"""Background jobs for cover letters (spec 5.3-5.6): generate, revise, repair and compile.

One worker thread runs the jobs. Every job reads its data in a short session, calls the LLM and the
compiler without a session, and writes the result in another short session. If the draft disappeared
meanwhile (application deleted, or its id reused by a newer draft), nothing is written and no PDF file is
left behind. Every error ends up in `error` as `{code, params, detail}`; `status` always ends `idle`.
"""
import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.errors import AppError, ConflictError
from app.latex import guard
from app.latex.compiler import Compiler, error_excerpt
from app.models import CoverLetter, CoverLetterMessage
from app.models.enums import CoverLetterFormat, CoverLetterStatus, MessageRole
from app.models.posting import utcnow
from app.services import cover_letter_llm
from app.services.cover_letter_llm import Answer, Context
from app.services.cover_letters import pdf_file, remove_pdf

log = logging.getLogger(__name__)

INTERRUPTED = {"code": "cover_letter_interrupted", "params": {}, "detail": "Interrupted by a restart"}
INTERNAL = {"code": "internal_error", "params": {}, "detail": "Unexpected error"}
COMPILE_DETAILS = {
    "latex_failed": "The LaTeX document does not compile",
    "latex_timeout": "Compiling the LaTeX document took too long",
    "latex_unavailable": "No LaTeX compiler is available",
}
MISSING_PREFIX = "Not available anymore: "
REPAIRABLE = ("latex_failed", "latex_forbidden")


class _Gone(Exception):
    """The job's draft no longer exists (or its id belongs to a newer draft): the job ends without writing."""


@dataclass
class _Ref:
    """Identity of the job's draft, snapshot when the job is submitted.

    SQLite may reuse a deleted id, so `created_at` must match as well.
    """

    id: int
    created_at: datetime


@dataclass
class _Draft:
    """What a job needs from the draft, read in a short session."""

    fmt: str
    template_content: str | None
    content: str
    error: dict | None
    compile_log: str | None
    ctx: Context | None = None
    system: str | None = None


class CoverLetterJobs:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings,
        compiler: Compiler,
        *,
        ask: Callable[..., Answer] = cover_letter_llm.ask,
    ):
        self._session_factory = session_factory
        self._settings = settings
        self.compiler = compiler  # public: the API reports `compiler.available()`
        self._ask = ask
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cover-letter")
        self._lock = threading.Lock()
        self._futures: set[Future] = set()

    # --- public API: each starts one job and returns immediately ------------------------------------
    # `created_at` is the draft's `created_at` at submit time: if the row with `cl_id` has another one when
    # the job runs (deleted, id reused by a newer draft), the job ends without touching it.

    def generate(self, cl_id: int, *, created_at: datetime) -> None:
        """Spec 5.3: LLM call with context + template, then (latex) compile with automatic repair."""
        self._submit(self._generate, _Ref(cl_id, created_at))

    def revise(self, cl_id: int, instruction: str, *, created_at: datetime) -> None:
        """Spec 5.4: LLM call with context, current content and the user's request (message stored by the router)."""
        self._submit(self._revise, _Ref(cl_id, created_at), instruction)

    def repair(self, cl_id: int, *, created_at: datetime) -> None:
        """Spec 5.5 (manual): one LLM call for the current compile error, then compile without further repair."""
        self._submit(self._repair, _Ref(cl_id, created_at))

    def compile_only(self, cl_id: int, *, created_at: datetime) -> None:
        """After a manual edit: compile the current content, no repair."""
        self._submit(self._compile_only, _Ref(cl_id, created_at))

    def recover(self, session: Session) -> int:
        """At start: drafts left `generating`/`compiling` become idle with `cover_letter_interrupted` (caller commits)."""
        result = session.execute(
            update(CoverLetter).where(CoverLetter.status != CoverLetterStatus.idle)
            .values(status=CoverLetterStatus.idle, error=INTERRUPTED)
        )
        return result.rowcount

    def wait_idle(self, timeout: float) -> bool:
        """Wait until all submitted jobs have finished (for tests); False on timeout."""
        with self._lock:
            pending = list(self._futures)
        _, not_done = wait(pending, timeout)
        return not not_done

    def shutdown(self) -> None:
        """Queued jobs are dropped (their drafts are recovered at the next start); a running job finishes."""
        self._executor.shutdown(wait=True, cancel_futures=True)

    # --- job frame ----------------------------------------------------------------------------------

    def _submit(self, fn: Callable[..., None], ref: _Ref, *args) -> Future | None:
        try:
            future = self._executor.submit(self._job, fn, ref, *args)
        except RuntimeError:  # shut down: the draft is recovered at the next start
            log.warning("cover letter job for %s not started: shutting down", ref.id)
            return None
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(self._forget)
        return future

    def _forget(self, future: Future) -> None:
        with self._lock:
            self._futures.discard(future)

    def _job(self, fn: Callable[..., None], ref: _Ref, *args) -> None:
        try:
            fn(ref, *args)
        except _Gone:
            log.info("cover letter %s was deleted before or while its job ran", ref.id)
        except AppError as exc:
            self._fail(ref, {"code": exc.code, "params": exc.params, "detail": exc.detail})
        except Exception:
            log.exception("cover letter job for %s failed", ref.id)
            self._fail(ref, dict(INTERNAL))

    def _fail(self, ref: _Ref, error: dict) -> None:
        try:
            self._write(ref, status=CoverLetterStatus.idle, error=error)
        except _Gone:
            pass
        except Exception:
            log.exception("could not record the failed cover letter job for %s", ref.id)

    def _get(self, session: Session, ref: _Ref) -> CoverLetter:
        """The job's draft; `_Gone` if it was deleted or its id now belongs to a newer draft."""
        cl = session.get(CoverLetter, ref.id)
        if cl is None or cl.created_at != ref.created_at:
            raise _Gone
        return cl

    # --- jobs ---------------------------------------------------------------------------------------

    def _generate(self, ref: _Ref) -> None:
        draft = self._load(ref, CoverLetterStatus.generating, with_context=True)
        template = draft.template_content if draft.fmt == CoverLetterFormat.latex else None
        answer = self._call(draft, cover_letter_llm.generate_text(draft.ctx, template))
        self._apply(ref, draft, answer, hint=True)
        self._finish(ref, draft, auto_repair=True)

    def _revise(self, ref: _Ref, instruction: str) -> None:
        draft = self._load(ref, CoverLetterStatus.generating, with_context=True)
        answer = self._call(draft, cover_letter_llm.revise_text(draft.ctx, draft.content, instruction))
        self._apply(ref, draft, answer, hint=True)
        self._finish(ref, draft, auto_repair=True)

    def _repair(self, ref: _Ref) -> None:
        draft = self._load(ref, CoverLetterStatus.generating, with_context=False)
        error = draft.error or {}
        if draft.fmt != CoverLetterFormat.latex or error.get("code") not in REPAIRABLE:
            raise ConflictError("cover_letter_nothing_to_repair", "There is no compile error to repair")
        self._add_context(ref, draft)
        params = error.get("params") or {}
        if error["code"] == "latex_forbidden" and "command" in params:
            text = cover_letter_llm.forbidden_text(draft.ctx, draft.content, params["command"], params.get("line", 0))
        else:
            text = cover_letter_llm.repair_text(draft.ctx, draft.content, draft.compile_log or "")
        answer = self._call(draft, text)
        self._apply(ref, draft, answer, hint=True)
        self._finish(ref, draft, auto_repair=False)

    def _compile_only(self, ref: _Ref) -> None:
        draft = self._load(ref, CoverLetterStatus.compiling, with_context=False)
        self._finish(ref, draft, auto_repair=False)

    # --- steps --------------------------------------------------------------------------------------

    def _load(self, ref: _Ref, status: CoverLetterStatus, *, with_context: bool) -> _Draft:
        """Snapshot the draft and mark it busy; optionally build the LLM context."""
        with self._session_factory() as session:
            cl = self._get(session, ref)
            draft = _Draft(cl.format.value, cl.template_content, cl.content, cl.error, cl.compile_log)
            cl.status = status
            session.commit()
        if with_context:
            self._add_context(ref, draft)
        return draft

    def _add_context(self, ref: _Ref, draft: _Draft) -> None:
        with self._session_factory() as session:
            cl = self._get(session, ref)
            draft.ctx = cover_letter_llm.build_context(session, cl.application, cl.context or {})
            draft.system = cover_letter_llm.system(session, draft.fmt, cl.language.value)

    def _call(self, draft: _Draft, user_text: str) -> Answer:
        # `limit_exceeded` is ignored: the router checks the limit before each job
        return self._ask(self._session_factory, draft.system, user_text, draft.fmt)

    def _apply(self, ref: _Ref, draft: _Draft, answer: Answer, *, hint: bool = False) -> None:
        """Store the new content and the note; the old PDF, error and compile log no longer match it."""
        messages = [answer.note] if answer.note else []
        if hint and draft.ctx is not None:
            missing = list(draft.ctx.missing_documents) + (["profile"] if draft.ctx.missing_profile else [])
            if missing:
                messages.append(MISSING_PREFIX + ", ".join(missing))
        latex = draft.fmt == CoverLetterFormat.latex
        draft.content = answer.document
        with self._session_factory() as session:
            cl = self._get(session, ref)
            cl.content = answer.document
            for text in messages:
                cl.messages.append(CoverLetterMessage(role=MessageRole.assistant, text=text))
            remove_pdf(session, self._settings, cl)
            cl.status = CoverLetterStatus.compiling if latex else CoverLetterStatus.idle
            cl.error, cl.compile_log = None, None
            session.commit()

    def _finish(self, ref: _Ref, draft: _Draft, *, auto_repair: bool) -> None:
        """Latex only: guard, compile, and (with `auto_repair`) one repair per error kind."""
        if draft.fmt != CoverLetterFormat.latex:
            return
        repaired_forbidden = repaired_failed = not auto_repair
        while True:
            violation = guard.check(draft.content, draft.template_content)
            if violation is not None:
                if not repaired_forbidden:
                    repaired_forbidden = True
                    text = cover_letter_llm.forbidden_text(draft.ctx, draft.content, violation.command, violation.line)
                    self._apply(ref, draft, self._call(draft, text))
                    continue
                self._compile_failed(ref, {
                    "code": "latex_forbidden",
                    "params": {"command": violation.command, "line": violation.line},
                    "detail": f"Line {violation.line} uses the forbidden command {violation.command}",
                }, None)
                return
            result = self.compiler.compile(draft.content)
            if result.error_code is None and result.pdf is not None:
                self._compiled(ref, result.pdf)
                return
            code = result.error_code or "latex_failed"
            excerpt = error_excerpt(result.log) if result.log else None
            if code == "latex_failed" and not repaired_failed:
                repaired_failed = True
                text = cover_letter_llm.repair_text(draft.ctx, draft.content, excerpt or "")
                self._apply(ref, draft, self._call(draft, text))
                continue
            self._compile_failed(
                ref, {"code": code, "params": {}, "detail": COMPILE_DETAILS.get(code, "Compiling failed")}, excerpt
            )
            return

    def _compiled(self, ref: _Ref, pdf: bytes) -> None:
        """Write the PDF while holding the write transaction, so a concurrent delete cannot orphan the file."""
        with self._session_factory() as session:
            cl = self._get(session, ref)
            path = pdf_file(self._settings, cl)
            cl.pdf_path = path.name
            cl.compiled_at = utcnow()
            cl.status = CoverLetterStatus.idle
            cl.error = None
            cl.compile_log = None
            written = False
            try:
                session.flush()  # takes the SQLite write lock
                current = session.scalar(select(CoverLetter.created_at).where(CoverLetter.id == ref.id))
                if current != ref.created_at:  # re-checked under the lock: still our draft
                    raise _Gone
                path.parent.mkdir(parents=True, exist_ok=True)
                written = True  # set before the write: a partly written file is ours too
                path.write_bytes(pdf)
                session.commit()
            except BaseException:
                if written:  # never delete a file this call did not write (e.g. a newer draft's PDF)
                    path.unlink(missing_ok=True)
                raise

    def _compile_failed(self, ref: _Ref, error: dict, compile_log: str | None) -> None:
        self._write(ref, status=CoverLetterStatus.idle, error=error, compile_log=compile_log, drop_pdf=True)

    def _write(self, ref: _Ref, *, drop_pdf: bool = False, **fields) -> None:
        with self._session_factory() as session:
            cl = self._get(session, ref)
            for name, value in fields.items():
                setattr(cl, name, value)
            if drop_pdf:
                remove_pdf(session, self._settings, cl)
            session.commit()

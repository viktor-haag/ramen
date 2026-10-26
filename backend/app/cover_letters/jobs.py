"""Background jobs for cover letters (spec 5.3-5.6): generate, revise, repair and compile.

One worker thread runs the jobs. Every job reads its data in a short session, calls the LLM and the
compiler without a session, and writes the result in another short session. If the draft disappeared
meanwhile (application deleted), nothing is written and no PDF file is left behind. Every error ends up
in `error` as `{code, params, detail}`; `status` always ends `idle`.
"""
import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass

from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.errors import AppError
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


class _Gone(Exception):
    """The draft no longer exists: the job ends without writing."""


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

    def generate(self, cl_id: int) -> None:
        """Spec 5.3: LLM call with context + template, then (latex) compile with automatic repair."""
        self._submit(self._generate, cl_id)

    def revise(self, cl_id: int, instruction: str) -> None:
        """Spec 5.4: LLM call with context, current content and the user's request (message stored by the router)."""
        self._submit(self._revise, cl_id, instruction)

    def repair(self, cl_id: int) -> None:
        """Spec 5.5 (manual): one LLM call for the current compile error, then compile without further repair."""
        self._submit(self._repair, cl_id)

    def compile_only(self, cl_id: int) -> None:
        """After a manual edit: compile the current content, no repair."""
        self._submit(self._compile_only, cl_id)

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

    def _submit(self, fn: Callable[..., None], cl_id: int, *args) -> Future | None:
        try:
            future = self._executor.submit(self._job, fn, cl_id, *args)
        except RuntimeError:  # shut down: the draft is recovered at the next start
            log.warning("cover letter job for %s not started: shutting down", cl_id)
            return None
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(self._forget)
        return future

    def _forget(self, future: Future) -> None:
        with self._lock:
            self._futures.discard(future)

    def _job(self, fn: Callable[..., None], cl_id: int, *args) -> None:
        try:
            fn(cl_id, *args)
        except _Gone:
            log.info("cover letter %s was deleted while its job ran", cl_id)
        except AppError as exc:
            self._fail(cl_id, {"code": exc.code, "params": exc.params, "detail": exc.detail})
        except Exception:
            log.exception("cover letter job for %s failed", cl_id)
            self._fail(cl_id, dict(INTERNAL))

    def _fail(self, cl_id: int, error: dict) -> None:
        try:
            self._write(cl_id, status=CoverLetterStatus.idle, error=error)
        except _Gone:
            pass
        except Exception:
            log.exception("could not record the failed cover letter job for %s", cl_id)

    # --- jobs ---------------------------------------------------------------------------------------

    def _generate(self, cl_id: int) -> None:
        draft = self._load(cl_id, CoverLetterStatus.generating, with_context=True)
        template = draft.template_content if draft.fmt == CoverLetterFormat.latex else None
        answer = self._call(draft, cover_letter_llm.generate_text(draft.ctx, template))
        self._apply(cl_id, draft, answer, hint=True)
        self._finish(cl_id, draft, auto_repair=True)

    def _revise(self, cl_id: int, instruction: str) -> None:
        draft = self._load(cl_id, CoverLetterStatus.generating, with_context=True)
        answer = self._call(draft, cover_letter_llm.revise_text(draft.ctx, draft.content, instruction))
        self._apply(cl_id, draft, answer, hint=True)
        self._finish(cl_id, draft, auto_repair=True)

    def _repair(self, cl_id: int) -> None:
        draft = self._load(cl_id, CoverLetterStatus.generating, with_context=True)
        error = draft.error or {}
        params = error.get("params") or {}
        if error.get("code") == "latex_forbidden" and "command" in params:
            text = cover_letter_llm.forbidden_text(draft.ctx, draft.content, params["command"], params.get("line", 0))
        else:
            text = cover_letter_llm.repair_text(draft.ctx, draft.content, draft.compile_log or "")
        answer = self._call(draft, text)
        self._apply(cl_id, draft, answer, hint=True)
        self._finish(cl_id, draft, auto_repair=False)

    def _compile_only(self, cl_id: int) -> None:
        draft = self._load(cl_id, CoverLetterStatus.compiling, with_context=False)
        self._finish(cl_id, draft, auto_repair=False)

    # --- steps --------------------------------------------------------------------------------------

    def _load(self, cl_id: int, status: CoverLetterStatus, *, with_context: bool) -> _Draft:
        """Read the draft and mark it busy; with `with_context` also build the LLM context and system prompt."""
        with self._session_factory() as session:
            cl = session.get(CoverLetter, cl_id)
            if cl is None:
                raise _Gone
            draft = _Draft(cl.format.value, cl.template_content, cl.content, cl.error, cl.compile_log)
            cl.status = status
            session.commit()
            if with_context:
                ctx = cover_letter_llm.build_context(session, cl.application, cl.context or {})
                draft.ctx = ctx
                draft.system = cover_letter_llm.system(session, draft.fmt, cl.language.value)
            return draft

    def _call(self, draft: _Draft, user_text: str) -> Answer:
        # `limit_exceeded` is ignored: the router checks the limit before each job
        return self._ask(self._session_factory, draft.system, user_text, draft.fmt)

    def _apply(self, cl_id: int, draft: _Draft, answer: Answer, *, hint: bool = False) -> None:
        """Store the new content and the note; the old PDF no longer matches the content."""
        messages = [answer.note] if answer.note else []
        if hint and draft.ctx is not None:
            missing = list(draft.ctx.missing_documents) + (["profile"] if draft.ctx.missing_profile else [])
            if missing:
                messages.append(MISSING_PREFIX + ", ".join(missing))
        latex = draft.fmt == CoverLetterFormat.latex
        draft.content = answer.document
        with self._session_factory() as session:
            cl = session.get(CoverLetter, cl_id)
            if cl is None:
                raise _Gone
            cl.content = answer.document
            for text in messages:
                cl.messages.append(CoverLetterMessage(role=MessageRole.assistant, text=text))
            remove_pdf(self._settings, cl)
            cl.status = CoverLetterStatus.compiling if latex else CoverLetterStatus.idle
            if not latex:
                cl.error, cl.compile_log = None, None
            session.commit()

    def _finish(self, cl_id: int, draft: _Draft, *, auto_repair: bool) -> None:
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
                    self._apply(cl_id, draft, self._call(draft, text))
                    continue
                self._compile_failed(cl_id, {
                    "code": "latex_forbidden",
                    "params": {"command": violation.command, "line": violation.line},
                    "detail": f"Line {violation.line} uses the forbidden command {violation.command}",
                }, None)
                return
            result = self.compiler.compile(draft.content)
            if result.error_code is None and result.pdf is not None:
                self._compiled(cl_id, result.pdf)
                return
            code = result.error_code or "latex_failed"
            excerpt = error_excerpt(result.log) if result.log else None
            if code == "latex_failed" and not repaired_failed:
                repaired_failed = True
                text = cover_letter_llm.repair_text(draft.ctx, draft.content, excerpt or "")
                self._apply(cl_id, draft, self._call(draft, text))
                continue
            self._compile_failed(
                cl_id, {"code": code, "params": {}, "detail": COMPILE_DETAILS.get(code, "Compiling failed")}, excerpt
            )
            return

    def _compiled(self, cl_id: int, pdf: bytes) -> None:
        """Write the PDF while holding the write transaction, so a concurrent delete cannot orphan the file."""
        with self._session_factory() as session:
            cl = session.get(CoverLetter, cl_id)
            if cl is None:
                raise _Gone
            path = pdf_file(self._settings, cl)
            cl.pdf_path = path.name
            cl.compiled_at = utcnow()
            cl.status = CoverLetterStatus.idle
            cl.error = None
            cl.compile_log = None
            try:
                session.flush()  # takes the SQLite write lock; the row is known to exist
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(pdf)
                session.commit()
            except BaseException:
                path.unlink(missing_ok=True)
                raise

    def _compile_failed(self, cl_id: int, error: dict, compile_log: str | None) -> None:
        self._write(cl_id, status=CoverLetterStatus.idle, error=error, compile_log=compile_log, drop_pdf=True)

    def _write(self, cl_id: int, *, drop_pdf: bool = False, **fields) -> None:
        with self._session_factory() as session:
            cl = session.get(CoverLetter, cl_id)
            if cl is None:
                raise _Gone
            for name, value in fields.items():
                setattr(cl, name, value)
            if drop_pdf:
                remove_pdf(self._settings, cl)
            session.commit()

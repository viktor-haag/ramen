"""Cover letter state service and background jobs (spec 5.3-5.6), with a fake LLM and a fake compiler."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.cover_letters.jobs import CoverLetterJobs
from app.errors import ConflictError, NotFoundError, UpstreamError
from app.latex.compiler import CompileResult
from app.main import create_app
from app.models import (
    AppSetting,
    Application,
    CoverLetter,
    CoverLetterMessage,
    CoverLetterTemplate,
    LLMConfig,
    LLMProvider,
    LLMUsage,
    Posting,
    ProfileDocument,
    UserProfile,
)
from app.models.enums import CoverLetterFormat, CoverLetterLanguage, CoverLetterStatus, DocumentKind, MessageRole
from app.models.posting import utcnow
from app.services import cover_letter_llm, cover_letters
from app.services.cover_letter_llm import Answer

TIMEOUT = 10
TEMPLATE = "\\documentclass{article}\n\\begin{document}\nLorem ipsum.\n\\end{document}"
LETTER = "\\documentclass{article}\n\\begin{document}\nDear team, \\textbf{hello}.\n\\end{document}"
FIXED = "\\documentclass{article}\n\\begin{document}\nDear team, hello.\n\\end{document}"
FORBIDDEN = "\\documentclass{article}\n\\begin{document}\n\\input{/x}\n\\end{document}"
PDF = b"%PDF-1.5 fake"
FAIL_LOG = "This is TeX\n! Undefined control sequence.\nl.3 \\foo\nmore\nmore2\nunrelated tail"


class FakeAsk:
    """Returns the scripted answers (an Answer, or an exception to raise) in order; records every call."""

    def __init__(self, *items, on_call=None):
        self.items = list(items)
        self.calls: list[tuple[str, str, str]] = []
        self.on_call = on_call

    def __call__(self, session_factory, system, user_text, fmt):
        self.calls.append((system, user_text, fmt))
        if self.on_call:
            self.on_call()
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeCompiler:
    def __init__(self, *results):
        self.results = list(results)
        self.calls: list[str] = []

    def available(self) -> bool:
        return True

    def compile(self, tex: str) -> CompileResult:
        self.calls.append(tex)
        return self.results.pop(0)


def ok() -> CompileResult:
    return CompileResult(PDF, "log", None)


def failed() -> CompileResult:
    return CompileResult(None, FAIL_LOG, "latex_failed")


def answer(document=LETTER, note="Phone number missing.") -> Answer:
    return Answer(document, note, False)


@pytest.fixture
def sf(client, app):
    return app.state.session_factory


@pytest.fixture
def make_jobs(sf, settings):
    made = []

    def make(ask, compiler=None):
        jobs = CoverLetterJobs(sf, settings, compiler or FakeCompiler(), ask=ask)
        made.append(jobs)
        return jobs

    yield make
    for jobs in made:
        jobs.shutdown()


def seed(sf, *, fmt=CoverLetterFormat.latex, content="", status=CoverLetterStatus.generating, context=None):
    with sf() as s:
        posting = Posting(source="s", external_id="1", title="Dev", company="Acme", description="Build APIs.")
        s.add(posting)
        application = Application(posting=posting)
        s.add(application)
        s.add(UserProfile(id=1, profile_markdown="## Summary\nEngineer.", version=1))
        cl = CoverLetter(
            application=application, format=fmt, language=CoverLetterLanguage.en,
            template_content=TEMPLATE if fmt == CoverLetterFormat.latex else None,
            context=context or {"profile": True, "document_ids": [], "notes": ""},
            content=content, status=status,
        )
        s.add(cl)
        s.commit()
        return cl.id


def load(sf, cl_id) -> CoverLetter | None:
    with sf() as s:
        cl = s.get(CoverLetter, cl_id)
        if cl is not None:
            cl.messages  # load the history before the session closes
        return cl


def run(jobs, method, *args):
    getattr(jobs, method)(*args)
    assert jobs.wait_idle(TIMEOUT)


# --- jobs ----------------------------------------------------------------------------------------


def test_generate_latex_ok(sf, settings, make_jobs):
    cl_id = seed(sf)
    ask, compiler = FakeAsk(answer()), FakeCompiler(ok())
    run(make_jobs(ask, compiler), "generate", cl_id)
    cl = load(sf, cl_id)
    assert cl.content == LETTER and cl.status == CoverLetterStatus.idle and cl.error is None
    assert [(m.role, m.text) for m in cl.messages] == [(MessageRole.assistant, "Phone number missing.")]
    assert cl.pdf_path == f"{cl_id}.pdf" and cl.compiled_at is not None and cl.compile_log is None
    assert cover_letters.pdf_file(settings, cl).read_bytes() == PDF
    assert compiler.calls == [LETTER]
    _, user_text, fmt = ask.calls[0]
    assert fmt == "latex" and "<template>" in user_text and "Lorem ipsum." in user_text


def test_generate_text_never_compiles(sf, make_jobs):
    cl_id = seed(sf, fmt=CoverLetterFormat.text)
    compiler = FakeCompiler()
    ask = FakeAsk(answer("Dear team,\nhello."))
    run(make_jobs(ask, compiler), "generate", cl_id)
    cl = load(sf, cl_id)
    assert cl.content == "Dear team,\nhello." and cl.status == CoverLetterStatus.idle and cl.error is None
    assert cl.pdf_path is None and compiler.calls == []
    assert ask.calls[0][2] == "text" and "<template>" not in ask.calls[0][1]


def test_compile_failure_repairs_once_then_keeps_error(sf, settings, make_jobs):
    cl_id = seed(sf)
    ask = FakeAsk(answer(), answer(FIXED, "Fixed it."))
    compiler = FakeCompiler(failed(), failed())
    run(make_jobs(ask, compiler), "generate", cl_id)
    cl = load(sf, cl_id)
    assert len(ask.calls) == 2  # no third call
    repair_text = ask.calls[1][1]
    assert cover_letter_llm.REPAIR_INSTRUCTION in repair_text and "Undefined control sequence" in repair_text
    assert "unrelated tail" not in repair_text  # only the excerpt goes to the LLM
    assert compiler.calls == [LETTER, FIXED]
    assert cl.content == FIXED and cl.status == CoverLetterStatus.idle
    assert cl.error["code"] == "latex_failed" and cl.compile_log and "Undefined control sequence" in cl.compile_log
    assert "unrelated tail" not in cl.compile_log
    assert cl.pdf_path is None and not cover_letters.pdf_file(settings, cl).exists()
    assert [m.text for m in cl.messages] == ["Phone number missing.", "Fixed it."]


def test_compile_failure_repair_succeeds(sf, settings, make_jobs):
    cl_id = seed(sf)
    run(make_jobs(FakeAsk(answer(), answer(FIXED)), FakeCompiler(failed(), ok())), "generate", cl_id)
    cl = load(sf, cl_id)
    assert cl.error is None and cl.compile_log is None and cl.content == FIXED
    assert cover_letters.pdf_file(settings, cl).read_bytes() == PDF


def test_forbidden_command_repaired_once_then_error(sf, make_jobs):
    cl_id = seed(sf)
    ask = FakeAsk(answer(FORBIDDEN), answer(FORBIDDEN, "Still there."))
    compiler = FakeCompiler()
    run(make_jobs(ask, compiler), "generate", cl_id)
    cl = load(sf, cl_id)
    assert len(ask.calls) == 2 and "forbidden \\input" in ask.calls[1][1] and "Line 3" in ask.calls[1][1]
    assert compiler.calls == []
    assert cl.error["code"] == "latex_forbidden"
    assert cl.error["params"] == {"command": "\\input", "line": 3}
    assert cl.status == CoverLetterStatus.idle and cl.pdf_path is None


def test_forbidden_command_repaired_then_compiles(sf, make_jobs):
    cl_id = seed(sf)
    compiler = FakeCompiler(ok())
    run(make_jobs(FakeAsk(answer(FORBIDDEN), answer(LETTER)), compiler), "generate", cl_id)
    cl = load(sf, cl_id)
    assert cl.error is None and cl.content == LETTER and compiler.calls == [LETTER]


def test_compile_only_does_not_repair(sf, make_jobs):
    cl_id = seed(sf, content=LETTER, status=CoverLetterStatus.compiling)
    ask, compiler = FakeAsk(), FakeCompiler(failed())
    run(make_jobs(ask, compiler), "compile_only", cl_id)
    cl = load(sf, cl_id)
    assert ask.calls == [] and compiler.calls == [LETTER]
    assert cl.error["code"] == "latex_failed" and cl.compile_log and cl.status == CoverLetterStatus.idle


def test_compile_only_forbidden_does_not_repair(sf, make_jobs):
    cl_id = seed(sf, content=FORBIDDEN, status=CoverLetterStatus.compiling)
    ask, compiler = FakeAsk(), FakeCompiler()
    run(make_jobs(ask, compiler), "compile_only", cl_id)
    cl = load(sf, cl_id)
    assert ask.calls == [] and compiler.calls == [] and cl.error["code"] == "latex_forbidden"


def test_compile_only_success_writes_pdf(sf, settings, make_jobs):
    cl_id = seed(sf, content=LETTER, status=CoverLetterStatus.compiling)
    run(make_jobs(FakeAsk(), FakeCompiler(ok())), "compile_only", cl_id)
    cl = load(sf, cl_id)
    assert cl.error is None and cover_letters.pdf_file(settings, cl).read_bytes() == PDF


def test_manual_repair_asks_exactly_once(sf, make_jobs):
    cl_id = seed(sf, content=LETTER, status=CoverLetterStatus.idle)
    with sf() as s:
        cl = s.get(CoverLetter, cl_id)
        cl.error = {"code": "latex_failed", "params": {}, "detail": "x"}
        cl.compile_log = "! Undefined control sequence."
        s.commit()
    ask = FakeAsk(answer(FIXED))
    compiler = FakeCompiler(failed())
    run(make_jobs(ask, compiler), "repair", cl_id)
    cl = load(sf, cl_id)
    assert len(ask.calls) == 1 and cover_letter_llm.REPAIR_INSTRUCTION in ask.calls[0][1]
    assert "Undefined control sequence" in ask.calls[0][1] and "<template>" not in ask.calls[0][1]
    assert compiler.calls == [FIXED] and cl.error["code"] == "latex_failed"


def test_manual_repair_of_forbidden_uses_forbidden_text(sf, make_jobs):
    cl_id = seed(sf, content=FORBIDDEN, status=CoverLetterStatus.idle)
    with sf() as s:
        s.get(CoverLetter, cl_id).error = {
            "code": "latex_forbidden", "params": {"command": "\\input", "line": 3}, "detail": "x"
        }
        s.commit()
    ask, compiler = FakeAsk(answer(LETTER)), FakeCompiler(ok())
    run(make_jobs(ask, compiler), "repair", cl_id)
    assert len(ask.calls) == 1 and "forbidden \\input" in ask.calls[0][1]
    assert load(sf, cl_id).error is None


def test_revise_uses_current_and_instruction(sf, make_jobs):
    cl_id = seed(sf, content=LETTER, status=CoverLetterStatus.idle)
    ask, compiler = FakeAsk(answer(FIXED, "Shorter now.")), FakeCompiler(ok())
    run(make_jobs(ask, compiler), "revise", cl_id, "Make it shorter")
    cl = load(sf, cl_id)
    user_text = ask.calls[0][1]
    assert "<current>" in user_text and "Dear team" in user_text and user_text.endswith("Make it shorter")
    assert "<template>" not in user_text
    assert cl.content == FIXED and [m.text for m in cl.messages] == ["Shorter now."]


def test_llm_error_keeps_content(sf, make_jobs):
    cl_id = seed(sf, content=LETTER, status=CoverLetterStatus.idle)
    compiler = FakeCompiler()
    run(make_jobs(FakeAsk(UpstreamError("llm_timeout", "slow", {"reason": "t"})), compiler), "revise", cl_id, "x")
    cl = load(sf, cl_id)
    assert cl.error == {"code": "llm_timeout", "params": {"reason": "t"}, "detail": "slow"}
    assert cl.status == CoverLetterStatus.idle and cl.content == LETTER and compiler.calls == []


def test_unexpected_exception_is_internal_error(sf, make_jobs):
    cl_id = seed(sf)
    run(make_jobs(FakeAsk(RuntimeError("boom"))), "generate", cl_id)
    cl = load(sf, cl_id)
    assert cl.error == {"code": "internal_error", "params": {}, "detail": "Unexpected error"}
    assert cl.status == CoverLetterStatus.idle


def test_application_deleted_during_llm_call(sf, settings, make_jobs):
    cl_id = seed(sf)

    def delete_application():
        with sf() as s:
            s.delete(s.scalars(select(Application)).one())
            s.commit()

    run(make_jobs(FakeAsk(answer(), on_call=delete_application), FakeCompiler(ok())), "generate", cl_id)
    assert load(sf, cl_id) is None
    assert list(settings.cover_letters_dir.iterdir()) == []


def test_application_deleted_during_compile(sf, settings, make_jobs):
    cl_id = seed(sf)

    class DeletingCompiler(FakeCompiler):
        def compile(self, tex):
            with sf() as s:
                s.delete(s.scalars(select(Application)).one())
                s.commit()
            return super().compile(tex)

    run(make_jobs(FakeAsk(answer()), DeletingCompiler(ok())), "generate", cl_id)
    assert load(sf, cl_id) is None
    assert list(settings.cover_letters_dir.iterdir()) == []


def test_missing_document_and_profile_hint(sf, make_jobs):
    with sf() as s:
        s.add(ProfileDocument(filename="f", display_name="cv.pdf", stored_path="p", mime="text/plain",
                              kind=DocumentKind.text, text="CV"))
        s.commit()
        doc_id = s.scalars(select(ProfileDocument.id)).one()
    cl_id = seed(sf, fmt=CoverLetterFormat.text, context={"profile": True, "document_ids": [doc_id, 99], "notes": ""})
    with sf() as s:
        s.get(UserProfile, 1).profile_markdown = ""
        s.commit()
    run(make_jobs(FakeAsk(answer("Text"))), "generate", cl_id)
    texts = [m.text for m in load(sf, cl_id).messages]
    assert texts[0] == "Phone number missing."
    assert texts[1].startswith("Not available anymore:") and "#99" in texts[1] and "profile" in texts[1]


def test_recover_resets_stuck_rows(sf, make_jobs):
    stuck = seed(sf)
    jobs = make_jobs(FakeAsk())
    with sf() as s:
        assert jobs.recover(s) == 1
        s.commit()
    cl = load(sf, stuck)
    assert cl.status == CoverLetterStatus.idle
    assert cl.error == {"code": "cover_letter_interrupted", "params": {}, "detail": "Interrupted by a restart"}


def test_lifespan_recovers_on_start(sf, settings):
    stuck = seed(sf)
    with TestClient(create_app(settings)) as c:
        assert c.app.state.cover_letter_jobs.compiler is not None
    cl = load(sf, stuck)
    assert cl.status == CoverLetterStatus.idle and cl.error["code"] == "cover_letter_interrupted"
    assert settings.cover_letters_dir.is_dir()


def test_jobs_expose_compiler(sf, settings):
    compiler = FakeCompiler()
    jobs = CoverLetterJobs(sf, settings, compiler)
    try:
        assert jobs.compiler is compiler
    finally:
        jobs.shutdown()


# --- service -------------------------------------------------------------------------------------


def data(fmt="latex", template_id=None, language="de", context=None):
    return SimpleNamespace(
        format=CoverLetterFormat(fmt), template_id=template_id, language=CoverLetterLanguage(language),
        context=SimpleNamespace(**(context or {"profile": False, "document_ids": [1], "notes": "n"})),
    )


def test_get_for_application_and_ensure_idle(sf):
    cl_id = seed(sf)
    with sf() as s:
        app_id = s.get(CoverLetter, cl_id).application_id
        cl = cover_letters.get_for_application(s, app_id)
        assert cl.id == cl_id
        with pytest.raises(ConflictError) as e:
            cover_letters.ensure_idle(cl)
        assert e.value.code == "cover_letter_busy"
        cl.status = CoverLetterStatus.idle
        cover_letters.ensure_idle(cl)
        with pytest.raises(NotFoundError) as e:
            cover_letters.get_for_application(s, 9999)
        assert e.value.code == "cover_letter_not_found"


def test_replace_creates_and_resets(sf, settings):
    cl_id = seed(sf, content=LETTER, status=CoverLetterStatus.idle)
    with sf() as s:
        cl = s.get(CoverLetter, cl_id)
        app_id = cl.application_id
        cover_letters.add_message(s, cl, MessageRole.user, "hi")
        cl.pdf_path, cl.error = f"{cl_id}.pdf", {"code": "x", "params": {}, "detail": "x"}
        s.commit()
    settings.cover_letters_dir.mkdir(parents=True, exist_ok=True)
    (settings.cover_letters_dir / f"{cl_id}.pdf").write_bytes(PDF)
    with sf() as s:
        builtin = s.scalars(select(CoverLetterTemplate).where(CoverLetterTemplate.builtin.is_(True))).one()
        cl = cover_letters.replace(s, settings, app_id, data(template_id=builtin.id))
        s.commit()
        assert cl.id == cl_id and cl.template_id == builtin.id and cl.template_content == builtin.content
        assert cl.content == "" and cl.status == CoverLetterStatus.generating and cl.error is None
        assert cl.pdf_path is None and cl.language == CoverLetterLanguage.de
        assert cl.context == {"profile": False, "document_ids": [1], "notes": "n"}
        assert s.scalars(select(CoverLetterMessage)).all() == []
    assert not (settings.cover_letters_dir / f"{cl_id}.pdf").exists()


def test_replace_new_text_and_unknown_template(sf, settings):
    with sf() as s:
        posting = Posting(source="s", external_id="2", title="Dev", company="Acme")
        application = Application(posting=posting)
        s.add_all([posting, application])
        s.commit()
        with pytest.raises(NotFoundError) as e:
            cover_letters.replace(s, settings, application.id, data(template_id=9999))
        assert e.value.code == "template_not_found"
        cl = cover_letters.replace(s, settings, application.id, data("text"))
        s.commit()
        assert cl.format == CoverLetterFormat.text and cl.template_content is None and cl.template_id is None


def test_delete_removes_pdf(sf, settings):
    cl_id = seed(sf, status=CoverLetterStatus.idle)
    settings.cover_letters_dir.mkdir(parents=True, exist_ok=True)
    (settings.cover_letters_dir / f"{cl_id}.pdf").write_bytes(PDF)
    with sf() as s:
        cover_letters.delete(s, settings, s.get(CoverLetter, cl_id))
        s.commit()
    assert load(sf, cl_id) is None and not (settings.cover_letters_dir / f"{cl_id}.pdf").exists()


def test_ensure_within_limit(sf):
    with sf() as s:
        with pytest.raises(ConflictError) as e:
            cover_letters.ensure_within_limit(s)
        assert e.value.code == "llm_not_configured"
        s.add(LLMConfig(name="C", provider=LLMProvider.anthropic, model="m", api_key="sk-test-1234",
                        is_default=True, daily_limit_kind="none"))
        s.commit()
        cover_letters.ensure_within_limit(s)
        s.add(LLMUsage(at=utcnow(), config_id=None, purpose="fit", input_tokens=5, output_tokens=0, ok=True))
        for key, val in (("daily_limit_kind", "tokens"), ("daily_limit_value", 1)):
            row = s.get(AppSetting, key)
            if row is None:
                s.add(AppSetting(key=key, value=val))
            else:
                row.value = val
        s.commit()
        with pytest.raises(ConflictError) as e:
            cover_letters.ensure_within_limit(s)
        assert e.value.code == "daily_limit_reached"
        assert e.value.params == {"scope": "global", "config_name": None}

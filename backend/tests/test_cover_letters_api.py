"""Cover letter API (spec 7.2) with fake background jobs: endpoints, attachment, source, PDF, permissions."""
import os
from pathlib import Path
from urllib.parse import quote, unquote

import pytest
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.models import (
    AppSetting,
    Application,
    Attachment,
    AttachmentKind,
    CoverLetter,
    CoverLetterMessage,
    CoverLetterTemplate,
    LLMUsage,
    Posting,
    ProfileDocument,
)
from app.models.enums import CoverLetterStatus, DocumentKind
from test_profile_docs import add_config

PDF = b"%PDF-1.4 fake"
FAKE_CONTENT = "FAKE LETTER"


class FakeCompiler:
    def __init__(self, available=True):
        self._available = available

    def available(self) -> bool:
        return self._available


class FakeJobs:
    """Records calls; `generate`/`revise`/`repair` synchronously store a fixed text and go idle.

    Every call must carry the draft's current `created_at` (the job's identity snapshot at submit time).
    """

    def __init__(self, session_factory):
        self._sf = session_factory
        self.compiler = FakeCompiler()
        self.calls: list[tuple] = []

    def _done(self, cl_id, created_at, content=FAKE_CONTENT):
        with self._sf() as s:
            cl = s.get(CoverLetter, cl_id)
            assert created_at is not None and cl.created_at == created_at
            if content is not None:
                cl.content = content
            cl.status = CoverLetterStatus.idle
            s.commit()

    def generate(self, cl_id, *, created_at):
        self.calls.append(("generate", cl_id))
        self._done(cl_id, created_at)

    def revise(self, cl_id, instruction, *, created_at):
        self.calls.append(("revise", cl_id, instruction))
        self._done(cl_id, created_at)

    def repair(self, cl_id, *, created_at):
        self.calls.append(("repair", cl_id))
        self._done(cl_id, created_at)

    def compile_only(self, cl_id, *, created_at):
        self.calls.append(("compile_only", cl_id))
        self._done(cl_id, created_at, content=None)

    def wait_idle(self, timeout):
        return True

    def recover(self, session):
        return 0

    def shutdown(self):
        pass


@pytest.fixture
def jobs(client, app):
    original = app.state.cover_letter_jobs
    fake = FakeJobs(app.state.session_factory)
    app.state.cover_letter_jobs = fake
    yield fake
    app.state.cover_letter_jobs = original


def make_application(app, company="Acme"):
    with app.state.session_factory() as s:
        posting = Posting(source="s", external_id=company or "none", title="Dev", company=company)
        application = Application(posting=posting)
        s.add(application)
        s.commit()
        return application.id


def builtin_id(app):
    with app.state.session_factory() as s:
        return s.scalar(select(CoverLetterTemplate.id).where(CoverLetterTemplate.builtin.is_(True)))


def url(app_id, suffix=""):
    return f"/api/applications/{app_id}/cover-letter{suffix}"


def body(fmt="latex", template_id=None, **extra):
    data = {"format": fmt, "language": "de", "context": {"profile": True, "document_ids": [], "notes": "n"}}
    if template_id is not None:
        data["template_id"] = template_id
    return {**data, **extra}


def set_fields(app, app_id, **fields):
    with app.state.session_factory() as s:
        cl = s.scalar(select(CoverLetter).where(CoverLetter.application_id == app_id))
        for name, value in fields.items():
            setattr(cl, name, value)
        s.commit()
        return cl.id


def create(client, app, fmt="latex"):
    app_id = make_application(app)
    tid = builtin_id(app) if fmt == "latex" else None
    r = client.post(url(app_id), json=body(fmt, tid))
    assert r.status_code == 202, r.text
    return app_id, r.json()


# --- create / replace -----------------------------------------------------------------------------


def test_post_creates_and_returns_202(client, app, jobs):
    add_config(client)
    app_id = make_application(app)
    r = client.post(url(app_id), json=body(template_id=builtin_id(app)))
    assert r.status_code == 202
    out = r.json()
    assert out["status"] == "generating" and out["format"] == "latex" and out["template_name"] == "Deedy"
    assert out["application_id"] == app_id and out["language"] == "de"
    assert out["context"] == {"profile": True, "document_ids": [], "notes": "n"}
    assert out["pdf_available"] is False and out["compiler_available"] is True
    assert out["messages"] == [] and out["error"] is None
    assert jobs.calls == [("generate", out["id"])]
    got = client.get(url(app_id)).json()
    assert got["content"] == FAKE_CONTENT and got["status"] == "idle"


def test_second_post_replaces_and_clears_messages(client, app, jobs):
    add_config(client)
    app_id, first = create(client, app)
    assert client.post(url(app_id, "/messages"), json={"text": "shorter"}).status_code == 202
    assert len(client.get(url(app_id)).json()["messages"]) == 1
    r = client.post(url(app_id), json=body("text"))
    assert r.status_code == 202
    out = r.json()
    assert out["id"] == first["id"] and out["format"] == "text" and out["template_name"] is None
    assert out["messages"] == [] and out["content"] == ""
    with app.state.session_factory() as s:
        assert s.scalars(select(CoverLetterMessage)).all() == []


def test_post_latex_requires_template(client, app, jobs):
    add_config(client)
    app_id = make_application(app)
    r = client.post(url(app_id), json=body("latex"))
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    assert jobs.calls == []


def test_post_notes_limit(client, app, jobs):
    add_config(client)
    app_id = make_application(app)
    data = body("text")
    data["context"]["notes"] = "x" * 5001
    assert client.post(url(app_id), json=data).status_code == 422


def test_post_context_too_large_keeps_old_draft(client, app, jobs, settings):
    """Spec 5.1: the POST itself answers 422; the existing draft (content, chat, PDF) stays unchanged."""
    add_config(client)
    app_id, first = create(client, app)
    assert client.post(url(app_id, "/messages"), json={"text": "shorter"}).status_code == 202
    pdf = settings.cover_letters_dir / f"{first['id']}.pdf"
    pdf.write_bytes(PDF)
    set_fields(app, app_id, pdf_path=pdf.name)
    before = client.get(url(app_id)).json()
    with app.state.session_factory() as s:
        docs = [ProfileDocument(filename="f", display_name=f"d{i}", stored_path="p", mime="text/plain",
                                kind=DocumentKind.text, text="y" * 20_000) for i in range(7)]
        s.add_all(docs)
        s.commit()
        ids = [d.id for d in docs]
    jobs.calls.clear()
    data = body("text")
    data["context"] = {"profile": False, "document_ids": ids, "notes": ""}
    r = client.post(url(app_id), json=data)
    assert r.status_code == 422 and r.json()["code"] == "cover_letter_context_too_large"
    assert jobs.calls == []
    after = client.get(url(app_id)).json()
    assert after == before
    assert after["content"] == FAKE_CONTENT and len(after["messages"]) == 1 and after["pdf_available"] is True
    assert pdf.read_bytes() == PDF


def test_post_while_busy(client, app, jobs):
    add_config(client)
    app_id, _ = create(client, app)
    set_fields(app, app_id, status=CoverLetterStatus.generating)
    jobs.calls.clear()
    r = client.post(url(app_id), json=body("text"))
    assert r.status_code == 409 and r.json()["code"] == "cover_letter_busy"
    assert jobs.calls == []


def test_post_without_llm_config(client, app, jobs):
    app_id = make_application(app)
    r = client.post(url(app_id), json=body("text"))
    assert r.status_code == 409 and r.json()["code"] == "llm_not_configured"
    assert jobs.calls == []


def test_post_daily_limit(client, app, jobs):
    add_config(client)
    app_id = make_application(app)
    with app.state.session_factory() as s:
        s.add_all([AppSetting(key="daily_limit_kind", value="tokens"), AppSetting(key="daily_limit_value", value=10)])
        s.add(LLMUsage(purpose="fit", input_tokens=10, output_tokens=0, ok=True))
        s.commit()
    r = client.post(url(app_id), json=body("text"))
    assert r.status_code == 409 and r.json()["code"] == "daily_limit_reached"
    assert jobs.calls == []
    with app.state.session_factory() as s:
        assert s.scalars(select(CoverLetter)).all() == []


def test_post_unknown_application(client, app, jobs):
    add_config(client)
    r = client.post(url(9999), json=body("text"))
    assert r.status_code == 404 and r.json()["code"] == "application_not_found"


def test_get_without_draft(client, app, jobs):
    app_id = make_application(app)
    r = client.get(url(app_id))
    assert r.status_code == 404 and r.json()["code"] == "cover_letter_not_found"


# --- content / messages / repair -------------------------------------------------------------------


def test_put_content_latex_compiles(client, app, jobs):
    add_config(client)
    app_id, out = create(client, app)
    set_fields(app, app_id, error={"code": "latex_failed", "params": {}, "detail": "x"}, compile_log="log")
    jobs.calls.clear()
    r = client.put(url(app_id, "/content"), json={"content": "\\documentclass{article}"})
    assert r.status_code == 202
    assert r.json()["status"] == "compiling" and r.json()["content"] == "\\documentclass{article}"
    assert r.json()["error"] is None and r.json()["compile_log"] is None
    assert jobs.calls == [("compile_only", out["id"])]


def test_put_content_text_saves_without_job(client, app, jobs):
    add_config(client)
    app_id, _ = create(client, app, "text")
    jobs.calls.clear()
    r = client.put(url(app_id, "/content"), json={"content": "Dear team"})
    assert r.status_code == 200
    assert r.json()["status"] == "idle" and r.json()["content"] == "Dear team"
    assert jobs.calls == []


def test_put_content_limit_and_busy(client, app, jobs):
    add_config(client)
    app_id, _ = create(client, app, "text")
    assert client.put(url(app_id, "/content"), json={"content": "x" * 200_001}).status_code == 422
    set_fields(app, app_id, status=CoverLetterStatus.compiling)
    r = client.put(url(app_id, "/content"), json={"content": "x"})
    assert r.status_code == 409 and r.json()["code"] == "cover_letter_busy"


def test_messages_starts_revision(client, app, jobs):
    add_config(client)
    app_id, out = create(client, app)
    jobs.calls.clear()
    r = client.post(url(app_id, "/messages"), json={"text": "  Make it shorter  "})
    assert r.status_code == 202
    assert r.json()["status"] == "generating"
    assert [(m["role"], m["text"]) for m in r.json()["messages"]] == [("user", "Make it shorter")]
    assert jobs.calls == [("revise", out["id"], "Make it shorter")]


@pytest.mark.parametrize("text", ["", "   ", "x" * 2001], ids=["empty", "blank", "too_long"])
def test_messages_validation(client, app, jobs, text):
    add_config(client)
    app_id, _ = create(client, app)
    jobs.calls.clear()
    assert client.post(url(app_id, "/messages"), json={"text": text}).status_code == 422
    assert jobs.calls == []


def test_messages_limit_and_busy(client, app, jobs):
    add_config(client)
    app_id, _ = create(client, app)
    set_fields(app, app_id, status=CoverLetterStatus.generating)
    r = client.post(url(app_id, "/messages"), json={"text": "hi"})
    assert r.json()["code"] == "cover_letter_busy"
    set_fields(app, app_id, status=CoverLetterStatus.idle)
    with app.state.session_factory() as s:
        s.add_all([AppSetting(key="daily_limit_kind", value="tokens"), AppSetting(key="daily_limit_value", value=10)])
        s.add(LLMUsage(purpose="fit", input_tokens=10, output_tokens=0, ok=True))
        s.commit()
    r = client.post(url(app_id, "/messages"), json={"text": "hi"})
    assert r.status_code == 409 and r.json()["code"] == "daily_limit_reached"
    assert client.get(url(app_id)).json()["messages"] == []


def test_repair_without_error(client, app, jobs):
    add_config(client)
    app_id, _ = create(client, app)
    jobs.calls.clear()
    r = client.post(url(app_id, "/repair"))
    assert r.status_code == 409 and r.json()["code"] == "cover_letter_nothing_to_repair"
    set_fields(app, app_id, error={"code": "latex_timeout", "params": {}, "detail": "x"})
    assert client.post(url(app_id, "/repair")).json()["code"] == "cover_letter_nothing_to_repair"
    assert jobs.calls == []


@pytest.mark.parametrize("code", ["latex_failed", "latex_forbidden"])
def test_repair_starts_job(client, app, jobs, code):
    add_config(client)
    app_id, out = create(client, app)
    set_fields(app, app_id, error={"code": code, "params": {}, "detail": "x"})
    jobs.calls.clear()
    r = client.post(url(app_id, "/repair"))
    assert r.status_code == 202 and r.json()["status"] == "generating"
    assert [(m["role"], m["text"]) for m in r.json()["messages"]] == [("user", "Fix the compile error")]
    assert jobs.calls == [("repair", out["id"])]


def test_delete(client, app, jobs, settings):
    add_config(client)
    app_id, out = create(client, app)
    pdf = settings.cover_letters_dir / f"{out['id']}.pdf"
    pdf.write_bytes(PDF)
    set_fields(app, app_id, pdf_path=pdf.name)
    assert client.delete(url(app_id)).status_code == 204
    assert client.get(url(app_id)).status_code == 404
    assert not pdf.exists()


def test_delete_succeeds_when_pdf_cannot_be_unlinked(client, app, jobs, settings, monkeypatch):
    """On Windows an open (streamed) PDF cannot be deleted: the commit still succeeds, the file stays."""
    add_config(client)
    app_id, out = create(client, app)
    pdf = settings.cover_letters_dir / f"{out['id']}.pdf"
    pdf.write_bytes(PDF)
    set_fields(app, app_id, pdf_path=pdf.name)

    def locked(self, missing_ok=False):
        raise PermissionError(13, "in use", str(self))

    monkeypatch.setattr(Path, "unlink", locked)
    assert client.delete(url(app_id)).status_code == 204
    monkeypatch.undo()
    assert client.get(url(app_id)).status_code == 404
    assert pdf.exists()


# --- pdf / source / attach -------------------------------------------------------------------------


def test_pdf(client, app, jobs, settings):
    add_config(client)
    app_id, out = create(client, app)
    r = client.get(url(app_id, "/pdf"))
    assert r.status_code == 404 and r.json()["code"] == "cover_letter_no_pdf"
    pdf = settings.cover_letters_dir / f"{out['id']}.pdf"
    set_fields(app, app_id, pdf_path=pdf.name)  # set, but the file is missing
    assert client.get(url(app_id, "/pdf")).status_code == 404
    assert client.get(url(app_id)).json()["pdf_available"] is False
    pdf.write_bytes(PDF)
    assert client.get(url(app_id)).json()["pdf_available"] is True
    r = client.get(url(app_id, "/pdf"))
    assert r.status_code == 200 and r.content == PDF
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == 'inline; filename="Cover_letter_Acme.pdf"'
    r = client.get(url(app_id, "/pdf"), params={"lang": "de"})
    assert r.headers["content-disposition"] == 'inline; filename="Anschreiben_Acme.pdf"'



def test_compiler_available_flag(client, app, jobs):
    add_config(client)
    app_id, _ = create(client, app)
    jobs.compiler = FakeCompiler(available=False)
    assert client.get(url(app_id)).json()["compiler_available"] is False


def test_source_and_attach_with_unsafe_company(client, app, jobs, settings):
    add_config(client)
    app_id = make_application(app, company="Müller & Söhne GmbH/Co.")
    r = client.post(url(app_id), json=body(template_id=builtin_id(app)))
    cl_id = r.json()["id"]

    r = client.get(url(app_id, "/source"), params={"lang": "de"})
    assert r.status_code == 200 and r.text == FAKE_CONTENT
    assert r.headers["content-type"].startswith("text/x-tex")
    disposition = r.headers["content-disposition"]
    prefix = "attachment; filename*=utf-8''"
    assert disposition.startswith(prefix)
    name = unquote(disposition[len(prefix):])
    assert disposition == prefix + quote(name)
    assert name.startswith("Anschreiben_Müller") and name.endswith(".tex")
    assert "/" not in name and "&" not in name

    r = client.post(url(app_id, "/attach"), params={"lang": "de"})
    assert r.status_code == 409 and r.json()["code"] == "cover_letter_no_pdf"

    (settings.cover_letters_dir / f"{cl_id}.pdf").write_bytes(PDF)
    set_fields(app, app_id, pdf_path=f"{cl_id}.pdf")
    r = client.post(url(app_id, "/attach"), params={"lang": "de"})
    assert r.status_code == 201
    att = r.json()
    assert att["kind"] == "cover_letter" and att["application_id"] == app_id
    assert "/" not in att["filename"] and "&" not in att["filename"]
    assert att["display_name"].startswith("Anschreiben_Müller") and att["display_name"].endswith(".pdf")
    assert att["display_name"] == name[: -len(".tex")] + ".pdf"
    download = client.get(f"/api/attachments/{att['id']}/download")
    assert download.status_code == 200 and download.content == PDF
    # saving again creates another attachment
    assert client.post(url(app_id, "/attach"), params={"lang": "de"}).status_code == 201
    with app.state.session_factory() as s:
        assert len(s.scalars(select(Attachment)).all()) == 2


def test_attach_text_english_and_empty_company(client, app, jobs):
    add_config(client)
    app_id = make_application(app, company=None)
    client.post(url(app_id), json=body("text"))
    r = client.post(url(app_id, "/attach"), params={"lang": "en"})
    assert r.status_code == 201
    assert r.json()["display_name"] == "Cover_letter.txt" and r.json()["kind"] == AttachmentKind.cover_letter
    assert client.get(f"/api/attachments/{r.json()['id']}/download").text == FAKE_CONTENT

    r = client.get(url(app_id, "/source"), params={"lang": "en"})
    assert r.headers["content-type"].startswith("text/plain")
    assert r.headers["content-disposition"] == 'attachment; filename="Cover_letter.txt"'


def test_attach_english_company(client, app, jobs):
    add_config(client)
    app_id = make_application(app, company="Acme Inc.")
    client.post(url(app_id), json=body("text"))
    r = client.post(url(app_id, "/attach"), params={"lang": "en"})
    assert r.json()["display_name"] == "Cover_letter_Acme_Inc.txt"
    assert client.post(url(app_id, "/attach"), params={"lang": "fr"}).status_code == 422


def test_endpoints_without_draft(client, app, jobs):
    app_id = make_application(app)
    for method, suffix in (("put", "/content"), ("post", "/messages"), ("post", "/repair"), ("get", "/pdf"),
                           ("get", "/source"), ("post", "/attach"), ("delete", "")):
        kwargs = {"json": {"content": "x", "text": "x"}} if method in ("put", "post") else {}
        r = getattr(client, method)(url(app_id, suffix), **kwargs)
        assert r.status_code == 404 and r.json()["code"] == "cover_letter_not_found", (method, suffix)


# --- data dir permissions ----------------------------------------------------------------------------


def test_data_dir_permissions_with_tectonic_user(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(os, "chmod", lambda path, mode: calls.append((path, mode)))
    data_dir = tmp_path / "data"
    create_app(Settings(data_dir=data_dir, update_check=False, tectonic_user="ramen-tex"))
    assert calls == [(data_dir, 0o700)]
    calls.clear()
    create_app(Settings(data_dir=tmp_path / "other", update_check=False))
    assert calls == []

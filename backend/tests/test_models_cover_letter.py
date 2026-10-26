import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.latex.default_template import DEFAULT_TEMPLATE, DEFAULT_TEMPLATE_NAME
from app.models import Application, Posting
from app.models.cover_letter import CoverLetter, CoverLetterMessage, CoverLetterTemplate
from app.models.enums import CoverLetterFormat, CoverLetterLanguage, CoverLetterStatus, MessageRole


def _application(session) -> Application:
    posting = Posting(source="src", external_id="1", title="P")
    session.add(posting)
    session.flush()
    application = Application(posting_id=posting.id)
    session.add(application)
    session.flush()
    return application


def _letter(application_id: int, **kw) -> CoverLetter:
    return CoverLetter(
        application_id=application_id,
        format=CoverLetterFormat.latex,
        language=CoverLetterLanguage.posting,
        content="x",
        **kw,
    )


def test_cover_letter_unique_per_application(session):
    application = _application(session)
    session.add(_letter(application.id))
    session.flush()
    session.add(_letter(application.id))
    with pytest.raises(IntegrityError):
        session.flush()


def test_defaults(session):
    application = _application(session)
    letter = _letter(application.id)
    session.add(letter)
    session.flush()
    assert letter.status == CoverLetterStatus.idle
    assert letter.context == {"profile": True, "document_ids": [], "notes": ""}
    assert letter.error is None and letter.pdf_path is None
    assert letter.created_at is not None and letter.updated_at is not None


def test_cascade_on_application_delete(session):
    application = _application(session)
    letter = _letter(application.id)
    letter.messages.append(CoverLetterMessage(role=MessageRole.user, text="hi"))
    letter.messages.append(CoverLetterMessage(role=MessageRole.assistant, text="ok"))
    session.add(letter)
    session.flush()
    assert [m.text for m in letter.messages] == ["hi", "ok"]
    session.delete(application)
    session.flush()
    assert session.scalars(select(CoverLetter)).all() == []
    assert session.scalars(select(CoverLetterMessage)).all() == []


def test_template_delete_sets_null(session):
    application = _application(session)
    template = CoverLetterTemplate(name="T", content="tex")
    session.add(template)
    session.flush()
    letter = _letter(application.id, template_id=template.id, template_content="tex")
    session.add(letter)
    session.flush()
    session.delete(template)
    session.flush()
    session.refresh(letter)
    assert letter.template_id is None
    assert letter.template_content == "tex"


def test_migration_seeds_builtin_template(app, client):
    with app.state.session_factory() as s:
        templates = s.scalars(select(CoverLetterTemplate)).all()
        assert len(templates) == 1
        assert templates[0].builtin is True
        assert templates[0].name == DEFAULT_TEMPLATE_NAME == "Deedy"
        assert templates[0].content == DEFAULT_TEMPLATE


def test_purposes_include_cover_letter(client):
    assert "cover_letter" in client.get("/api/llm/purposes").json()

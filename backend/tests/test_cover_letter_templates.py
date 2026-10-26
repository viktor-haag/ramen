from sqlalchemy import select

from app.latex.default_template import DEFAULT_TEMPLATE
from app.models import Application, CoverLetter, CoverLetterTemplate, Posting
from app.models.enums import CoverLetterFormat, CoverLetterLanguage

URL = "/api/cover-letter-templates"
VALID = "\\documentclass{article}\n\\begin{document}\nHi\n\\end{document}\n"


def upload(client, name="Mein Brief.tex", data=VALID.encode()):
    return client.post(URL, files={"file": (name, data, "application/x-tex")})


def builtin_id(client):
    return next(t["id"] for t in client.get(URL).json() if t["builtin"])


def test_list_after_migration(client):
    body = client.get(URL).json()
    assert len(body) == 1
    assert body[0]["name"] == "Deedy" and body[0]["builtin"] is True
    assert set(body[0]) == {"id", "name", "builtin", "created_at"}


def test_upload_ok(client):
    r = upload(client)
    assert r.status_code == 201
    assert r.json()["name"] == "Mein Brief" and r.json()["builtin"] is False
    assert len(client.get(URL).json()) == 2


def test_upload_name_uses_basename(client):
    assert upload(client, "C:/dir\\sub/Brief 2.tex").json()["name"] == "Brief 2"


def test_upload_wrong_extension(client):
    r = upload(client, "a.txt")
    assert r.status_code == 422
    assert r.json()["code"] == "template_invalid" and r.json()["params"]["reason"] == "extension"


def test_upload_too_large(client):
    r = upload(client, data=VALID.encode() + b"%" * (200 * 1024))
    assert r.status_code == 413
    assert r.json()["code"] == "template_invalid" and r.json()["params"]["reason"] == "size"


def test_upload_not_utf8(client):
    r = upload(client, data=b"\\documentclass{a}\xff\xfe\\end{document}")
    assert r.status_code == 422
    assert r.json()["code"] == "template_invalid" and r.json()["params"]["reason"] == "encoding"


def test_upload_structure(client):
    for data in (b"\\end{document}", b"\\documentclass{a}", b"hello"):
        r = upload(client, data=data)
        assert r.status_code == 422
        assert r.json()["code"] == "template_invalid" and r.json()["params"]["reason"] == "structure"


def test_rename(client):
    tid = upload(client).json()["id"]
    r = client.patch(f"{URL}/{tid}", json={"name": "  Neu  "})
    assert r.status_code == 200 and r.json()["name"] == "Neu"
    assert client.patch(f"{URL}/{tid}", json={"name": "  "}).status_code == 422
    assert client.patch(f"{URL}/{tid}", json={"name": "x" * 121}).status_code == 422
    assert client.patch(f"{URL}/9999", json={"name": "x"}).json()["code"] == "template_not_found"


def test_builtin_protected(client):
    bid = builtin_id(client)
    r = client.patch(f"{URL}/{bid}", json={"name": "x"})
    assert r.status_code == 409 and r.json()["code"] == "template_builtin"
    r = client.delete(f"{URL}/{bid}")
    assert r.status_code == 409 and r.json()["code"] == "template_builtin"


def test_download_default(client):
    r = client.get(f"{URL}/{builtin_id(client)}/download")
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/x-tex; charset=utf-8"
    assert r.headers["content-disposition"] == 'attachment; filename="Deedy.tex"'
    assert r.text == DEFAULT_TEMPLATE


def test_download_missing(client):
    assert client.get(f"{URL}/9999/download").json()["code"] == "template_not_found"


def test_delete_used_template_keeps_draft(client, app):
    tid = upload(client).json()["id"]
    with app.state.session_factory() as s:
        posting = Posting(source="s", external_id="1", title="Dev", company="Acme")
        application = Application(posting=posting)
        s.add(application)
        s.add(CoverLetter(
            application=application, format=CoverLetterFormat.latex, language=CoverLetterLanguage.en,
            template_id=tid, template_content=VALID, context={}, content="x",
        ))
        s.commit()
    assert client.delete(f"{URL}/{tid}").status_code == 204
    with app.state.session_factory() as s:
        cl = s.scalars(select(CoverLetter)).one()
        assert cl.template_id is None and cl.template_content == VALID
        assert s.get(CoverLetterTemplate, tid) is None

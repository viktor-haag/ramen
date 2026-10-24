from datetime import UTC, datetime

import pytest

from app.models import Attachment, Posting
from app.services import attachments as att_svc
from app.services import triage

NOW = datetime(2026, 10, 22, 8, 0, tzinfo=UTC)


@pytest.fixture
def db(app, client):  # client runs the lifespan (migrations)
    with app.state.session_factory() as s:
        yield s


@pytest.fixture
def app_id(db):
    p = Posting(source="src", external_id="1", first_seen_at=NOW, last_seen_at=NOW, title="T", company="C")
    db.add(p)
    db.commit()
    application = triage.save_posting(db, p.id, NOW)
    db.commit()
    return application.id


def test_appointment_crud(client, app_id):
    r = client.post(
        f"/api/applications/{app_id}/appointments",
        json={"kind": "interview", "starts_at": "2026-11-01T09:30:00", "note": "Zoom"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["kind"] == "interview" and body["note"] == "Zoom"
    assert datetime.fromisoformat(body["starts_at"]) == datetime(2026, 11, 1, 9, 30, tzinfo=UTC)  # naive = UTC
    aid = body["id"]

    client.post(
        f"/api/applications/{app_id}/appointments",
        json={"kind": "deadline", "starts_at": "2026-10-30T12:00:00+02:00"},
    )
    listed = client.get(f"/api/applications/{app_id}/appointments").json()
    assert [a["kind"] for a in listed] == ["deadline", "interview"]  # ordered by starts_at
    assert datetime.fromisoformat(listed[0]["starts_at"]) == datetime(2026, 10, 30, 10, 0, tzinfo=UTC)

    r = client.patch(f"/api/appointments/{aid}", json={"note": "Teams"})
    assert r.status_code == 200 and r.json()["note"] == "Teams" and r.json()["kind"] == "interview"
    assert client.patch(f"/api/appointments/{aid}", json={"starts_at": None}).status_code == 422
    assert client.patch(f"/api/appointments/{aid}", json={"kind": "bogus"}).status_code == 422

    assert client.delete(f"/api/appointments/{aid}").status_code == 204
    assert len(client.get(f"/api/applications/{app_id}/appointments").json()) == 1
    r = client.delete(f"/api/appointments/{aid}")
    assert r.status_code == 404 and r.json()["code"] == "appointment_not_found"
    assert client.patch("/api/appointments/999", json={}).json()["code"] == "appointment_not_found"
    r = client.post("/api/applications/999/appointments", json={"kind": "other", "starts_at": "2026-11-01T09:00:00Z"})
    assert r.status_code == 404 and r.json()["code"] == "application_not_found"
    assert client.get("/api/applications/999/contacts").json()["code"] == "application_not_found"


def test_contact_crud(client, app_id):
    r = client.post(f"/api/applications/{app_id}/contacts", json={"name": "Erika Muster", "role": "HR"})
    assert r.status_code == 201
    cid = r.json()["id"]
    assert r.json()["email"] is None

    r = client.patch(f"/api/contacts/{cid}", json={"email": "e@x.de", "phone": "123"})
    assert r.json()["email"] == "e@x.de" and r.json()["name"] == "Erika Muster"
    assert client.patch(f"/api/contacts/{cid}", json={"role": None}).json()["role"] is None
    assert client.patch(f"/api/contacts/{cid}", json={"name": None}).status_code == 422
    assert client.post(f"/api/applications/{app_id}/contacts", json={}).status_code == 422

    assert [c["id"] for c in client.get(f"/api/applications/{app_id}/contacts").json()] == [cid]
    assert client.delete(f"/api/contacts/{cid}").status_code == 204
    r = client.delete(f"/api/contacts/{cid}")
    assert r.status_code == 404 and r.json()["code"] == "contact_not_found"
    assert client.get(f"/api/applications/{app_id}").json()["contacts"] == []


def test_attachment_upload_download_delete(client, app, db, app_id):
    content = b"%PDF-1.4 hello \x00\xff binary"
    r = client.post(
        f"/api/applications/{app_id}/attachments",
        files={"file": ("Lebenslauf äöü.pdf", content, "application/pdf")},
        data={"kind": "cv"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["kind"] == "cv" and body["display_name"] == "Lebenslauf äöü.pdf"
    att_dir = app.state.settings.attachments_dir
    path = att_dir / body["stored_path"]
    assert path.read_bytes() == content
    assert not body["stored_path"].startswith("/") and body["stored_path"].startswith(f"{app_id}/")

    r = client.get(f"/api/attachments/{body['id']}/download")
    assert r.status_code == 200 and r.content == content
    assert "filename*=utf-8''Lebenslauf%20%C3%A4%C3%B6%C3%BC.pdf" in r.headers["content-disposition"]

    assert client.get(f"/api/applications/{app_id}").json()["attachments"][0]["id"] == body["id"]

    assert client.delete(f"/api/attachments/{body['id']}").status_code == 204
    assert not path.exists()
    assert db.get(Attachment, body["id"]) is None
    for r in (
        client.get(f"/api/attachments/{body['id']}/download"),
        client.delete(f"/api/attachments/{body['id']}"),
    ):
        assert r.status_code == 404 and r.json()["code"] == "attachment_not_found"


def test_attachment_delete_tolerates_missing_file(client, app, app_id):
    r = client.post(f"/api/applications/{app_id}/attachments", files={"file": ("a.txt", b"x")}, data={"kind": "other"})
    (app.state.settings.attachments_dir / r.json()["stored_path"]).unlink()
    assert client.get(f"/api/attachments/{r.json()['id']}/download").status_code == 404
    assert client.delete(f"/api/attachments/{r.json()['id']}").status_code == 204


def test_upload_unknown_application_and_bad_kind(client, app_id):
    r = client.post("/api/applications/999/attachments", files={"file": ("a.txt", b"x")}, data={"kind": "cv"})
    assert r.status_code == 404 and r.json()["code"] == "application_not_found"
    r = client.post(f"/api/applications/{app_id}/attachments", files={"file": ("a.txt", b"x")}, data={"kind": "zzz"})
    assert r.status_code == 422


def test_upload_too_large(client, app, app_id, monkeypatch):
    monkeypatch.setattr(att_svc, "MAX_UPLOAD_BYTES", 1024)
    r = client.post(
        f"/api/applications/{app_id}/attachments", files={"file": ("big.bin", b"a" * 1025)}, data={"kind": "other"}
    )
    assert r.status_code == 413 and r.json()["code"] == "attachment_too_large"
    assert list((app.state.settings.attachments_dir / str(app_id)).glob("*")) == []
    ok = client.post(
        f"/api/applications/{app_id}/attachments", files={"file": ("ok.bin", b"a" * 1024)}, data={"kind": "other"}
    )
    assert ok.status_code == 201


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("..\\..\\evil.pdf", "evil.pdf"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\x\\cv.pdf", "cv.pdf"),
        ("a:b?.pdf", "a_b_.pdf"),
        ("CON.txt", "_CON.txt"),
        ("con", "_con"),
        ("Lpt9.tar.gz", "_Lpt9.tar.gz"),
        ("COM1", "_COM1"),
        ("CONSOLE.txt", "CONSOLE.txt"),
        ("", "datei"),
        ("...", "datei"),
        ("  .hidden. ", "hidden"),
        ("a/", "datei"),
        ("Lebenslauf äöüß ÄÖÜ.pdf", "Lebenslauf äöüß ÄÖÜ.pdf"),
        ("naïve*.pdf", "na_ve_.pdf"),
        ("x\x00y\n.txt", "x_y_.txt"),
    ],
)
def test_safe_filename(raw, expected):
    assert att_svc.safe_filename(raw) == expected


def test_safe_filename_truncates_keeping_extension():
    out = att_svc.safe_filename("a" * 300 + ".pdf")
    assert len(out) == 120 and out.endswith(".pdf")
    out = att_svc.safe_filename("b" * 300)
    assert len(out) == 120
    out = att_svc.safe_filename("c" * 130 + "." + "e" * 200)  # absurd extension: still capped at 120
    assert len(out) == 120


def test_upload_path_stays_inside_dir(client, app, app_id):
    r = client.post(
        f"/api/applications/{app_id}/attachments",
        files={"file": ("../../x.txt", b"data")},
        data={"kind": "other"},
    )
    assert r.status_code == 201
    body = r.json()
    base = (app.state.settings.attachments_dir / str(app_id)).resolve()
    stored = (app.state.settings.attachments_dir / body["stored_path"]).resolve()
    assert stored.is_relative_to(base) and stored.parent == base and stored.read_bytes() == b"data"
    assert body["filename"] == "x.txt" and body["display_name"] == "x.txt"
    assert stored.name.endswith("_x.txt")
    assert not (app.state.settings.data_dir / "x.txt").exists()


def test_resolve_rejects_escaping_stored_path(app):
    with pytest.raises(ValueError):
        att_svc.resolve_path(app.state.settings, "../jobtracker.db")
    with pytest.raises(ValueError):
        att_svc.resolve_path(app.state.settings, "/etc/passwd")

import io
import random
from pathlib import Path

import pytest
from PIL import Image

from app.llm.base import ImagePart, LLMResult
from app.models import DocumentKind, ProfileDocument, UserProfile
from app.services import profile_docs

LONG_TEXT = "Experienced backend engineer with ten years of Python, SQL and distributed systems work."


# --- fixtures generated in code -------------------------------------------------------------

def make_pdf(pages: list[str], with_image: bool = False) -> bytes:
    """Minimal valid PDF: one page per entry (text may be empty), optionally with a full-page image."""
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    add(b"")  # catalog placeholder
    add(b"")  # pages placeholder
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    pixels = bytes(range(48))  # 4x4 RGB
    image = add(
        b"<< /Type /XObject /Subtype /Image /Width 4 /Height 4 /ColorSpace /DeviceRGB /BitsPerComponent 8 "
        b"/Length 48 >>\nstream\n" + pixels + b"\nendstream"
    )
    kids = []
    for text in pages:
        ops = b"q 500 0 0 700 50 50 cm /Im1 Do Q " if with_image else b""
        if text:
            ops += b"BT /F1 10 Tf 60 30 Td (" + text.encode("latin-1") + b") Tj ET"
        content = add(b"<< /Length %d >>\nstream\n" % len(ops) + ops + b"\nendstream")
        res = b"<< /Font << /F1 %d 0 R >> /XObject << /Im1 %d 0 R >> >>" % (font, image)
        kids.append(add(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R /Resources " % content
            + res + b" >>"
        ))
    objs[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[1] = b"<< /Type /Pages /Count %d /Kids [%s] >>" % (
        len(kids), b" ".join(b"%d 0 R" % k for k in kids))
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def text_pdf(pages: int = 2) -> bytes:
    return make_pdf([LONG_TEXT] * pages)


def scan_pdf(pages: int = 2) -> bytes:
    return make_pdf([f"footer {i + 1:03d}" for i in range(pages)], with_image=True)  # 10 chars per page


def png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, format="PNG")
    return buf.getvalue()


def post(client, name, data, description=None, mime="application/octet-stream"):
    return client.post(
        "/api/me/documents", files={"file": (name, data, mime)},
        data={"description": description} if description else {},
    )


# --- local kind detection and text ----------------------------------------------------------

def test_fixture_pdfs_are_real_pdfs():
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(scan_pdf(3)))
    assert len(reader.pages) == 3 and reader.pages[0].extract_text().strip() == "footer 001"
    assert LONG_TEXT in PdfReader(io.BytesIO(text_pdf())).pages[1].extract_text()


def test_text_pdf(client):
    r = post(client, "cv.pdf", text_pdf(), "My CV")
    assert r.status_code == 201
    body = r.json()
    assert body["kind"] == "pdf_text" and body["text_source"] == "extracted" and body["usable"] is True
    assert body["text"].count(LONG_TEXT) == 2 and body["description"] == "My CV"
    assert body["mime"] == "application/pdf" and body["display_name"] == "cv.pdf"


def test_scan_pdf_has_no_local_text(client):
    body = post(client, "scan.pdf", scan_pdf()).json()
    assert body["kind"] == "pdf_scan" and body["text"] is None and body["text_source"] is None
    assert body["usable"] is False


def test_image(client):
    body = post(client, "cert.PNG", png_bytes()).json()
    assert body["kind"] == "image" and body["text"] is None and body["mime"] == "image/png"


def test_utf8_and_cp1252_text(client):
    utf = post(client, "a.txt", "Zürich – Größe".encode()).json()
    assert utf["kind"] == "text" and utf["text"] == "Zürich – Größe" and utf["text_source"] == "extracted"
    cp = post(client, "b.md", "# Bewerbung\nVerkäufer ä".encode("cp1252")).json()
    assert cp["kind"] == "text" and cp["text"] == "# Bewerbung\nVerkäufer ä" and cp["mime"] == "text/markdown"


@pytest.mark.parametrize("name,data", [
    ("cv.docx", b"PK\x03\x04 zip"),
    ("noext", b"hello"),
    ("fake.png", b"%PDF-1.4 not an image"),
    ("fake.pdf", png_bytes()),
    ("bin.txt", b"abc\x00def"),
])
def test_unsupported_documents(client, settings, name, data):
    r = post(client, name, data)
    assert r.status_code == 415 and r.json()["code"] == "unsupported_document_type"
    assert client.get("/api/me/documents").json() == []
    assert list(settings.profile_dir.glob("*")) == []  # nothing left on disk


def test_too_large(client, settings, monkeypatch):
    monkeypatch.setattr("app.services.attachments.MAX_UPLOAD_BYTES", 10)
    r = post(client, "big.txt", b"x" * 11)
    assert r.status_code == 413 and r.json()["code"] == "document_too_large"
    assert r.json()["params"] == {"max_bytes": 10}
    assert list(settings.profile_dir.glob("*")) == []


# --- manual edits, delete, download, flag ----------------------------------------------------

def test_manual_edit_and_clear(client):
    doc = post(client, "a.txt", b"original").json()
    r = client.patch(f"/api/me/documents/{doc['id']}", json={"text": "  fixed text "})
    assert r.json()["text"] == "fixed text" and r.json()["text_source"] == "manual"
    r = client.patch(f"/api/me/documents/{doc['id']}", json={"description": "Notes"})
    assert r.json()["description"] == "Notes" and r.json()["text"] == "fixed text"  # text untouched
    r = client.patch(f"/api/me/documents/{doc['id']}", json={"text": ""}).json()
    assert r["text"] is None and r["text_source"] is None and r["usable"] is False
    assert client.patch("/api/me/documents/999", json={"text": "x"}).json()["code"] == "document_not_found"


def test_delete_removes_file(client, settings):
    doc = post(client, "a.txt", b"hello").json()
    assert len(list(settings.profile_dir.glob("*"))) == 1
    assert client.delete(f"/api/me/documents/{doc['id']}").status_code == 204
    assert list(settings.profile_dir.glob("*")) == []
    assert client.get("/api/me/documents").json() == []
    r = client.delete(f"/api/me/documents/{doc['id']}")
    assert r.status_code == 404 and r.json()["code"] == "document_not_found"


def test_download(client):
    doc = post(client, "a.txt", b"hello").json()
    r = client.get(f"/api/me/documents/{doc['id']}/download")
    assert r.status_code == 200 and r.content == b"hello"
    assert client.get("/api/me/documents/999/download").json()["code"] == "document_not_found"


def flag(app):
    with app.state.session_factory() as s:
        row = s.get(UserProfile, 1)
        return None if row is None else row.inputs_changed_since_generation


def test_changes_mark_inputs_changed(client, app):
    assert flag(app) is None
    doc = post(client, "a.txt", b"hello").json()  # creates the row
    assert flag(app) is True
    for action in (
        lambda: client.patch(f"/api/me/documents/{doc['id']}", json={"description": "d"}),
        lambda: client.delete(f"/api/me/documents/{doc['id']}"),
    ):
        with app.state.session_factory() as s:
            s.get(UserProfile, 1).inputs_changed_since_generation = False
            s.commit()
        action()
        assert flag(app) is True


# --- LLM extraction --------------------------------------------------------------------------

class Recorder:
    calls: list
    reply = LLMResult("Transcribed text", 20, 5, False)


@pytest.fixture
def llm(client, monkeypatch):
    Recorder.calls = []

    class Fake:
        def __init__(self, cfg):
            pass

        def complete(self, system, messages, *, json_schema=None, max_tokens=4096):
            Recorder.calls.append((system, messages))
            return Recorder.reply

    monkeypatch.setattr("app.llm.runner.make_client", lambda cfg, **_: Fake(cfg))
    return Recorder


def add_config(client, **extra):
    body = {"name": "c", "provider": "anthropic", "model": "m", "api_key": "sk-test-1234", **extra}
    assert client.post("/api/llm/configs", json=body).status_code == 200


def images_sent(llm):
    return [p for m in llm.calls[-1][1] for p in m.parts if isinstance(p, ImagePart)]


def test_extract_image(client, app, llm):
    add_config(client)
    doc = post(client, "cert.png", png_bytes()).json()
    with app.state.session_factory() as s:
        s.get(UserProfile, 1).inputs_changed_since_generation = False
        s.commit()
    r = client.post(f"/api/me/documents/{doc['id']}/extract")
    assert r.status_code == 200
    body = r.json()
    assert body["document"]["text"] == "Transcribed text" and body["document"]["text_source"] == "llm"
    assert body["document"]["usable"] is True and body["limit_exceeded"] is False
    system, _ = llm.calls[-1]
    assert "Transcribe all text faithfully" in system
    [image] = images_sent(llm)
    assert image.mime == "image/png" and image.data == png_bytes()
    assert flag(app) is True
    assert client.get("/api/llm/usage").json()["today"]["input_tokens"] == 20  # recorded as extraction


def test_extract_scan_renders_pages(client, llm):
    add_config(client)
    doc = post(client, "scan.pdf", scan_pdf(2)).json()
    assert client.post(f"/api/me/documents/{doc['id']}/extract").status_code == 200
    images = images_sent(llm)
    assert len(images) == 2 and all(i.mime == "image/png" for i in images)
    width, height = Image.open(io.BytesIO(images[0].data)).size
    assert abs(width - 612 * 150 / 72) <= 1 and abs(height - 792 * 150 / 72) <= 1  # 150 dpi (letter fits 2000 px)


def test_extract_scan_is_capped_at_ten_pages(client, llm):
    add_config(client)
    doc = post(client, "long.pdf", scan_pdf(11)).json()
    assert doc["kind"] == "pdf_scan"
    assert client.post(f"/api/me/documents/{doc['id']}/extract").status_code == 200
    assert len(images_sent(llm)) == 10


def test_extract_needs_image_support(client, llm):
    add_config(client, provider="openai_compatible", base_url="http://localhost:1/v1")
    doc = post(client, "cert.png", png_bytes()).json()
    r = client.post(f"/api/me/documents/{doc['id']}/extract")
    assert r.status_code == 409 and r.json()["code"] == "llm_no_image_support"
    assert llm.calls == []


def test_extract_without_config(client, llm):
    doc = post(client, "cert.png", png_bytes()).json()
    assert client.post(f"/api/me/documents/{doc['id']}/extract").json()["code"] == "llm_not_configured"


@pytest.mark.parametrize("name,data", [("a.txt", b"hello"), ("cv.pdf", text_pdf())])
def test_extract_refused_for_documents_with_text(client, llm, name, data):
    add_config(client)
    doc = post(client, name, data).json()
    r = client.post(f"/api/me/documents/{doc['id']}/extract")
    assert r.status_code == 409 and r.json()["code"] == "document_extraction_not_needed"
    assert llm.calls == []


def test_extract_unknown_document(client, llm):
    add_config(client)
    assert client.post("/api/me/documents/999/extract").json()["code"] == "document_not_found"


def test_extract_blank_answer_is_invalid_and_keeps_text(client, llm):
    add_config(client)
    doc = post(client, "cert.png", png_bytes()).json()
    client.patch(f"/api/me/documents/{doc['id']}", json={"text": "my own text"})
    llm.reply = LLMResult("  \n", 5, 1, False)
    try:
        r = client.post(f"/api/me/documents/{doc['id']}/extract")
    finally:
        llm.reply = LLMResult("Transcribed text", 20, 5, False)
    assert r.status_code == 502 and r.json()["code"] == "llm_invalid_output"
    kept = [d for d in client.get("/api/me/documents").json() if d["id"] == doc["id"]][0]
    assert kept["text"] == "my own text" and kept["text_source"] == "manual"


def test_service_decode_text():
    assert profile_docs.decode_text("ä".encode("cp1252")) == "ä"
    assert profile_docs.decode_text(b"\x81") is None  # undefined in cp1252
    assert profile_docs.decode_text(b"\xef\xbb\xbfhi") == "hi"


# --- fix round 1 -----------------------------------------------------------------------------

def encrypted_pdf() -> bytes:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(text_pdf(1))))
    writer.encrypt("secret")
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.mark.parametrize("data", [b"%PDF-1.4\ngarbage", None])
def test_unreadable_pdf_has_own_code(client, settings, data):
    r = post(client, "x.pdf", encrypted_pdf() if data is None else data)
    assert r.status_code == 422 and r.json()["code"] == "document_unreadable"
    assert client.get("/api/me/documents").json() == [] and list(settings.profile_dir.glob("*")) == []


def test_path_traversal_names_stay_inside_profile_dir(client, settings):
    for name in ("../../x.txt", "..\\x.txt"):
        body = post(client, name, b"hi").json()
        assert body["filename"] == "x.txt" and body["display_name"] == "x.txt"
    stored = list(settings.profile_dir.glob("*"))
    assert len(stored) == 2 and all(p.parent == settings.profile_dir for p in stored)
    assert not (settings.data_dir.parent / "x.txt").exists() and not (settings.data_dir / "x.txt").exists()


def test_download_non_ascii_name(client):
    doc = post(client, "Zeugnis_日本.txt", b"hello").json()
    r = client.get(f"/api/me/documents/{doc['id']}/download")
    assert r.status_code == 200 and "filename*=utf-8''" in r.headers["content-disposition"]


def test_empty_patch_does_not_mark_changed(client, app):
    doc = post(client, "a.txt", b"hello").json()
    with app.state.session_factory() as s:
        s.get(UserProfile, 1).inputs_changed_since_generation = False
        s.commit()
    assert client.patch(f"/api/me/documents/{doc['id']}", json={}).status_code == 200
    assert flag(app) is False


def test_extract_records_extraction_purpose_and_passes_limit_flag(client, app, llm):
    from app.models import LLMUsage

    add_config(client)
    client.put("/api/settings", json={
        "fit_auto": False, "fit_concurrency": 2, "daily_limit_kind": "tokens", "daily_limit_value": 10})
    doc = post(client, "cert.png", png_bytes()).json()
    body = client.post(f"/api/me/documents/{doc['id']}/extract").json()
    assert body["limit_exceeded"] is True  # 25 tokens used, limit 10
    with app.state.session_factory() as s:
        assert [u.purpose for u in s.query(LLMUsage)] == ["extraction"]


def big_png(w, h, mode="RGB", noise=False) -> bytes:
    img = Image.new(mode, (w, h), "white" if mode == "RGB" else (255, 255, 255, 128))
    if noise:
        img = Image.frombytes("RGB", (w, h), random.Random(1).randbytes(w * h * 3))  # incompressible
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_large_photo_is_downscaled_to_jpeg(client, llm):
    add_config(client)
    doc = post(client, "photo.png", big_png(3000, 1500)).json()
    client.post(f"/api/me/documents/{doc['id']}/extract")
    [image] = images_sent(llm)
    pic = Image.open(io.BytesIO(image.data))
    assert image.mime == "image/jpeg" and pic.format == "JPEG" and max(pic.size) == 2000


def test_large_alpha_png_stays_png(client, llm):
    add_config(client)
    doc = post(client, "logo.png", big_png(2500, 100, "RGBA")).json()
    client.post(f"/api/me/documents/{doc['id']}/extract")
    [image] = images_sent(llm)
    assert image.mime == "image/png" and max(Image.open(io.BytesIO(image.data)).size) == 2000


def test_heavy_small_image_is_reencoded(client, llm):
    add_config(client)
    data = big_png(1500, 1500, noise=True)
    assert len(data) > 4 * 1024 * 1024
    doc = post(client, "dense.png", data).json()
    client.post(f"/api/me/documents/{doc['id']}/extract")
    [image] = images_sent(llm)
    assert len(image.data) < len(data) and image.mime == "image/jpeg"


def test_small_image_is_sent_unchanged(client, llm):
    add_config(client)
    doc = post(client, "s.png", png_bytes()).json()
    client.post(f"/api/me/documents/{doc['id']}/extract")
    assert images_sent(llm)[0].data == png_bytes()


def test_scan_longest_edge_capped_at_2000(client, llm):
    add_config(client)
    big = make_pdf(["footer 001"], with_image=True).replace(b"[0 0 612 792]", b"[0 0 1224 1584]")
    doc = post(client, "big.pdf", big).json()
    assert doc["kind"] == "pdf_scan"
    client.post(f"/api/me/documents/{doc['id']}/extract")
    [image] = images_sent(llm)
    assert max(Image.open(io.BytesIO(image.data)).size) <= 2000


def test_render_failure_is_a_coded_error(client, llm, monkeypatch):
    add_config(client)
    doc = post(client, "scan.pdf", scan_pdf(1)).json()

    def boom(path):
        raise RuntimeError("pdfium exploded")

    monkeypatch.setattr(profile_docs.pypdfium2, "PdfDocument", boom)
    r = client.post(f"/api/me/documents/{doc['id']}/extract")
    assert r.status_code == 422 and r.json()["code"] == "document_unreadable" and llm.calls == []


def test_missing_file_during_extraction_is_coded(client, llm, settings):
    add_config(client)
    doc = post(client, "cert.png", png_bytes()).json()
    for p in settings.profile_dir.glob("*"):
        p.unlink()
    r = client.post(f"/api/me/documents/{doc['id']}/extract")
    assert r.status_code == 404 and r.json()["code"] == "document_not_found"


def test_concurrent_rendering(tmp_path):
    import threading

    path = tmp_path / "s.pdf"
    path.write_bytes(scan_pdf(3))
    results, errors = [], []

    def work():
        try:
            results.append(len(profile_docs.render_pdf_pages(path)))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == [] and results == [3, 3]


def exif_jpeg(size=(40, 20), orientation=6) -> bytes:
    img = Image.new("RGB", size, "red")
    exif = Image.Exif()
    exif[0x0112] = orientation
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def test_small_exif_rotated_image_is_reencoded_transposed(client, llm):
    add_config(client)
    doc = post(client, "phone.jpg", exif_jpeg((40, 20), 6)).json()
    client.post(f"/api/me/documents/{doc['id']}/extract")
    [image] = images_sent(llm)
    assert Image.open(io.BytesIO(image.data)).size == (20, 40)  # 90 degree rotation applied


def test_large_exif_rotated_image_is_transposed_before_downscaling(client, llm):
    add_config(client)
    doc = post(client, "big.jpg", exif_jpeg((3000, 1000), 6)).json()
    client.post(f"/api/me/documents/{doc['id']}/extract")
    [image] = images_sent(llm)
    assert Image.open(io.BytesIO(image.data)).size == (667, 2000)


def test_upright_image_is_still_sent_unchanged(client, llm):
    add_config(client)
    data = exif_jpeg((40, 20), 1)
    doc = post(client, "up.jpg", data).json()
    client.post(f"/api/me/documents/{doc['id']}/extract")
    assert images_sent(llm)[0].data == data


def test_pixel_cap_is_set_and_bombs_are_unreadable(client, llm, monkeypatch):
    assert Image.MAX_IMAGE_PIXELS == 50_000_000
    add_config(client)
    doc = post(client, "bomb.png", big_png(200, 200)).json()
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    r = client.post(f"/api/me/documents/{doc['id']}/extract")
    assert r.status_code == 422 and r.json()["code"] == "document_unreadable" and llm.calls == []

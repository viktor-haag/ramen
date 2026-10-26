"""Server-sent events for streaming cover letter drafts (`GET .../cover-letter/stream`, spec section 5)."""
import json
import logging
import threading

import pytest
from sqlalchemy import select

from app.api import cover_letters as api
from app.cover_letters.jobs import StreamSnapshot
from app.models import Application, CoverLetter, Posting
from app.models.enums import CoverLetterFormat, CoverLetterStatus
from test_cover_letters_api import FakeCompiler

END = ("end", {})


class StreamJobs:
    """Fake jobs object: `stream_snapshot` delegates to a replaceable `script(call_no, cl_id, created_at)`."""

    def __init__(self):
        self.compiler = FakeCompiler()
        self.script = lambda n, cl_id, created_at: None
        self.created_ats: list = []
        self._lock = threading.Lock()
        self._calls = 0

    def stream_snapshot(self, cl_id, created_at):
        with self._lock:
            self._calls += 1
            n = self._calls
        self.created_ats.append(created_at)
        return self.script(n, cl_id, created_at)

    def wait_idle(self, timeout):
        return True

    def recover(self, session):
        return 0

    def shutdown(self):
        pass


@pytest.fixture
def jobs(client, app, monkeypatch):
    monkeypatch.setattr(api, "POLL_SECONDS", 0.005)
    monkeypatch.setattr(api, "PING_SECONDS", 60.0)
    original = app.state.cover_letter_jobs
    fake = StreamJobs()
    app.state.cover_letter_jobs = fake
    yield fake
    app.state.cover_letter_jobs = original


def make_draft(app, status=CoverLetterStatus.generating):
    with app.state.session_factory() as s:
        application = Application(posting=Posting(source="s", external_id="x", title="Dev", company="Acme"))
        cl = CoverLetter(
            application=application, format=CoverLetterFormat.text, language="de", content="", status=status
        )
        s.add(cl)
        s.commit()
        return application.id, cl.id, cl.created_at


def set_status(app, cl_id, status):
    with app.state.session_factory() as s:
        s.get(CoverLetter, cl_id).status = status
        s.commit()


def stream_url(app_id):
    return f"/api/applications/{app_id}/cover-letter/stream"


def parse(lines):
    """Yield `(event, data)` per SSE event and `("ping", None)` per comment line."""
    event = data = None
    for line in lines:
        if line.startswith(":"):
            yield ("ping", None)
        elif line.startswith("event: "):
            event = line[len("event: "):]
        elif line.startswith("data: "):
            data = json.loads(line[len("data: "):])
        elif line == "" and event is not None:
            yield (event, data)
            event = data = None


def collect(client, app_id):
    with client.stream("GET", stream_url(app_id)) as r:
        assert r.status_code == 200
        return list(parse(r.iter_lines()))


def test_no_draft_is_404(client, app, jobs):
    with app.state.session_factory() as s:
        application = Application(posting=Posting(source="s", external_id="y", title="Dev", company="Acme"))
        s.add(application)
        s.commit()
        app_id = application.id
    r = client.get(stream_url(app_id))
    assert r.status_code == 404
    assert r.json()["code"] == "cover_letter_not_found"


def test_idle_draft_ends_immediately(client, app, jobs):
    app_id, _, _ = make_draft(app, CoverLetterStatus.idle)
    assert collect(client, app_id) == [END]


def test_headers(client, app, jobs):
    app_id, _, _ = make_draft(app, CoverLetterStatus.idle)
    with client.stream("GET", stream_url(app_id)) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["cache-control"] == "no-cache"
        assert r.headers["x-accel-buffering"] == "no"
        r.read()


def test_snapshots_then_end_when_no_longer_generating(client, app, jobs):
    app_id, cl_id, created_at = make_draft(app)

    def script(n, _cl_id, _created_at):
        if n <= 2:
            return StreamSnapshot("generate", "Sehr geehrte", 1)
        if n == 3:
            return StreamSnapshot("generate", "Sehr geehrte Damen und Herren, äöü", 2)
        if n == 4:
            set_status(app, cl_id, CoverLetterStatus.compiling)
            return StreamSnapshot("generate", "Sehr geehrte Damen und Herren, äöü", 2)
        return StreamSnapshot("generate", "never sent", 3)  # buffer may outlive `generating`

    jobs.script = script
    events = collect(client, app_id)
    assert events == [
        ("text", {"phase": "generate", "text": "Sehr geehrte", "seq": 1}),
        ("text", {"phase": "generate", "text": "Sehr geehrte Damen und Herren, äöü", "seq": 2}),
        END,
    ]
    assert jobs.created_ats and all(c == created_at and c.tzinfo is not None for c in jobs.created_ats)


def test_draft_deleted_mid_stream_ends(client, app, jobs):
    app_id, cl_id, _ = make_draft(app)

    def script(n, _cl_id, _created_at):
        if n == 2:
            with app.state.session_factory() as s:
                s.delete(s.get(CoverLetter, cl_id))
                s.commit()
        return StreamSnapshot("generate", "Hallo", 1)

    jobs.script = script
    assert collect(client, app_id) == [("text", {"phase": "generate", "text": "Hallo", "seq": 1}), END]


def test_ping_while_waiting(client, app, jobs, monkeypatch):
    monkeypatch.setattr(api, "PING_SECONDS", 0.0)
    app_id, cl_id, _ = make_draft(app)

    def script(n, _cl_id, _created_at):
        if n == 3:
            set_status(app, cl_id, CoverLetterStatus.idle)
        return None

    jobs.script = script
    events = collect(client, app_id)
    assert events[-1] == END
    assert ("ping", None) in events
    assert all(e[0] in ("ping", "end") for e in events)


def test_two_parallel_connections_both_get_snapshots(client, app, jobs):
    app_id, cl_id, _ = make_draft(app)
    jobs.script = lambda n, _c, _t: StreamSnapshot("revise", "Parallel", 7)
    got_text = [threading.Event(), threading.Event()]
    results: list = [None, None]

    def reader(i):
        events = []
        with client.stream("GET", stream_url(app_id)) as r:
            for ev in parse(r.iter_lines()):
                events.append(ev)
                if ev[0] == "text":
                    got_text[i].set()
                if ev[0] == "end":
                    break
        results[i] = events

    threads = [threading.Thread(target=reader, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    assert all(e.wait(5) for e in got_text)
    set_status(app, cl_id, CoverLetterStatus.idle)
    for t in threads:
        t.join(5)
        assert not t.is_alive()
    expected = [("text", {"phase": "revise", "text": "Parallel", "seq": 7}), END]
    assert results == [expected, expected]


def test_client_disconnect_logs_no_error(client, app, jobs, caplog):
    app_id, cl_id, _ = make_draft(app)
    jobs.script = lambda n, _c, _t: StreamSnapshot("generate", "Hallo", n)
    with caplog.at_level(logging.WARNING):
        with client.stream("GET", stream_url(app_id)) as r:
            for ev in parse(r.iter_lines()):
                assert ev[0] == "text"
                break
        # the server-side generator is gone: the draft stays `generating`, and nothing failed
        with app.state.session_factory() as s:
            assert s.scalar(select(CoverLetter.status).where(CoverLetter.id == cl_id)) == CoverLetterStatus.generating
    assert not [rec for rec in caplog.records if rec.levelno >= logging.ERROR]

import threading
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.models import (
    Appointment,
    Application,
    AppointmentKind,
    AppSetting,
    Attachment,
    Contact,
    DocumentKind,
    LLMConfig,
    LLMProvider,
    LLMPurpose,
    LLMPurposeKind,
    LLMUsage,
    PluginSetting,
    Posting,
    PostingFit,
    PostingMatch,
    RunStatus,
    RunTrigger,
    SearchProfile,
    ProfileDocument,
    SearchRun,
    StatusChange,
    TriageStatus,
    UserProfile,
    FitStatus,
    FitRating,
)
from app.models import AppStatus

NOW = datetime(2026, 10, 23, 8, 0, tzinfo=UTC)


@pytest.fixture
def db(app, client):  # client runs the lifespan (migrations)
    with app.state.session_factory() as s:
        yield s


def posting(ext, status=TriageStatus.new):
    return Posting(source="src", external_id=ext, title=f"T{ext}", triage_status=status,
                   first_seen_at=NOW, last_seen_at=NOW)


def seed(db):
    """3 postings (new, dismissed, saved with application + children), 2 runs, profile, setting."""
    profile = SearchProfile(name="P", keywords=["a"], plugins=["fake"])
    kept, new, dismissed = posting("kept"), posting("new"), posting("dis", TriageStatus.dismissed)
    db.add_all([profile, kept, new, dismissed])
    db.flush()
    app_ = Application(posting_id=kept.id, status=AppStatus.saved)
    db.add(app_)
    db.flush()
    db.add_all([
        PostingMatch(posting_id=p.id, profile_id=profile.id) for p in (kept, new, dismissed)
    ])
    db.add_all([
        PostingFit(posting_id=kept.id, status=FitStatus.done, rating=FitRating.good, profile_version=1),
        PostingFit(posting_id=new.id, status=FitStatus.queued),
    ])
    db.add_all([
        Contact(application_id=app_.id, name="C"),
        StatusChange(application_id=app_.id, from_status=None, to_status=AppStatus.saved),
        Appointment(application_id=app_.id, kind=AppointmentKind.other, starts_at=NOW),
        Attachment(application_id=app_.id, filename="f", display_name="f", stored_path="x/f"),
        SearchRun(profile_id=profile.id, plugin="fake", trigger=RunTrigger.manual, status=RunStatus.ok),
        SearchRun(profile_id=profile.id, plugin="fake", trigger=RunTrigger.manual, status=RunStatus.error),
        PluginSetting(plugin="fake", enabled=True, settings={}),
    ])
    llm = LLMConfig(name="L", provider=LLMProvider.openai, model="m", api_key="sk-test-1234")
    db.add(llm)
    db.flush()
    db.add_all([
        LLMPurpose(purpose=LLMPurposeKind.fit, config_id=llm.id),
        LLMUsage(config_id=llm.id, purpose="fit", input_tokens=1, output_tokens=2),
        AppSetting(key="fit_auto", value=True),
        ProfileDocument(filename="cv.txt", display_name="CV", stored_path="cv.txt",
                        mime="text/plain", kind=DocumentKind.text),
        UserProfile(id=1, free_text="x"),
    ])
    db.commit()
    return kept


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_clear_feed_keeps_applications(client, db):
    kept = seed(db)
    r = client.post("/api/admin/clear-feed")
    assert r.status_code == 200
    assert r.json() == {"deleted_postings": 2, "deleted_runs": 2}
    db.expire_all()
    assert [p.id for p in db.scalars(select(Posting))] == [kept.id]
    assert count(db, Application) == 1
    assert count(db, Contact) == 1
    assert count(db, SearchProfile) == 1
    assert count(db, PluginSetting) == 1
    assert count(db, SearchRun) == 0
    assert [m.posting_id for m in db.scalars(select(PostingMatch))] == [kept.id]


def test_reset_clears_everything(client, app, db):
    seed(db)
    att_dir = app.state.settings.attachments_dir
    (att_dir / "sub").mkdir(parents=True, exist_ok=True)
    (att_dir / "sub" / "f.pdf").write_bytes(b"x")
    (att_dir / "top.txt").write_bytes(b"x")
    prof_dir = app.state.settings.profile_dir
    prof_dir.mkdir(parents=True, exist_ok=True)
    (prof_dir / "cv.txt").write_bytes(b"x")
    (prof_dir / "sub").mkdir()
    (prof_dir / "sub" / "scan.png").write_bytes(b"x")
    # a scheduled profile, so that the scheduler has a job to drop
    db.add(SearchProfile(name="S", keywords=["b"], plugins=["fake"], schedule_hours=4))
    db.commit()
    app.state.scheduler.sync()
    assert app.state.scheduler.jobs()

    r = client.post("/api/admin/reset")
    assert r.status_code == 200
    assert r.json() == {"deleted": {
        "posting_fit": 2, "posting_match": 3, "status_change": 1, "appointment": 1, "contact": 1, "attachment": 1,
        "application": 1, "job_posting": 3, "search_run": 2, "search_profile": 2, "plugin_setting": 1,
        "llm_usage": 1, "llm_purpose": 1, "llm_config": 1, "app_setting": 1, "profile_document": 1,
        "user_profile": 1, "cover_letter_message": 0, "cover_letter": 0, "cover_letter_template": 0,
    }}
    db.expire_all()
    for model in (Posting, PostingFit, PostingMatch, SearchProfile, SearchRun, Application, StatusChange,
                  Appointment, Contact, Attachment, PluginSetting, LLMConfig, LLMPurpose, LLMUsage,
                  AppSetting, ProfileDocument, UserProfile):
        assert count(db, model) == 0, model
    assert att_dir.is_dir()
    assert list(att_dir.iterdir()) == []
    assert prof_dir.is_dir()
    assert list(prof_dir.iterdir()) == []
    assert app.state.scheduler.jobs() == {}


@pytest.mark.parametrize("path", ["/api/admin/clear-feed", "/api/admin/reset", "/api/admin/delete-profile"])
def test_admin_conflict_when_running(client, db, path):
    seed(db)
    db.add(SearchRun(plugin="fake", trigger=RunTrigger.manual, status=RunStatus.running))
    db.commit()
    r = client.post(path)
    assert r.status_code == 409
    assert r.json()["code"] == "runs_active"
    db.expire_all()
    assert count(db, Posting) == 3
    assert count(db, SearchRun) == 3
    assert count(db, SearchProfile) == 1


def test_admin_holds_run_lock(client, app):
    lock = app.state.run_service.db_lock
    result: dict = {}

    def call():
        result["r"] = client.post("/api/admin/clear-feed")

    lock.acquire()
    t = threading.Thread(target=call)
    try:
        t.start()
        t.join(0.3)
        assert t.is_alive()  # blocked on the run lock
    finally:
        lock.release()
    t.join(5)
    assert not t.is_alive()
    assert result["r"].status_code == 200


def test_reset_order_covers_every_table():
    from app.db import Base
    from app.services.admin import _RESET_ORDER

    assert {model.__tablename__ for _, model in _RESET_ORDER} == set(Base.metadata.tables)


def test_reset_survives_attachment_cleanup_failure(client, app, db, monkeypatch):
    from pathlib import Path

    seed(db)
    att_dir = app.state.settings.attachments_dir
    (att_dir / "sub").mkdir(parents=True, exist_ok=True)
    (att_dir / "sub" / "f.pdf").write_bytes(b"x")
    (att_dir / "top.txt").write_bytes(b"x")
    db.add(SearchProfile(name="S", keywords=["b"], plugins=["fake"], schedule_hours=4))
    db.commit()
    app.state.scheduler.sync()
    assert app.state.scheduler.jobs()

    def locked(self, missing_ok=False):
        raise PermissionError("file in use")

    monkeypatch.setattr(Path, "unlink", locked)
    monkeypatch.setattr("app.services.admin.shutil.rmtree", lambda *a, **k: (_ for _ in ()).throw(PermissionError("dir in use")))
    r = client.post("/api/admin/reset")
    assert r.status_code == 200
    assert app.state.scheduler.jobs() == {}
    db.expire_all()
    for model in (Posting, SearchProfile, Application, PluginSetting):
        assert count(db, model) == 0, model


def test_delete_profile_removes_documents_files_and_profile(client, app, db):
    seed(db)
    prof_dir = app.state.settings.profile_dir
    prof_dir.mkdir(parents=True, exist_ok=True)
    (prof_dir / "cv.txt").write_bytes(b"x")
    (prof_dir / "missing-row.txt").write_bytes(b"x")  # not referenced by any row: left alone
    db.add(ProfileDocument(filename="b.txt", display_name="B", stored_path="gone.txt",
                           mime="text/plain", kind=DocumentKind.text))  # file already missing
    db.commit()

    r = client.post("/api/admin/delete-profile")
    assert r.status_code == 200
    assert r.json() == {"deleted_documents": 2, "deleted_fits": 2}
    db.expire_all()
    assert count(db, ProfileDocument) == 0
    assert count(db, UserProfile) == 0
    assert count(db, PostingFit) == 0  # fits of the deleted profile go too, postings stay
    assert not (prof_dir / "cv.txt").exists()
    assert (prof_dir / "missing-row.txt").exists()
    # everything else stays
    assert count(db, LLMConfig) == 1
    assert count(db, LLMPurpose) == 1
    assert count(db, LLMUsage) == 1
    assert count(db, AppSetting) == 1
    assert count(db, Posting) == 3
    assert count(db, Application) == 1


def test_clear_feed_cascades_fits_of_deleted_postings(client, db):
    kept = seed(db)
    assert client.post("/api/admin/clear-feed").status_code == 200
    db.expire_all()
    assert [f.posting_id for f in db.scalars(select(PostingFit))] == [kept.id]


def test_delete_profile_without_profile_is_a_noop(client, db):
    r = client.post("/api/admin/delete-profile")
    assert r.status_code == 200
    assert r.json() == {"deleted_documents": 0, "deleted_fits": 0}


def test_delete_profile_survives_file_removal_failure(client, app, db, monkeypatch, caplog):
    from pathlib import Path

    seed(db)
    prof_dir = app.state.settings.profile_dir
    prof_dir.mkdir(parents=True, exist_ok=True)
    (prof_dir / "cv.txt").write_bytes(b"x")

    def locked(self, missing_ok=False):
        raise PermissionError("file in use")

    monkeypatch.setattr(Path, "unlink", locked)
    with caplog.at_level("WARNING", logger="app.services.admin"):
        r = client.post("/api/admin/delete-profile")
    assert r.status_code == 200
    assert r.json() == {"deleted_documents": 1, "deleted_fits": 2}
    db.expire_all()
    assert count(db, ProfileDocument) == 0
    assert count(db, UserProfile) == 0
    assert "Could not remove profile document file cv.txt" in caplog.text


def test_delete_profile_with_escaping_stored_path_leaves_outside_file(client, app, db):
    seed(db)
    outside = app.state.settings.profile_dir.parent / "outside.txt"
    outside.write_bytes(b"keep")
    db.add(ProfileDocument(filename="o.txt", display_name="O", stored_path="../outside.txt",
                           mime="text/plain", kind=DocumentKind.text))
    db.commit()
    r = client.post("/api/admin/delete-profile")
    assert r.status_code == 200 and r.json() == {"deleted_documents": 2, "deleted_fits": 2}  # seed() adds one document
    assert outside.read_bytes() == b"keep"
    db.expire_all()
    assert count(db, ProfileDocument) == 0

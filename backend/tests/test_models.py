from datetime import UTC, datetime

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import Base, make_engine
from app.db_migrate import upgrade
from app.models import (
    Appointment,
    Application,
    Attachment,
    Contact,
    Posting,
    SearchProfile,
    SearchRun,
    StatusChange,
)


def test_unique_source_external_id(session):
    session.add(Posting(source="x", external_id="1"))
    session.flush()
    session.add(Posting(source="x", external_id="1"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_datetime_roundtrip_is_utc_aware(session):
    ts = datetime(2026, 1, 1, 12, tzinfo=UTC)
    session.add(Posting(source="x", external_id="1", first_seen_at=ts))
    session.commit()
    session.expire_all()
    loaded = session.scalars(select(Posting)).one()
    assert loaded.first_seen_at.tzinfo == UTC
    assert loaded.first_seen_at == ts


def test_application_cascade(session):
    posting = Posting(source="x", external_id="1")
    app_ = Application(posting=posting, contacts=[Contact(name="Ann")])
    session.add(app_)
    session.commit()
    session.delete(app_)
    session.commit()
    assert session.scalars(select(Contact)).all() == []


def test_posting_delete_cascades_in_db(session):
    posting = Posting(source="x", external_id="1")
    session.add(
        Application(
            posting=posting,
            contacts=[Contact(name="Ann")],
            status_changes=[StatusChange(to_status="saved")],
            appointments=[Appointment(starts_at=datetime(2026, 1, 1, tzinfo=UTC))],
            attachments=[Attachment(filename="a", display_name="a", stored_path="p")],
        )
    )
    session.commit()
    session.delete(posting)
    session.commit()
    session.expire_all()
    for model in (Application, Contact, StatusChange, Appointment, Attachment):
        assert session.scalars(select(model)).all() == [], model


def test_profile_delete_nulls_search_run_profile_id(session):
    profile = SearchProfile(name="p")
    session.add(profile)
    session.flush()
    session.add(SearchRun(profile_id=profile.id, plugin="good", trigger="manual"))
    session.commit()
    session.delete(profile)
    session.commit()
    session.expire_all()
    run = session.scalars(select(SearchRun)).one()
    assert run.profile_id is None


def test_migration_matches_models(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    upgrade(url)
    engine = make_engine(url)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(
            conn, opts={"compare_type": True, "render_as_batch": True}
        )
        assert compare_metadata(ctx, Base.metadata) == []
    engine.dispose()

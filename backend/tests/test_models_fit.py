from datetime import UTC, datetime

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select

from app.db import Base, make_engine
from app.db_migrate import BACKEND_DIR, upgrade
from app.models import FitRating, FitStatus, Posting, PostingFit

NOW = datetime(2026, 10, 24, 8, 0, tzinfo=UTC)


def make_posting(ext="1"):
    return Posting(source="src", external_id=ext, title="T", first_seen_at=NOW, last_seen_at=NOW)


def test_posting_fit_roundtrip(session):
    p = make_posting()
    session.add(p)
    session.flush()
    session.add(PostingFit(posting_id=p.id, status=FitStatus.done, rating=FitRating.good,
                           explanation="Fits.", profile_version=3, evaluated_at=NOW))
    session.commit()
    session.expire_all()
    fit = session.get(PostingFit, p.id)
    assert fit.status == FitStatus.done and fit.rating == FitRating.good
    assert fit.explanation == "Fits." and fit.profile_version == 3
    assert fit.error is None and fit.evaluated_at == NOW
    session.delete(session.get(Posting, p.id))
    session.commit()
    assert session.scalars(select(PostingFit)).all() == []  # FK cascade


def test_posting_fit_nullable_columns(session):
    p = make_posting()
    session.add(p)
    session.flush()
    session.add(PostingFit(posting_id=p.id, status=FitStatus.queued))
    session.commit()
    session.expire_all()
    fit = session.get(PostingFit, p.id)
    assert fit.rating is None and fit.explanation is None and fit.profile_version is None
    assert fit.evaluated_at is None


def test_migration_0004_matches_models_and_roundtrips(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    upgrade(url)
    engine = make_engine(url)
    assert "posting_fit" in inspect(engine).get_table_names()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True, "render_as_batch": True})
        assert compare_metadata(ctx, Base.metadata) == []
    engine.dispose()

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.downgrade(cfg, "0003")
    engine = make_engine(url)
    assert "posting_fit" not in inspect(engine).get_table_names()
    engine.dispose()
    upgrade(url)
    engine = make_engine(url)
    assert "posting_fit" in inspect(engine).get_table_names()
    engine.dispose()

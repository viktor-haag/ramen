import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.db import Base, make_engine
from app.db_migrate import upgrade
from app.models import (
    AppSetting,
    DocumentKind,
    LLMConfig,
    LLMProvider,
    LLMPurpose,
    LLMPurposeKind,
    LLMUsage,
    ProfileDocument,
    TextSource,
    ThinkingLevel,
    UserProfile,
)


def make_config(name="main", **kw):
    return LLMConfig(name=name, provider=LLMProvider.anthropic, model="m", **kw)


def test_llm_config_defaults(session):
    session.add(make_config(api_key="sk-test-1234"))
    session.commit()
    session.expire_all()
    cfg = session.scalars(select(LLMConfig)).one()
    assert cfg.thinking == ThinkingLevel.off
    assert cfg.extra_body == {}
    assert cfg.extra_headers == {}
    assert cfg.is_default is False
    assert cfg.price_in is None and cfg.price_out is None
    assert cfg.provider == LLMProvider.anthropic


def test_name_unique(session):
    session.add(make_config("dup"))
    session.flush()
    session.add(make_config("dup"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_purpose_set_null_on_config_delete(session):
    cfg = make_config()
    session.add(cfg)
    session.flush()
    session.add(LLMPurpose(purpose=LLMPurposeKind.fit, config_id=cfg.id))
    session.add(LLMUsage(config_id=cfg.id, purpose="fit", input_tokens=1, output_tokens=2))
    session.commit()
    session.delete(cfg)
    session.commit()
    session.expire_all()
    assert session.get(LLMPurpose, LLMPurposeKind.fit).config_id is None
    assert session.scalars(select(LLMUsage)).one().config_id is None


def test_app_setting_json_roundtrip(session):
    session.add(AppSetting(key="fit_concurrency", value=2))
    session.add(AppSetting(key="fit_auto", value=False))
    session.commit()
    session.expire_all()
    assert session.get(AppSetting, "fit_concurrency").value == 2
    assert session.get(AppSetting, "fit_auto").value is False


def test_profile_document_and_user_profile_defaults(session):
    session.add(ProfileDocument(filename="cv.pdf", display_name="CV", stored_path="p/cv.pdf",
                                mime="application/pdf", kind=DocumentKind.pdf_scan))
    session.add(UserProfile(id=1))
    session.commit()
    session.expire_all()
    doc = session.scalars(select(ProfileDocument)).one()
    assert doc.text is None and doc.text_source is None
    assert doc.kind == DocumentKind.pdf_scan
    doc.text_source = TextSource.llm
    session.commit()
    profile = session.get(UserProfile, 1)
    assert profile.version == 0
    assert profile.edited_since_generation is False
    assert profile.inputs_changed_since_generation is False
    assert profile.generated_at is None


def test_migration_0003_matches_models(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    upgrade(url)
    engine = make_engine(url)
    assert {"llm_config", "llm_purpose", "app_setting", "llm_usage", "profile_document",
            "user_profile"} <= set(inspect(engine).get_table_names())
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True, "render_as_batch": True})
        assert compare_metadata(ctx, Base.metadata) == []
    engine.dispose()

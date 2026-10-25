from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

import app.models  # noqa: F401  (register all tables)
from app.config import Settings
from app.db import Base, make_engine
from app.main import create_app

FAKE_PLUGINS = Path(__file__).parent / "fake_plugins"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path, plugin_dirs=[FAKE_PLUGINS], update_check=False)


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def session():
    engine = make_engine("sqlite://", poolclass=StaticPool)  # FK pragma on, like production
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    engine.dispose()

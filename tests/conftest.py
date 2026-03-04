from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from tax_assistant.config import Settings
from tax_assistant.db import build_engine, init_db
from tax_assistant.main import create_app


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    db_path = tmp_path / "tax_assistant_test.db"
    storage_path = tmp_path / "uploads"
    return Settings(database_url=f"sqlite:///{db_path}", storage_dir=str(storage_path))


@pytest.fixture
def engine(test_settings: Settings):
    engine = build_engine(test_settings)
    init_db(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as db_session:
        yield db_session


@pytest.fixture
def client(test_settings: Settings):
    app = create_app(test_settings)
    with TestClient(app) as test_client:
        yield test_client

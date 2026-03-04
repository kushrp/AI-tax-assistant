from __future__ import annotations

from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from tax_assistant.config import Settings


def build_engine(settings: Settings):
    settings.ensure_paths()
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    return create_engine(settings.database_url, connect_args=connect_args)


def init_db(engine) -> None:
    SQLModel.metadata.create_all(engine)


def session_scope(engine) -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session

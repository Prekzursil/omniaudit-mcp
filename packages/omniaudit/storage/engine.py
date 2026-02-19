from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from omniaudit.core.settings import settings
from omniaudit.models.db import Base


def create_db_engine(url: str | None = None):
    return create_engine(url or settings.database_url, future=True)


def create_session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)


def initialize_database(engine) -> None:
    Base.metadata.create_all(engine)

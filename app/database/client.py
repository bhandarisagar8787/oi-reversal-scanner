"""
Database Client

Provides the application's shared SQLAlchemy Engine and
Session factory.

This module is the only place responsible for creating
database connections.
"""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """
    Returns the singleton SQLAlchemy Engine.
    """

    global _engine

    if _engine is None:
        _engine = create_engine(
            settings.DATABASE_URL,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            pool_recycle=1800,
            future=True,
            echo=False,
        )

    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """
    Returns the singleton SQLAlchemy Session factory.
    """

    global _session_factory

    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            expire_on_commit=False,
            future=True,
        )

    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """
    Transactional session context.

    Commits on success.
    Rolls back on failure.
    Always closes the session.
    """

    session = get_session_factory()()

    try:
        yield session
        session.commit()

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()
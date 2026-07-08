"""
Database Engine

Creates a single SQLAlchemy Engine that is shared by
the entire application.

No module should create its own connection.
"""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.config import settings


_engine: Engine | None = None


def get_engine() -> Engine:
    """
    Returns the singleton SQLAlchemy engine.
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
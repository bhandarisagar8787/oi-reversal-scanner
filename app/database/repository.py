"""
Repository Layer

Centralized database access for the OI Reversal Scanner.

Business logic MUST NOT access SQLAlchemy directly.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.database.client import session_scope

logger = logging.getLogger(__name__)


class Repository:
    """
    Production repository.

    All database operations are centralized here.
    """

    def __init__(self) -> None:
        logger.info("Repository initialized")

    def health(self) -> bool:
        """
        Verify database connectivity.
        """

        try:
            with session_scope() as session:
                session.execute(text("SELECT 1"))
            return True

        except Exception:
            logger.exception("Database health check failed")
            return False
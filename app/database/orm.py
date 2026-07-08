"""
SQLAlchemy ORM Models

Persistence models mapped to PostgreSQL tables.

These models are ONLY used by the Repository layer.

Business logic should use the dataclasses defined in
models.py instead.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Double,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
)

from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""


# ---------------------------------------------------------
# Bars
# ---------------------------------------------------------


class BarORM(Base):
    __tablename__ = "bars"

    __table_args__ = (
        PrimaryKeyConstraint("symbol", "ts_utc"),
    )

    symbol: Mapped[str] = mapped_column(String)
    ts_utc: Mapped[int] = mapped_column(BigInteger)

    open: Mapped[float] = mapped_column(Double)
    high: Mapped[float] = mapped_column(Double)
    low: Mapped[float] = mapped_column(Double)
    close: Mapped[float] = mapped_column(Double)

    volume: Mapped[float] = mapped_column(Double)
    open_interest: Mapped[float] = mapped_column(Double)


# ---------------------------------------------------------
# Zones
# ---------------------------------------------------------


class ZoneORM(Base):
    __tablename__ = "zones"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    symbol: Mapped[str] = mapped_column(String)

    zone_type: Mapped[str] = mapped_column(String)

    extreme_ts_utc: Mapped[int] = mapped_column(BigInteger)

    confirm_ts_utc: Mapped[int] = mapped_column(BigInteger)

    zone_top: Mapped[float] = mapped_column(Double)

    zone_bottom: Mapped[float] = mapped_column(Double)

    oi_extreme: Mapped[float] = mapped_column(Double)

    oi_confirm: Mapped[float] = mapped_column(Double)

    oi_change_pct: Mapped[float | None] = mapped_column(Double)

    passed_oi_filter: Mapped[bool] = mapped_column(Boolean)

    detected_at_utc: Mapped[int] = mapped_column(BigInteger)


# ---------------------------------------------------------
# Fetch Log
# ---------------------------------------------------------


class FetchLogORM(Base):
    __tablename__ = "fetch_log"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )

    symbol: Mapped[str] = mapped_column(String)

    ts_utc: Mapped[int] = mapped_column(BigInteger)

    status: Mapped[str] = mapped_column(String)

    bars_received: Mapped[int] = mapped_column(Integer)

    detail: Mapped[str] = mapped_column(Text)


# ---------------------------------------------------------
# Scanner Status
# ---------------------------------------------------------


class ScannerStatusORM(Base):
    __tablename__ = "scanner_status"

    scanner_name: Mapped[str] = mapped_column(
        String,
        primary_key=True,
    )

    last_scan_utc: Mapped[int | None] = mapped_column(BigInteger)

    last_success_utc: Mapped[int | None] = mapped_column(BigInteger)

    status: Mapped[str] = mapped_column(String)

    message: Mapped[str | None] = mapped_column(Text)
"""
Domain Models

These classes represent the business objects used throughout
the application.

They are independent of PostgreSQL, Supabase and FastAPI.
"""

from dataclasses import dataclass
from typing import Optional


# --------------------------------------------------
# Market Bar
# --------------------------------------------------

@dataclass(slots=True)
class Bar:

    symbol: str

    ts_utc: int

    open: float

    high: float

    low: float

    close: float

    volume: float

    open_interest: float


# --------------------------------------------------
# Zone
# --------------------------------------------------

@dataclass(slots=True)
class Zone:

    symbol: str

    zone_type: str

    extreme_ts_utc: int

    confirm_ts_utc: int

    zone_top: float

    zone_bottom: float

    oi_extreme: float

    oi_confirm: float

    oi_change_pct: Optional[float]

    passed_oi_filter: bool


# --------------------------------------------------
# Fetch Log
# --------------------------------------------------

@dataclass(slots=True)
class FetchLog:

    symbol: str

    ts_utc: int

    status: str

    bars_received: int

    detail: str = ""
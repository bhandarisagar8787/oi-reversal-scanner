"""
market_db.py
============
Fast local storage for OHLCV + Open Interest bars, and for the reversal
zones detected from them.

DESIGN DECISION: every timestamp stored here is a true UTC epoch integer
(seconds since 1970-01-01 UTC). This is deliberate and important - it is
what makes the database "accurate" independent of any charting library's
display quirks. tvDatafeed hands back naive wall-clock IST timestamps
(e.g. "09:15:00" with no tz attached); we convert those to real UTC here,
once, at the point of ingestion, and never store anything ambiguous again.
Every reader (the zone engine, any report, any future chart feed) can
trust ts_utc completely and apply whatever display conversion it needs
locally - the source of truth itself is never in question.

SQLite is used in WAL mode for concurrent-safe, low-latency writes
without needing a server process - the right tool for a single-machine
scanner writing a few hundred rows every 30 minutes.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

IST_OFFSET = pd.Timedelta(hours=5, minutes=30)  # NSE/BSE exchange offset from UTC

DEFAULT_DB_PATH = Path(__file__).with_name("market_data.sqlite3")

SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    symbol          TEXT    NOT NULL,
    ts_utc          INTEGER NOT NULL,   -- true UTC epoch seconds, canonical
    open            REAL,
    high            REAL,
    low             REAL,
    close           REAL,
    volume          REAL,
    open_interest   REAL,
    PRIMARY KEY (symbol, ts_utc)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_bars_symbol_ts ON bars(symbol, ts_utc);

CREATE TABLE IF NOT EXISTS zones (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol           TEXT    NOT NULL,
    zone_type        TEXT    NOT NULL CHECK(zone_type IN ('bull', 'bear')),
    extreme_ts_utc   INTEGER NOT NULL,
    confirm_ts_utc   INTEGER NOT NULL,
    zone_top         REAL,
    zone_bottom      REAL,
    oi_extreme       REAL,
    oi_confirm       REAL,
    oi_change_pct    REAL,
    passed_oi_filter INTEGER NOT NULL,  -- 0/1
    detected_at_utc  INTEGER NOT NULL,
    UNIQUE(symbol, zone_type, extreme_ts_utc, confirm_ts_utc)
);

CREATE INDEX IF NOT EXISTS idx_zones_symbol_ts ON zones(symbol, confirm_ts_utc);

CREATE TABLE IF NOT EXISTS fetch_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol        TEXT    NOT NULL,
    ts_utc        INTEGER NOT NULL,
    status        TEXT    NOT NULL,   -- 'ok' | 'failed' | 'partial'
    bars_received INTEGER,
    detail        TEXT
);
"""


@contextmanager
def get_conn(db_path: Path = DEFAULT_DB_PATH):
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")     # concurrent readers while writing
    conn.execute("PRAGMA synchronous=NORMAL;")   # fast, still crash-safe under WAL
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    with get_conn(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def ist_naive_to_utc_epoch(series: pd.Series) -> pd.Series:
    """
    Convert a datetime series to true UTC epoch seconds.

    Handles BOTH shapes this function may be fed:
      1. Naive timestamps already in IST wall-clock time (the original
         tvDatafeed convention) -> subtract 5:30 to get true UTC.
      2. Timezone-AWARE timestamps already converted to UTC upstream
         (oi_reversal_scanner._normalise_df localizes to Asia/Kolkata then
         converts to UTC before this function ever sees it) -> just strip
         the tz info, no offset math needed.

    Applying the -5:30 shift to an already-UTC tz-aware series would
    double-shift it, and calling .astype("datetime64[s]") on tz-aware data
    raises a TypeError outright - both were happening before this fix.
    """
    dt = pd.to_datetime(series)
    if dt.dt.tz is not None:
        # Already timezone-aware -> convert to UTC, then drop tz info.
        utc_naive = dt.dt.tz_convert("UTC").dt.tz_localize(None)
    else:
        # Naive IST wall-clock -> true UTC = IST - 5:30.
        utc_naive = dt - IST_OFFSET

    return utc_naive.astype("datetime64[s]").astype("int64")

def upsert_bars(symbol: str, df: pd.DataFrame, db_path: Path = DEFAULT_DB_PATH) -> int:
    """
    df must have columns: datetime (naive IST timestamps), open, high, low,
    close, volume, open_interest. Idempotent - re-running with overlapping
    data just overwrites those rows, never duplicates them.
    Returns number of rows written.
    """
    if df is None or df.empty:
        return 0

    work = df.copy()
    work["ts_utc"] = ist_naive_to_utc_epoch(work["datetime"])
    cols = ["ts_utc", "open", "high", "low", "close", "volume", "open_interest"]
    for c in cols:
        if c not in work.columns:
            work[c] = None

    rows = [
        (symbol, int(r.ts_utc), r.open, r.high, r.low, r.close, r.volume, r.open_interest)
        for r in work[cols].itertuples(index=False)
    ]

    with get_conn(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO bars (symbol, ts_utc, open, high, low, close, volume, open_interest)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, ts_utc) DO UPDATE SET
                open=excluded.open, high=excluded.high, low=excluded.low,
                close=excluded.close, volume=excluded.volume,
                open_interest=excluded.open_interest
            """,
            rows,
        )
        conn.commit()
    return len(rows)


def get_bars(symbol: str, start_utc: Optional[int] = None, end_utc: Optional[int] = None,
             db_path: Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    q = "SELECT ts_utc, open, high, low, close, volume, open_interest FROM bars WHERE symbol = ?"
    params: list = [symbol]
    if start_utc is not None:
        q += " AND ts_utc >= ?"
        params.append(start_utc)
    if end_utc is not None:
        q += " AND ts_utc <= ?"
        params.append(end_utc)
    q += " ORDER BY ts_utc ASC"

    with get_conn(db_path) as conn:
        df = pd.read_sql_query(q, conn, params=params)
    return df


def get_all_symbols(db_path: Path = DEFAULT_DB_PATH) -> list[str]:
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT DISTINCT symbol FROM bars ORDER BY symbol").fetchall()
    return [r[0] for r in rows]


def upsert_zones(zones: Iterable[dict], db_path: Path = DEFAULT_DB_PATH) -> int:
    zones = list(zones)
    if not zones:
        return 0
    now = int(time.time())
    rows = [
        (
            z["symbol"], z["zone_type"], z["extreme_ts_utc"], z["confirm_ts_utc"],
            z["zone_top"], z["zone_bottom"], z["oi_extreme"], z["oi_confirm"],
            z["oi_change_pct"], int(bool(z["passed_oi_filter"])), now,
        )
        for z in zones
    ]
    with get_conn(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO zones (symbol, zone_type, extreme_ts_utc, confirm_ts_utc,
                                zone_top, zone_bottom, oi_extreme, oi_confirm,
                                oi_change_pct, passed_oi_filter, detected_at_utc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, zone_type, extreme_ts_utc, confirm_ts_utc) DO NOTHING
            """,
            rows,
        )
        conn.commit()
    return len(rows)


def get_zones(symbol: Optional[str] = None, only_passed: bool = False,
              db_path: Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    q = "SELECT * FROM zones WHERE 1=1"
    params: list = []
    if symbol:
        q += " AND symbol = ?"
        params.append(symbol)
    if only_passed:
        q += " AND passed_oi_filter = 1"
    q += " ORDER BY confirm_ts_utc DESC"
    with get_conn(db_path) as conn:
        df = pd.read_sql_query(q, conn, params=params)
    return df


def log_fetch(symbol: str, status: str, bars_received: int = 0, detail: str = "",
              db_path: Path = DEFAULT_DB_PATH) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO fetch_log (symbol, ts_utc, status, bars_received, detail) VALUES (?, ?, ?, ?, ?)",
            (symbol, int(time.time()), status, bars_received, detail),
        )
        conn.commit()


def utc_epoch_to_ist_str(ts_utc: int) -> str:
    """Display helper only - never stored, computed fresh each time."""
    ts = pd.Timestamp(ts_utc, unit="s", tz="UTC") + IST_OFFSET
    return ts.strftime("%Y-%m-%d %H:%M:%S") + " IST"

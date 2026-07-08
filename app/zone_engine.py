"""
zone_engine.py
==============
Faithful Python port of the Pine Script v6 "Day High/Low Reversal Zones"
indicator. Every rule is matched 1-to-1 against the Pine source.

Pine rules ported exactly:
─────────────────────────
• newDay resets day_low/day_high to that candle's high/low.
  Candle #1 SEEDS the day extreme values but:
    skip_first=True  → arm_bull/arm_bear stay None; candle #1 cannot be a zone.
    skip_first=False → candle #1 arms both bull and bear immediately.
  After the `continue` in Pine (newDay block), the rest of the bar's logic
  does NOT run — this port matches that exactly.

• Re-arm: every time a LATER candle (candle #2+) prints a new session low,
  arm_bull is reset to that candle and bull_conf is cleared.
  Symmetric for session highs / bear.

• strict_next=True  → only bar_index == arm_idx + 1 can confirm.
  strict_next=False → any later bar in the session can confirm.

• Bullish confirm: close > arm_bull["high"]   (engulf the extreme candle).
  Bearish confirm: close < arm_bear["low"]    (engulf the extreme candle).

• OI filter: zone is FINAL-VALID only if confirming candle OI ≥ extreme
  candle OI + oi_zone_pct%. When oi_filter=False every zone is stored with
  its pass/fail flag (matching Pine's `if not oiFilter or pass` logic).

• break_stop=True: once confirmed, if a later close crosses back through the
  zone boundary the "active box" is dropped (visual only — the zone record
  stays in the log).

CRITICAL FIX vs previous version:
  Zones are returned as DICTS (not objects). The scanner's zone_confirm_ist()
  was calling getattr() on dicts which always returns None. All timestamp
  lookups now use dict key access directly in the scanner filter.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

IST_OFFSET = pd.Timedelta(hours=5, minutes=30)


@dataclass
class ZoneParams:
    skip_first:  bool  = True
    track_bull:  bool  = True
    track_bear:  bool  = True
    strict_next: bool  = True
    break_stop:  bool  = True
    oi_filter:   bool  = True
    oi_zone_pct: float = 0.10   # percent, e.g. 0.10 means 0.10%


def _to_ist_date(ts_utc_series: pd.Series) -> pd.Series:
    """Convert a series of UTC epoch ints → IST calendar date."""
    return (
        pd.to_datetime(ts_utc_series, unit="s", utc=True)
        .dt.tz_convert("Asia/Kolkata")
        .dt.date
    )


def _to_ist_dt(ts_utc: int) -> pd.Timestamp:
    return pd.Timestamp(ts_utc, unit="s", tz="UTC").tz_convert("Asia/Kolkata")


def _oi_pass(oi1, oi2, pct_threshold: float) -> tuple[bool, Optional[float]]:
    """
    Returns (passed: bool, change_pct: float | None).
    Matches Pine exactly:
        pass = not na(oi1) and oi1 != 0 and not na(oi2) and
               (oi2 - oi1) / oi1 * 100 >= oiZonePct
    """
    try:
        if oi1 is None or pd.isna(oi1) or oi1 == 0:
            return False, None
        if oi2 is None or pd.isna(oi2):
            return False, None
        pct = (oi2 - oi1) / abs(oi1) * 100.0
        return pct >= pct_threshold, pct
    except Exception:
        return False, None


def detect_zones(
    df: pd.DataFrame,
    symbol: str,
    params: ZoneParams = ZoneParams(),
) -> list[dict]:
    """
    df must have columns: ts_utc, open, high, low, close, volume, open_interest
    (as returned by market_db.get_bars). Sorted ascending internally.

    Returns list of zone dicts with keys:
        symbol, zone_type, extreme_ts_utc, confirm_ts_utc,
        zone_top, zone_bottom, oi_extreme, oi_confirm,
        oi_change_pct, passed_oi_filter
    """
    if df is None or df.empty:
        return []

    d = df.sort_values("ts_utc").reset_index(drop=True)
    d["_ist_date"] = _to_ist_date(d["ts_utc"])

    zones: list[dict] = []

    # ── State variables mirroring Pine vars ──────────────────────────────────
    day_low  = None
    day_high = None

    arm_bull: Optional[dict] = None   # {idx, high, low, oi, ts_utc}
    arm_bear: Optional[dict] = None

    bull_conf = False
    bear_conf = False

    # Visual box state (break_stop tracking only)
    bull_box_active = False
    bear_box_active = False
    bull_box_bot    = None
    bear_box_top    = None

    prev_date = None

    for i, row in d.iterrows():
        cur_date = row["_ist_date"]
        new_day  = (prev_date is None) or (cur_date != prev_date)
        prev_date = cur_date

        # ── Pine: newDay block (runs then `continue` — nothing else this bar) ─
        if new_day:
            bull_box_active = False
            bear_box_active = False
            day_low  = float(row["low"])
            day_high = float(row["high"])
            bull_conf = False
            bear_conf = False

            if params.skip_first:
                # Candle #1 seeds day_low/day_high but cannot be an arm
                arm_bull = None
                arm_bear = None
            else:
                seed = {
                    "idx":    i,
                    "ts_utc": int(row["ts_utc"]),
                    "high":   float(row["high"]),
                    "low":    float(row["low"]),
                    "oi":     float(row["open_interest"]),
                }
                arm_bull = dict(seed)
                arm_bear = dict(seed)

            continue   # ← matches Pine's implicit skip of rest-of-bar on newDay

        # ── Extend / invalidate active zone boxes ────────────────────────────
        if bull_box_active and params.break_stop:
            if float(row["close"]) < bull_box_bot:
                bull_box_active = False

        if bear_box_active and params.break_stop:
            if float(row["close"]) > bear_box_top:
                bear_box_active = False

        # ── Re-arm on new session extreme (candle #2 onward) ─────────────────
        # Pine: `if trackBull and low < dayLow`  (strict less-than)
        if params.track_bull and float(row["low"]) < day_low:
            day_low  = float(row["low"])
            arm_bull = {
                "idx":    i,
                "ts_utc": int(row["ts_utc"]),
                "high":   float(row["high"]),
                "low":    float(row["low"]),
                "oi":     float(row["open_interest"]),
            }
            bull_conf = False

        # Pine: `if trackBear and high > dayHigh`  (strict greater-than)
        if params.track_bear and float(row["high"]) > day_high:
            day_high = float(row["high"])
            arm_bear = {
                "idx":    i,
                "ts_utc": int(row["ts_utc"]),
                "high":   float(row["high"]),
                "low":    float(row["low"]),
                "oi":     float(row["open_interest"]),
            }
            bear_conf = False

        # ── Bullish confirmation ──────────────────────────────────────────────
        if params.track_bull and not bull_conf and arm_bull is not None:
            if params.strict_next:
                elig = (i == arm_bull["idx"] + 1)
            else:
                elig = (i > arm_bull["idx"])

            if elig and float(row["close"]) > arm_bull["high"]:
                bull_conf = True
                passed, pct = _oi_pass(arm_bull["oi"], float(row["open_interest"]), params.oi_zone_pct)

                # Pine: `if not oiFilter or pass` → store when filter off OR filter passes
                if not params.oi_filter or passed:
                    bull_box_active = True
                    bull_box_bot    = arm_bull["low"]
                    zones.append({
                        "symbol":          symbol,
                        "zone_type":       "bull",
                        "extreme_ts_utc":  arm_bull["ts_utc"],
                        "confirm_ts_utc":  int(row["ts_utc"]),
                        "zone_top":        arm_bull["high"],
                        "zone_bottom":     arm_bull["low"],
                        "oi_extreme":      arm_bull["oi"],
                        "oi_confirm":      float(row["open_interest"]),
                        "oi_change_pct":   pct,
                        "passed_oi_filter": int(passed),
                    })

        # ── Bearish confirmation ──────────────────────────────────────────────
        if params.track_bear and not bear_conf and arm_bear is not None:
            if params.strict_next:
                elig = (i == arm_bear["idx"] + 1)
            else:
                elig = (i > arm_bear["idx"])

            if elig and float(row["close"]) < arm_bear["low"]:
                bear_conf = True
                passed, pct = _oi_pass(arm_bear["oi"], float(row["open_interest"]), params.oi_zone_pct)

                if not params.oi_filter or passed:
                    bear_box_active = True
                    bear_box_top    = arm_bear["high"]
                    zones.append({
                        "symbol":          symbol,
                        "zone_type":       "bear",
                        "extreme_ts_utc":  arm_bear["ts_utc"],
                        "confirm_ts_utc":  int(row["ts_utc"]),
                        "zone_top":        arm_bear["high"],
                        "zone_bottom":     arm_bear["low"],
                        "oi_extreme":      arm_bear["oi"],
                        "oi_confirm":      float(row["open_interest"]),
                        "oi_change_pct":   pct,
                        "passed_oi_filter": int(passed),
                    })

    return zones

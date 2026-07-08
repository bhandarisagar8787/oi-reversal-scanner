"""
oi_reversal_scanner.py
=======================
Multi-symbol OI Reversal Zone scanner — market-hours aware.

USAGE
─────
  python oi_reversal_scanner.py                    # live loop, every 30 min
  python oi_reversal_scanner.py --date today       # scan today, then exit
  python oi_reversal_scanner.py --date 2026-07-01  # backtest any past date

FETCH SCHEDULE (live mode)
──────────────────────────
  09:30 IST → first fetch (after the 9:00-9:30 extended candle closes)
  10:00, 10:30, 11:00 … 15:00 → every 30 min
  After 15:00 IST → sleep until next day 09:30

ZONE FILTER (enforced BEFORE writing to DB)
───────────────────────────────────────────
  Zone engine receives FULL bar history (prior days + today's extended candles)
  so it has proper context. But zones whose CONFIRM candle closed before 10:30
  IST on the target date are DISCARDED entirely — never written to DB.
  Only zones confirmed 10:30 – 15:00 IST are stored and shown.

OI ALIGNMENT FIX
─────────────────
  OI bars are merged by TIMESTAMP (not by position) so a missing bar in one
  series never shifts OI onto the wrong candle.

  ADDITIONAL FIX (verified against live Pine tooltips on 2026-07-03 AXISBANK):
  Pine's oiNow reflects the OI print AS OF a bar's own close. tvDatafeed's
  raw OI series comes back stored one bar LATER than that convention — i.e.
  the OI value that belongs to a given bar's close is found on the NEXT row
  of the raw feed. We correct this with a single `.shift(-1)` immediately
  after the OI column is established (whether it arrived embedded in the
  price bars or via a separate merged OI series), so every OI value lines
  up with the same bar Pine would show it on.
"""
from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta, date as date_type

import pandas as pd
from tvDatafeed import Interval, TvDatafeed

from app import market_db as mdb
from app.zone_engine import ZoneParams, detect_zones

# ══════════════════════════════ CONFIG ═══════════════════════════════════════
NSE_WATCHLIST = [
    "NIFTY", "BANKNIFTY",
    "ADANIENT", "ADANIPORTS", "ADANIGREEN", "AXISBANK", "BAJAJ_AUTO", "BHARTIARTL",
    "BHEL", "BSE", "HAL", "HEROMOTOCO", "HINDALCO", "JINDALSTEL", "JSWSTEEL",
    "LAURUSLABS", "LT", "M&M", "MARUTI", "MCX", "RELIANCE", "SBIN",
    "SHRIRAMFIN", "TRENT", "TVSMOTOR"
]

INTERVAL            = Interval.in_30_minute
MAX_FETCH_WORKERS   = 2
FETCH_STAGGER_SECS  = 0.4
MAX_RETRY_ROUNDS    = 3
RETRY_COOLDOWN_SECS = 8

LIVE_BARS_COUNT     = 500
BARS_PER_DAY        = 20
CONTEXT_DAYS        = 5

MARKET_OPEN_IST     = (9,  30)
MARKET_CLOSE_IST    = (15,  0)
REPORT_START_IST    = (10, 30)
REPORT_END_IST      = (15,  0)

ZONE_PARAMS = ZoneParams(
    skip_first=True, track_bull=True, track_bear=True,
    strict_next=True, break_stop=True,
    oi_filter=True, oi_zone_pct=0.10,
)

tv  = TvDatafeed()
IST = timezone(timedelta(hours=5, minutes=30))


# ══════════════════════════════ TIME HELPERS ══════════════════════════════════
def now_ist() -> datetime:
    return datetime.now(IST)


def ist_dt(h: int, m: int, d: date_type | None = None) -> datetime:
    base = d or now_ist().date()
    return datetime(base.year, base.month, base.day, h, m, tzinfo=IST)


def seconds_until_market_open() -> float:
    now = now_ist()
    today_open = ist_dt(*MARKET_OPEN_IST)
    if now < today_open:
        return (today_open - now).total_seconds()
    tomorrow = now.date() + timedelta(days=1)
    return (ist_dt(*MARKET_OPEN_IST, d=tomorrow) - now).total_seconds()


def seconds_until_next_30min_bar() -> float:
    now_epoch        = time.time()
    next_close_epoch = now_epoch + (1800 - now_epoch % 1800)
    next_close_ist   = datetime.fromtimestamp(next_close_epoch, tz=IST)
    if next_close_ist > ist_dt(*MARKET_CLOSE_IST):
        return seconds_until_market_open()
    return next_close_epoch - now_epoch


def is_in_report_window(ts_utc_epoch: int, check_date: date_type) -> bool:
    bar_open_ist  = datetime.fromtimestamp(ts_utc_epoch, tz=IST)
    bar_close_ist = bar_open_ist + timedelta(minutes=30)

    return (
        bar_close_ist.date() == check_date
        and ist_dt(*REPORT_START_IST, d=check_date) <= bar_close_ist <= ist_dt(*REPORT_END_IST, d=check_date)
    )


def confirm_close_ist_str(ts_utc_epoch: int) -> str:
    bar_open  = datetime.fromtimestamp(ts_utc_epoch, tz=IST)
    bar_close = bar_open + timedelta(minutes=30)
    return bar_close.strftime("%Y-%m-%d %H:%M:%S IST")


def extreme_open_ist_str(ts_utc_epoch: int) -> str:
    return datetime.fromtimestamp(ts_utc_epoch, tz=IST).strftime("%Y-%m-%d %H:%M:%S IST")


# ══════════════════════════════ DATE HELPERS ══════════════════════════════════
def parse_target_date(s: str) -> date_type:
    return datetime.strptime(s, "%Y-%m-%d").date()


def bars_needed_for_date(target_date: date_type) -> int:
    today    = now_ist().date()
    days_back = max((today - target_date).days, 0) + 1 + CONTEXT_DAYS
    return min(days_back * BARS_PER_DAY, 2000)


# ══════════════════════════════ FETCH ════════════════════════════════════════
def _fetch_raw(symbol: str, exchange: str, n_bars: int, max_attempts: int = 5):
    for attempt in range(1, max_attempts + 1):
        try:
            df = tv.get_hist(symbol=symbol, exchange=exchange,
                             interval=INTERVAL, n_bars=n_bars,
                             extended_session=True)
            if df is not None and not df.empty:
                return df
        except Exception:
            pass
        time.sleep(attempt * 1.5)
    return None


def _normalise_df(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.reset_index()
    df = df.rename(columns={df.columns[0]: "datetime"})
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    df = df.dropna(subset=["datetime"]).reset_index(drop=True)

    df["datetime"] = (
        df["datetime"]
        .dt.tz_localize("Asia/Kolkata")
        .dt.tz_convert("UTC")
    )
    return df


def _fetch_oi(root: str, n_bars: int) -> pd.DataFrame | None:
    for sym in (f"{root}1!_OI", f"{root}_OI"):
        raw = _fetch_raw(sym, "NSE", n_bars)
        if raw is not None and not raw.empty:
            df = _normalise_df(raw)
            val_col = "open_interest" if "open_interest" in df.columns else "close"
            df = df[["datetime", val_col]].rename(columns={val_col: "oi_value"})
            print(f"  [OI-OK]   {root}: OI from {sym} ({val_col} col)")
            return df
    return None


def fetch_one_symbol(root: str, n_bars: int) -> tuple[str, pd.DataFrame | None, bool]:
    """
    Returns (root, merged_df_or_None, oi_was_zero).
    OI is merged by TIMESTAMP so a missing bar never shifts OI onto wrong candle,
    then shifted back one bar so each OI value aligns with the same bar's close
    that Pine's oiNow shows it on (see OI ALIGNMENT FIX in module docstring).
    """
    raw = _fetch_raw(f"{root}1!", "NSE", n_bars)
    if raw is None or raw.empty:
        raw = _fetch_raw(root, "NSE", n_bars)
    if raw is None or raw.empty:
        return root, None, False

    p_df = _normalise_df(raw)
    if p_df.empty:
        return root, None, False

    oi_was_zero = False

    if "open_interest" in p_df.columns:
        print(f"  [OI-OK]   {root}: OI already inside price bars")
        # Bar-close alignment fix — see module docstring "OI ALIGNMENT FIX".
        p_df["open_interest"] = p_df["open_interest"].shift(-1)
    else:
        oi_df = _fetch_oi(root, n_bars)
        if oi_df is not None:
            p_df = p_df.merge(oi_df, on="datetime", how="left")
            p_df = p_df.rename(columns={"oi_value": "open_interest"})
            # Bar-close alignment fix — see module docstring "OI ALIGNMENT FIX".
            p_df["open_interest"] = p_df["open_interest"].shift(-1)
        else:
            print(f"  [OI-FAIL] {root}: all OI variants failed — "
                  f"OI=0, zone OI filter BYPASSED this cycle.")
            p_df["open_interest"] = 0.0
            oi_was_zero = True

    p_df["open_interest"] = pd.to_numeric(p_df["open_interest"], errors="coerce")
    # bfill() first covers the shift(-1)'s trailing NaN (last row has nothing
    # to shift into it) with the previous known value instead of zero.
    p_df["open_interest"] = p_df["open_interest"].ffill().bfill().fillna(0.0)

    if not oi_was_zero and (p_df["open_interest"] == 0).all():
        print(f"  [OI-ZERO] {root}: OI column all-zeros — "
              f"zone OI filter BYPASSED this cycle.")
        oi_was_zero = True

    keep = ["datetime", "open", "high", "low", "close", "volume", "open_interest"]
    p_df = p_df[[c for c in keep if c in p_df.columns]]
    return root, p_df, oi_was_zero


def fetch_cycle(watchlist: list[str], n_bars: int) -> tuple[dict, set]:
    pending      = list(watchlist)
    results      = {}
    oi_zero_syms = set()

    for round_num in range(1, MAX_RETRY_ROUNDS + 1):
        if not pending:
            break
        label = "fetch" if round_num == 1 else f"retry round {round_num}"
        print(f"\n[CYCLE] {label}: {len(pending)} symbol(s) → {pending}")

        failed = []
        with ThreadPoolExecutor(max_workers=MAX_FETCH_WORKERS) as pool:
            futures = {pool.submit(fetch_one_symbol, sym, n_bars): sym
                       for sym in pending}
            time.sleep(FETCH_STAGGER_SECS * len(pending))

            for future in as_completed(futures):
                sym = futures[future]
                try:
                    _, df, oi_zero = future.result()
                    if df is not None and not df.empty:
                        results[sym] = df
                        if oi_zero:
                            oi_zero_syms.add(sym)
                        mdb.log_fetch(sym, "ok", bars_received=len(df))
                        tag = " [OI=0→filter bypassed]" if oi_zero else ""
                        print(f"  [OK] {sym}: {len(df)} bars fetched{tag}")
                    else:
                        failed.append(sym)
                        mdb.log_fetch(sym, "failed", detail="empty/None")
                        print(f"  [FAIL] {sym}: no data returned")
                except Exception as e:
                    failed.append(sym)
                    mdb.log_fetch(sym, "failed", detail=str(e))
                    print(f"  [ERROR] {sym}: {e}")

        pending = failed
        if pending and round_num < MAX_RETRY_ROUNDS:
            print(f"  [RETRY] {len(pending)} symbol(s) retrying in "
                  f"{RETRY_COOLDOWN_SECS}s: {pending}")
            time.sleep(RETRY_COOLDOWN_SECS)

    if pending:
        print(f"[CYCLE] Gave up on {pending} after {MAX_RETRY_ROUNDS} rounds.")

    return results, oi_zero_syms


# ══════════════════════════════ STORE ════════════════════════════════════════
def store_bars(fetched: dict, target_date: date_type | None) -> list[str]:
    stored_syms = []
    print()
    for sym, df in fetched.items():
        if target_date is not None:
            dt = pd.to_datetime(df["datetime"])
            dt_ist = dt.dt.tz_convert(IST) if dt.dt.tz is not None else dt.dt.tz_localize(IST)
            on_date  = (dt_ist.dt.date == target_date).sum()
            ctx_bars = (dt_ist.dt.date < target_date).sum()
            if on_date == 0:
                print(f"  [DB] {sym}: SKIP — no bars found for {target_date} IST "
                      f"(market closed or data gap)")
                continue
            n = mdb.upsert_bars(sym, df)
            print(f"  [DB] {sym}: {n} bars stored "
                  f"({ctx_bars} context + {on_date} on {target_date})")
        else:
            n = mdb.upsert_bars(sym, df)
            print(f"  [DB] {sym}: {n} bars stored")
        stored_syms.append(sym)
    return stored_syms


# ══════════════════════════════ ZONE SCAN ════════════════════════════════════
def _make_no_oi_params() -> ZoneParams:
    return ZoneParams(
        skip_first=ZONE_PARAMS.skip_first,
        track_bull=ZONE_PARAMS.track_bull,
        track_bear=ZONE_PARAMS.track_bear,
        strict_next=ZONE_PARAMS.strict_next,
        break_stop=ZONE_PARAMS.break_stop,
        oi_filter=False,
        oi_zone_pct=ZONE_PARAMS.oi_zone_pct,
    )


def scan_zones(
    stored_syms: list[str],
    oi_zero_syms: set[str],
    target_date: date_type,
) -> int:
    params_no_oi   = _make_no_oi_params()
    new_zone_count = 0

    print()
    for sym in stored_syms:
        bars = mdb.get_bars(sym)
        if bars.empty:
            print(f"  [ZONES] {sym}: no bars in DB — skipping")
            continue

        use_params = params_no_oi if sym in oi_zero_syms else ZONE_PARAMS
        oi_note    = " (OI filter OFF — no OI data)" if sym in oi_zero_syms else ""

        all_zones = detect_zones(bars, sym, use_params)
        if not all_zones:
            print(f"  [ZONES] {sym}: 0 zones detected{oi_note}")
            continue

        valid_zones = [
            z for z in all_zones
            if is_in_report_window(z["confirm_ts_utc"], target_date)
        ]
        too_early = len(all_zones) - len(valid_zones)

        early_msg = (f" | {too_early} pre-10:30 discarded" if too_early else "")

        if not valid_zones:
            print(f"  [ZONES] {sym}: {len(all_zones)} detected{early_msg} | "
                  f"0 in report window{oi_note}")
            continue

        passed   = sum(1 for z in valid_zones if z.get("passed_oi_filter", 1))
        failed_n = len(valid_zones) - passed
        written  = mdb.upsert_zones(valid_zones)
        new_zone_count += written

        print(f"  [ZONES] {sym}: {len(all_zones)} detected{early_msg} | "
              f"{len(valid_zones)} in window | "
              f"{passed} passed OI | {failed_n} failed OI | "
              f"{written} new written{oi_note}")

    return new_zone_count


# ══════════════════════════════ REPORT ═══════════════════════════════════════
def print_recent_zones(target_date: date_type, limit: int = 30):
    all_rows = []
    for sym in NSE_WATCHLIST:
        z = mdb.get_zones(symbol=sym, only_passed=True)
        if z.empty:
            continue
        mask = z["confirm_ts_utc"].apply(
            lambda ts: is_in_report_window(int(ts), target_date)
        )
        z = z[mask]
        if not z.empty:
            all_rows.append(z)

    win = (f"{REPORT_START_IST[0]:02d}:{REPORT_START_IST[1]:02d}"
           f"–{REPORT_END_IST[0]:02d}:{REPORT_END_IST[1]:02d} IST")

    if not all_rows:
        print(f"[ZONES] No confirmed zones in window ({win}) on {target_date}.")
        return

    combined = (
        pd.concat(all_rows)
        .sort_values("confirm_ts_utc", ascending=False)
        .head(limit)
    )
    print(f"\n[ZONES] Confirmed zones on {target_date} ({win}) — top {limit}:")
    print(f"{'SYMBOL':<12}{'TYPE':<6}{'EXTREME open(IST)':<26}{'CONFIRM close(IST)':<26}"
          f"{'TOP':>10}{'BOTTOM':>10}{'OI Δ%':>9}")
    for _, r in combined.iterrows():
        print(f"{r['symbol']:<12}{r['zone_type']:<6}"
              f"{extreme_open_ist_str(r['extreme_ts_utc']):<26}"
              f"{confirm_close_ist_str(r['confirm_ts_utc']):<26}"
              f"{r['zone_top']:>10.2f}{r['zone_bottom']:>10.2f}"
              f"{r['oi_change_pct']:>8.2f}%")


# ══════════════════════════════ CYCLE ════════════════════════════════════════
def run_cycle(target_date: date_type | None = None):
    today = now_ist().date()
    scan_date = target_date if target_date is not None else today

    print(f"\n{'═'*70}")
    mode = f"DATE MODE ({scan_date})" if target_date else f"LIVE MODE ({scan_date})"
    print(f"[SCANNER] Cycle start [{mode}]: "
          f"{now_ist().strftime('%Y-%m-%d %H:%M:%S %Z')}")

    if target_date is not None:
        n_bars = bars_needed_for_date(target_date)
        print(f"[SCANNER] Fetching {n_bars} bars/symbol "
              f"(covers {target_date} + {CONTEXT_DAYS} prior-day context)")
    else:
        n_bars = LIVE_BARS_COUNT

    fetched, oi_zero_syms = fetch_cycle(NSE_WATCHLIST, n_bars=n_bars)

    if oi_zero_syms:
        print(f"\n[OI-SUMMARY] OI missing/zero → filter bypassed: {sorted(oi_zero_syms)}")

    stored_syms    = store_bars(fetched, target_date)
    new_zone_count = scan_zones(stored_syms, oi_zero_syms, scan_date)

    print_recent_zones(scan_date)
    print(f"\n[SCANNER] Cycle complete — {new_zone_count} new zone row(s) written.")


# ══════════════════════════════ LIVE SCHEDULER ════════════════════════════════
def run_live_loop():
    while True:
        now          = now_ist()
        market_open  = ist_dt(*MARKET_OPEN_IST)
        market_close = ist_dt(*MARKET_CLOSE_IST)

        if now < market_open:
            wait = (market_open - now).total_seconds()
            print(f"\n[SCHEDULER] Before market open. "
                  f"Sleeping {wait/60:.1f} min until "
                  f"{MARKET_OPEN_IST[0]:02d}:{MARKET_OPEN_IST[1]:02d} IST ...")
            time.sleep(wait)
            continue

        if now > market_close:
            wait     = seconds_until_market_open()
            wake_at  = now_ist() + timedelta(seconds=wait)
            print(f"\n[SCHEDULER] Market closed. "
                  f"Sleeping {wait/3600:.1f} hrs until "
                  f"{wake_at.strftime('%Y-%m-%d %H:%M IST')} ...")
            time.sleep(wait)
            continue

        try:
            run_cycle()
        except Exception as e:
            print(f"[SCANNER] Cycle crashed: {e} — retrying next bar.")

        now_after = now_ist()
        if now_after >= market_close:
            wait    = seconds_until_market_open()
            wake_at = now_ist() + timedelta(seconds=wait)
            print(f"\n[SCHEDULER] Last cycle done. Sleeping until "
                  f"{wake_at.strftime('%Y-%m-%d %H:%M IST')} ...")
            time.sleep(wait)
        else:
            wait     = seconds_until_next_30min_bar()
            next_bar = now_ist() + timedelta(seconds=wait)
            print(f"\n[SCHEDULER] Next fetch at "
                  f"{next_bar.strftime('%H:%M IST')} ({wait/60:.1f} min) ...")
            time.sleep(wait)


# ══════════════════════════════ CLI ══════════════════════════════════════════
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="OI Reversal Zone Scanner — market-hours aware",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python oi_reversal_scanner.py                    # live loop every 30 min
  python oi_reversal_scanner.py --date today       # scan today, then exit
  python oi_reversal_scanner.py --date 2026-07-01  # backtest a past date
        """,
    )
    p.add_argument(
        "--date", metavar="YYYY-MM-DD|today", default=None,
        help="Date to scan (IST). Fetches full history for context; "
             "reports only zones confirmed 10:30–15:00 on that date. Exits after scan.",
    )
    return p


def main():
    args = build_parser().parse_args()
    mdb.init_db()
    print(f"[SCANNER] DB ready: {mdb.DEFAULT_DB_PATH}")
    print(f"[SCANNER] Fetch window : "
          f"{MARKET_OPEN_IST[0]:02d}:{MARKET_OPEN_IST[1]:02d}–"
          f"{MARKET_CLOSE_IST[0]:02d}:{MARKET_CLOSE_IST[1]:02d} IST")
    print(f"[SCANNER] Report window: "
          f"{REPORT_START_IST[0]:02d}:{REPORT_START_IST[1]:02d}–"
          f"{REPORT_END_IST[0]:02d}:{REPORT_END_IST[1]:02d} IST")

    if args.date:
        raw = args.date.strip().lower()
        if raw == "today":
            target_date = now_ist().date()
        else:
            try:
                target_date = parse_target_date(raw)
            except ValueError:
                print(f"[ERROR] Bad date '{args.date}'. Use YYYY-MM-DD or 'today'.")
                return
        if target_date > now_ist().date():
            print(f"[ERROR] {target_date} is in the future.")
            return
        print(f"[SCANNER] DATE MODE → scanning {target_date}")
        run_cycle(target_date=target_date)
        return

    print("[SCANNER] LIVE MODE → market-hours scheduler starting.")
    run_live_loop()


if __name__ == "__main__":
    main()

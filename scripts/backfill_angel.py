#!/usr/bin/env python3
"""
Backfill historical 1-min options candles from Angel One SmartAPI.
Fetches NIFTY + BANKNIFTY F&O OHLCV + spot, writes to DuckDB.

NOTE: Angel One historical options OI = 0 (API limitation). Prices correct.

Usage (run on VPS after 15:30 IST):
    cd /opt/trading
    .venv/bin/python scripts/backfill_angel.py --from 2026-03-17 --to 2026-06-17
    .venv/bin/python scripts/backfill_angel.py --from 2026-03-17 --to 2026-06-17 --underlyings BANKNIFTY
    .venv/bin/python scripts/backfill_angel.py --help
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

import polars as pl

from config import settings
from src.data import storage
from src.data.angelone_scrip import (
    INDEX_SPOT_TOKENS,
    fetch_scrip_master,
    resolve_option_tokens,
)

IST = ZoneInfo("Asia/Kolkata")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backfill")

# NSE strike intervals
STRIKE_STEP = {"NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50, "MIDCPNIFTY": 25}

# Angel One rate limit: 3 historical candle requests/sec
_RPS_LIMIT = 3
_last_t = 0.0


def _throttle():
    global _last_t
    wait = (1.0 / _RPS_LIMIT) - (time.time() - _last_t)
    if wait > 0:
        time.sleep(wait)
    _last_t = time.time()


def _login():
    try:
        import pyotp
        from SmartApi import SmartConnect
    except ImportError:
        log.error("Install: pip install smartapi-python pyotp")
        sys.exit(1)
    smart = SmartConnect(api_key=settings.angelone_api_key)
    totp = pyotp.TOTP(settings.angelone_totp_secret).now()
    res = smart.generateSession(
        settings.angelone_client_code, settings.angelone_pin, totp
    )
    if not (res and res.get("status")):
        raise RuntimeError(f"Login failed: {res.get('message') if res else 'no response'}")
    log.info("Angel One login OK")
    return smart


def _trading_days(from_d: date, to_d: date) -> list[date]:
    out, d = [], from_d
    while d <= to_d:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _fetch_candles(smart, exchange: str, token: str, day: date) -> list:
    """Call getCandleData with throttling. Returns raw rows or []."""
    _throttle()
    try:
        res = smart.getCandleData({
            "exchange": exchange,
            "symboltoken": token,
            "interval": "ONE_MINUTE",
            "fromdate": f"{day} 09:15",
            "todate": f"{day} 15:30",
        })
        if res and res.get("status") and res.get("data"):
            return res["data"]
    except Exception as e:
        log.debug(f"getCandleData {exchange}/{token} {day}: {e}")
    return []


def _to_df(rows: list) -> pl.DataFrame:
    """Convert Angel One candle rows → polars df (IST naive timestamps)."""
    ts, o, h, l, c, v = [], [], [], [], [], []
    for row in rows:
        try:
            t = datetime.fromisoformat(row[0]).astimezone(IST).replace(tzinfo=None)
            ts.append(t); o.append(float(row[1])); h.append(float(row[2]))
            l.append(float(row[3])); c.append(float(row[4])); v.append(int(row[5]))
        except Exception:
            continue
    if not ts:
        return pl.DataFrame()
    return pl.DataFrame({"ts": ts, "open": o, "high": h, "low": l, "close": c, "volume": v})


def _existing_opt_dates(underlying: str) -> set[date]:
    cur = storage.db().cursor()
    try:
        rows = cur.execute(
            "SELECT DISTINCT ts::DATE FROM options_1m WHERE underlying=?", [underlying]
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        cur.close()


def _existing_spot_dates(underlying: str) -> set[date]:
    cur = storage.db().cursor()
    try:
        rows = cur.execute(
            "SELECT DISTINCT ts::DATE FROM spot_1m WHERE underlying=?", [underlying]
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        cur.close()


def _active_expiries(day: date, scrip: list, underlying: str, max_n: int = 3) -> list[str]:
    """Return ISO expiries active on `day` (not yet expired), nearest max_n."""
    want = underlying.upper()
    exp_dates: set[date] = set()
    for row in scrip:
        if row.get("name") != want or row.get("instrumenttype") != "OPTIDX":
            continue
        try:
            exp_d = datetime.strptime(row["expiry"], "%d%b%Y").date()
        except (ValueError, KeyError):
            continue
        if exp_d >= day:
            exp_dates.add(exp_d)
    return [d.isoformat() for d in sorted(exp_dates)[:max_n]]


def _backfill_day(
    smart,
    scrip: list,
    day: date,
    underlying: str,
    strikes_radius: int,
    spot_tok: str,
    fetch_spot: bool,
) -> dict:
    step = STRIKE_STEP.get(underlying, 50)
    stats = {"opt": 0, "spot": 0, "tokens": 0}

    # --- Spot ---
    if fetch_spot:
        spot_raw = _fetch_candles(smart, "NSE", spot_tok, day)
        if not spot_raw:
            log.warning(f"  {underlying} {day}: no spot data — skipping")
            return stats
        sdf = _to_df(spot_raw).with_columns(pl.lit(underlying).alias("underlying"))
        stats["spot"] = storage.write_spot(sdf)
        open_spot = float(spot_raw[0][4])  # first candle close as ATM ref
    else:
        # read ATM ref from already-stored spot
        cur = storage.db().cursor()
        try:
            row = cur.execute(
                "SELECT close FROM spot_1m WHERE underlying=? AND ts::DATE=? ORDER BY ts LIMIT 1",
                [underlying, day]
            ).fetchone()
        finally:
            cur.close()
        if not row:
            log.warning(f"  {underlying} {day}: no spot in DB — skipping options")
            return stats
        open_spot = float(row[0])

    # ATM ± radius
    atm = int(round(open_spot / step) * step)
    want_strikes = [atm + i * step for i in range(-strikes_radius, strikes_radius + 1)]

    # --- Options per expiry ---
    expiries = _active_expiries(day, scrip, underlying)
    if not expiries:
        log.warning(f"  {underlying} {day}: no active expiries in scrip")
        return stats

    for exp_iso in expiries:
        token_map = resolve_option_tokens(underlying, exp_iso, want_strikes, scrip)
        if not token_map:
            continue
        stats["tokens"] += len(token_map)
        exp_date = date.fromisoformat(exp_iso)
        bufs = []
        for tok, meta in token_map.items():
            raw = _fetch_candles(smart, "NFO", tok, day)
            if not raw:
                continue
            df = _to_df(raw)
            if df.is_empty():
                continue
            df = df.with_columns([
                pl.lit(underlying).alias("underlying"),
                pl.lit(exp_date).alias("expiry"),
                pl.lit(meta["strike"]).cast(pl.Int32).alias("strike"),
                pl.lit(meta["opt_type"]).alias("option_type"),
                pl.lit(0).cast(pl.Int64).alias("oi"),
            ])
            bufs.append(df)
        if bufs:
            stats["opt"] += storage.write_options(pl.concat(bufs))

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Backfill Angel One historical 1-min options data into DuckDB"
    )
    parser.add_argument("--from", dest="from_date", required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--underlyings", default="NIFTY,BANKNIFTY")
    parser.add_argument("--strikes", type=int, default=15,
                        help="ATM ± N strike radius (default 15 → 31 strikes per CE+PE)")
    parser.add_argument("--expiries", type=int, default=3,
                        help="Max active expiries per day (default 3)")
    parser.add_argument("--refetch", action="store_true",
                        help="Re-fetch days already in DB (default: skip existing)")
    args = parser.parse_args()

    from_date = date.fromisoformat(args.from_date)
    to_date   = date.fromisoformat(args.to_date)
    underlyings = [u.strip().upper() for u in args.underlyings.split(",")]

    if not settings.angelone_ready:
        log.error("Angel One credentials missing in .env")
        sys.exit(1)

    days = _trading_days(from_date, to_date)
    total_days = len(days)
    log.info(f"Range {from_date} → {to_date} | {total_days} trading days | "
             f"underlyings={underlyings} | strikes=ATM±{args.strikes} | "
             f"expiries/day={args.expiries}")

    # Estimate: 2 underlyings × 3 expiries × 31 strikes × 2 types = 372 API calls/day
    # + 2 spot calls/day → ~374/day ÷ 3 rps ≈ 125 sec/day
    est_min = round(total_days * len(underlyings) * args.expiries * (args.strikes * 2 + 1) * 2 / _RPS_LIMIT / 60)
    log.info(f"Estimated time: ~{est_min} minutes (Angel One rate limit {_RPS_LIMIT} req/s)")

    smart = _login()
    scrip = fetch_scrip_master()
    log.info(f"Scrip master: {len(scrip):,} instruments")
    storage.init_db()

    grand_opt = 0
    for und in underlyings:
        spot_tok = INDEX_SPOT_TOKENS.get(und)
        if not spot_tok:
            log.error(f"No spot token for {und} — skipping")
            continue

        existing_opt   = _existing_opt_dates(und) if not args.refetch else set()
        existing_spot  = _existing_spot_dates(und) if not args.refetch else set()
        todo = [d for d in days if d not in existing_opt]

        log.info(f"\n{'='*50}")
        log.info(f"{und}: {len(todo)}/{total_days} days to fetch "
                 f"(skipping {total_days - len(todo)} already in DB)")

        und_opt = 0
        for i, day in enumerate(todo, 1):
            fetch_spot = (day not in existing_spot)
            log.info(f"  [{i:3}/{len(todo)}] {und} {day} "
                     f"{'(spot+options)' if fetch_spot else '(options only)'}")
            st = _backfill_day(smart, scrip, day, und, args.strikes, spot_tok, fetch_spot)
            und_opt += st["opt"]
            log.info(f"    → {st['opt']} opt rows | {st['spot']} spot rows | {st['tokens']} tokens")

        log.info(f"{und} complete: {und_opt:,} option rows")
        grand_opt += und_opt

    log.info(f"\nDone. Total option rows written: {grand_opt:,}")
    log.info("Run deduplication if you re-fetched existing days:")
    log.info("  .venv/bin/python -c \"from src.data import storage; print(storage.dedupe_options())\"")


if __name__ == "__main__":
    main()

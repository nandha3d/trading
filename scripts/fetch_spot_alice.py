#!/usr/bin/env python3
"""
Fetch NIFTY + BANKNIFTY 1-min spot data from Alice Blue (pya3) → write to spot_1m.

Alice Blue pya3 provides 1-min historical data for NSE indices up to ~100 days.
Requires ALICE_USER_ID and ALICE_API_KEY in .env.

Usage:
    cd /opt/trading
    .venv/bin/python scripts/fetch_spot_alice.py                        # last 60 days
    .venv/bin/python scripts/fetch_spot_alice.py --from 2026-04-01 --to 2026-06-17
    .venv/bin/python scripts/fetch_spot_alice.py --interval 5           # 5-min bars
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings

if not settings.alice_ready:
    sys.exit("Alice Blue credentials missing. Set ALICE_USER_ID and ALICE_API_KEY in .env")

try:
    from pya3 import Aliceblue
except ImportError:
    sys.exit("pya3 not installed. Run: pip install pya3")

import polars as pl
from src.data import storage

IST = ZoneInfo("Asia/Kolkata")

# pya3 symbol names for NSE index spot
INDEX_SYMBOLS = {
    "NIFTY":     ("NSE", "Nifty 50"),
    "BANKNIFTY": ("NSE", "Nifty Bank"),
}

MARKET_OPEN  = 9 * 60 + 15   # 09:15
MARKET_CLOSE = 15 * 60 + 30  # 15:30


def _login() -> Aliceblue:
    alice = Aliceblue(
        user_id=settings.alice_user_id,
        api_key=settings.alice_api_key,
        disable_ssl=False,
    )
    sid = alice.get_session_id()
    ok = bool(sid and (sid.get("sessionID") if isinstance(sid, dict) else sid))
    if not ok:
        sys.exit(f"Alice Blue login failed: {sid}")
    print(f"Alice Blue login OK ({settings.alice_user_id})")
    return alice


def _trading_days(from_d: date, to_d: date) -> list[date]:
    out, d = [], from_d
    while d <= to_d:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _fetch_spot_day(alice: Aliceblue, underlying: str, day: date, interval: str) -> pl.DataFrame:
    exch, sym = INDEX_SYMBOLS[underlying]
    inst = alice.get_instrument_by_symbol(exch, sym)
    if inst is None:
        print(f"  [warn] instrument not found: {exch}:{sym}")
        return pl.DataFrame()

    try:
        data = alice.get_historical_data(
            instrument=inst,
            from_datetime=datetime(day.year, day.month, day.day, 9, 15),
            to_datetime=datetime(day.year, day.month, day.day, 15, 30),
            interval=interval,
        )
    except Exception as e:
        print(f"  [warn] {underlying} {day}: {e}")
        return pl.DataFrame()

    if not data or not isinstance(data, list) or len(data) == 0:
        return pl.DataFrame()

    rows = []
    for bar in data:
        try:
            # pya3 returns list of [timestamp, open, high, low, close, volume]
            # or dict with keys
            if isinstance(bar, (list, tuple)) and len(bar) >= 5:
                ts_raw, o, h, l, c = bar[0], bar[1], bar[2], bar[3], bar[4]
                vol = int(bar[5]) if len(bar) > 5 else 0
            elif isinstance(bar, dict):
                ts_raw = bar.get("time") or bar.get("timestamp") or bar.get("date")
                o = bar.get("open", 0); h = bar.get("high", 0)
                l = bar.get("low", 0);  c = bar.get("close", 0)
                vol = int(bar.get("volume", 0) or 0)
            else:
                continue

            # Parse timestamp
            if isinstance(ts_raw, datetime):
                ts = ts_raw.replace(tzinfo=None)
            elif isinstance(ts_raw, str):
                for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%b-%Y %H:%M:%S"):
                    try:
                        ts = datetime.strptime(ts_raw[:19], fmt)
                        break
                    except ValueError:
                        continue
                else:
                    continue
            else:
                continue

            # Filter market hours
            t_min = ts.hour * 60 + ts.minute
            if t_min < MARKET_OPEN or t_min > MARKET_CLOSE:
                continue

            c = float(c)
            if c <= 0:
                continue

            rows.append({
                "underlying": underlying,
                "ts": ts,
                "open": float(o), "high": float(h), "low": float(l), "close": c,
                "volume": vol,
            })
        except Exception:
            continue

    if not rows:
        return pl.DataFrame()

    return pl.DataFrame(rows).with_columns([
        pl.col("underlying").cast(pl.Utf8),
        pl.col("ts").cast(pl.Datetime("us")),
        pl.col("open").cast(pl.Float32),
        pl.col("high").cast(pl.Float32),
        pl.col("low").cast(pl.Float32),
        pl.col("close").cast(pl.Float32),
        pl.col("volume").cast(pl.Int32),
    ])


def main():
    p = argparse.ArgumentParser(description="Fetch spot data from Alice Blue pya3")
    p.add_argument("--from", dest="from_date", default=None, metavar="YYYY-MM-DD")
    p.add_argument("--to",   dest="to_date",   default=None, metavar="YYYY-MM-DD")
    p.add_argument("--interval", default="1", choices=["1", "3", "5", "10", "15", "30", "60"],
                   help="Bar interval in minutes (default: 1)")
    p.add_argument("--underlyings", default="NIFTY,BANKNIFTY")
    args = p.parse_args()

    to_d   = date.fromisoformat(args.to_date)   if args.to_date   else date.today()
    from_d = date.fromisoformat(args.from_date) if args.from_date else to_d - timedelta(days=60)

    underlyings = [u.strip().upper() for u in args.underlyings.split(",")]
    days = _trading_days(from_d, to_d)

    print(f"Range {from_d} → {to_d} | {len(days)} trading days | interval={args.interval}m")

    storage.init_db()
    alice = _login()

    total = 0
    for und in underlyings:
        if und not in INDEX_SYMBOLS:
            print(f"[skip] {und} not supported")
            continue
        und_rows = 0
        for i, day in enumerate(days, 1):
            df = _fetch_spot_day(alice, und, day, args.interval)
            if not df.is_empty():
                n = storage.write_spot(df)
                und_rows += n
                print(f"  [{i}/{len(days)}] {und} {day}: {len(df)} bars → {n} written")
            else:
                print(f"  [{i}/{len(days)}] {und} {day}: no data")
            time.sleep(0.2)  # gentle rate limiting
        print(f"  {und} total: {und_rows} rows")
        total += und_rows

    print(f"\nDone. Total spot rows written: {total}")


if __name__ == "__main__":
    main()

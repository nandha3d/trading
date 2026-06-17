#!/usr/bin/env python3
"""
Fetch NIFTY + BANKNIFTY spot 1-min data from Yahoo Finance and write to spot_1m.

Yahoo Finance limits:
  interval=1m  -> last 7 days only
  interval=2m  -> last 60 days
  interval=5m  -> last 60 days

We use 2m, resample down to 1m-equivalent timestamps (each row stored as-is).
For oldest data (>60 days) you'd need a different source.

Usage:
    cd /opt/trading
    .venv/bin/python scripts/fetch_spot_yahoo.py                      # last 30 days
    .venv/bin/python scripts/fetch_spot_yahoo.py --from 2026-06-02 --to 2026-06-17
    .venv/bin/python scripts/fetch_spot_yahoo.py --interval 5m        # 5-min bars (60d max)
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import yfinance as yf
except ImportError:
    sys.exit("yfinance not installed. Run: pip install yfinance")

import polars as pl

from src.data import storage

IST = ZoneInfo("Asia/Kolkata")

SYMBOLS = {
    "NIFTY":     "^NSEI",
    "BANKNIFTY": "^NSEBANK",
}

MARKET_OPEN  = (9, 15)
MARKET_CLOSE = (15, 30)


def _trading_days(from_d: date, to_d: date) -> list[date]:
    out, d = [], from_d
    while d <= to_d:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def fetch_spot(underlying: str, from_d: date, to_d: date, interval: str = "2m") -> pl.DataFrame:
    sym = SYMBOLS[underlying]
    # yfinance end date is exclusive
    end_str = (to_d + timedelta(days=1)).isoformat()
    print(f"  Downloading {underlying} ({sym}) {from_d} → {to_d} interval={interval}…")
    try:
        raw = yf.download(
            sym,
            start=from_d.isoformat(),
            end=end_str,
            interval=interval,
            progress=False,
            auto_adjust=True,
        )
    except Exception as e:
        print(f"  [warn] yfinance download failed: {e}")
        return pl.DataFrame()

    if raw is None or raw.empty:
        print(f"  [warn] No data returned for {underlying}")
        return pl.DataFrame()

    raw = raw.reset_index()
    # Column name may be "Datetime" or "Date"
    ts_col = "Datetime" if "Datetime" in raw.columns else "Date"

    rows = []
    for _, row in raw.iterrows():
        ts_raw = row[ts_col]
        # Convert to IST naive datetime
        try:
            if hasattr(ts_raw, "tzinfo") and ts_raw.tzinfo is not None:
                ts_ist = ts_raw.astimezone(IST).replace(tzinfo=None)
            else:
                ts_ist = ts_raw.to_pydatetime().replace(tzinfo=None)
        except Exception:
            continue

        # Filter to market hours only
        h, m = ts_ist.hour, ts_ist.minute
        t_min = h * 60 + m
        if t_min < MARKET_OPEN[0] * 60 + MARKET_OPEN[1]:
            continue
        if t_min > MARKET_CLOSE[0] * 60 + MARKET_CLOSE[1]:
            continue

        # Skip weekends (shouldn't happen but just in case)
        if ts_ist.weekday() >= 5:
            continue

        try:
            # Handle MultiIndex columns from yfinance
            def _get(col: str) -> float:
                v = row[col] if col in raw.columns else row.get((col, sym), 0)
                return float(v) if v is not None and str(v) != "nan" else 0.0

            o = _get("Open"); h_ = _get("High"); l = _get("Low"); c = _get("Close")
            vol = int(_get("Volume"))
        except Exception:
            continue

        if c <= 0:
            continue

        rows.append({
            "underlying": underlying,
            "ts": ts_ist,
            "open": o, "high": h_, "low": l, "close": c,
            "volume": vol,
        })

    if not rows:
        print(f"  [warn] 0 valid rows after filtering for {underlying}")
        return pl.DataFrame()

    df = pl.DataFrame(rows).with_columns([
        pl.col("underlying").cast(pl.Utf8),
        pl.col("ts").cast(pl.Datetime("us")),
        pl.col("open").cast(pl.Float32),
        pl.col("high").cast(pl.Float32),
        pl.col("low").cast(pl.Float32),
        pl.col("close").cast(pl.Float32),
        pl.col("volume").cast(pl.Int32),
    ])
    print(f"  {underlying}: {len(df)} rows fetched")
    return df


def main():
    p = argparse.ArgumentParser(description="Fetch spot 1-min data from Yahoo Finance")
    p.add_argument("--from", dest="from_date", default=None, metavar="YYYY-MM-DD")
    p.add_argument("--to",   dest="to_date",   default=None, metavar="YYYY-MM-DD")
    p.add_argument("--interval", default="2m", choices=["1m", "2m", "5m"],
                   help="Bar interval (1m=7d max, 2m/5m=60d max)")
    p.add_argument("--underlyings", default="NIFTY,BANKNIFTY")
    args = p.parse_args()

    to_d   = date.fromisoformat(args.to_date)   if args.to_date   else date.today()
    from_d = date.fromisoformat(args.from_date) if args.from_date else to_d - timedelta(days=30)

    # Warn if range exceeds Yahoo Finance limits
    days_back = (date.today() - from_d).days
    if args.interval == "1m" and days_back > 7:
        print(f"[warn] interval=1m supports only last 7 days; from={from_d} is {days_back}d ago. Use --interval 2m or 5m.")
    if args.interval in ("2m", "5m") and days_back > 60:
        print(f"[warn] interval={args.interval} supports only last 60 days; from={from_d} is {days_back}d ago.")

    underlyings = [u.strip().upper() for u in args.underlyings.split(",")]

    storage.init_db()

    total = 0
    for und in underlyings:
        if und not in SYMBOLS:
            print(f"[skip] unknown underlying {und}")
            continue
        df = fetch_spot(und, from_d, to_d, args.interval)
        if df.is_empty():
            continue
        n = storage.write_spot(df)
        print(f"  → {n} rows written to spot_1m for {und}")
        total += n

    print(f"\nDone. Total spot rows written: {total}")


if __name__ == "__main__":
    main()

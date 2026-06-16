"""Pull recent 1-minute INDEX SPOT candles from Yahoo Finance into spot_1m.

Free, no key. Yahoo serves 1-minute data only for roughly the last ~5-7
trading days (hard API cap), so this keeps the spot tables current week to week.
It does NOT provide options/OI (not available free at 1-minute granularity).

Usage:
    py -m src.data.yahoo_loader            # NIFTY + BANKNIFTY, last 5d
    py -m src.data.yahoo_loader --range 7d

Writes are idempotent: existing spot rows in the pulled time-range are deleted
for that underlying before insert, so re-running won't duplicate.
"""
from __future__ import annotations

import argparse
from datetime import datetime, time

import polars as pl
import requests

from . import storage

# Yahoo index tickers -> our underlying code
TICKERS = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}
SESSION_START = time(9, 15)
SESSION_END = time(15, 30)
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def fetch_yahoo_1m(ticker: str, rng: str = "5d") -> pl.DataFrame:
    """Fetch 1-minute candles. Returns DataFrame[ts, open, high, low, close, volume]
    with ts as naive IST datetimes (matching the rest of spot_1m)."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    r = requests.get(url, headers=_HEADERS, params={"range": rng, "interval": "1m"}, timeout=15)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res["timestamp"]
    gmt = res["meta"].get("gmtoffset", 19800)  # IST = +5:30
    q = res["indicators"]["quote"][0]
    rows = []
    for i, epoch in enumerate(ts):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c):
            continue
        # epoch is UTC; add exchange gmtoffset -> naive local (IST) clock time
        dt = datetime.utcfromtimestamp(epoch + gmt)
        if not (SESSION_START <= dt.time() <= SESSION_END):
            continue
        rows.append({
            "ts": dt.replace(second=0, microsecond=0),
            "open": float(o), "high": float(h), "low": float(l), "close": float(c),
            "volume": int(q["volume"][i] or 0),
        })
    return pl.DataFrame(rows) if rows else pl.DataFrame(
        schema={"ts": pl.Datetime, "open": pl.Float64, "high": pl.Float64,
                "low": pl.Float64, "close": pl.Float64, "volume": pl.Int64})


def _delete_range(underlying: str, t0: datetime, t1: datetime) -> int:
    con = storage.db()
    n = con.execute(
        "SELECT count(*) FROM spot_1m WHERE underlying=? AND ts>=? AND ts<=?",
        [underlying, t0, t1]).fetchone()[0]
    con.execute("DELETE FROM spot_1m WHERE underlying=? AND ts>=? AND ts<=?",
                [underlying, t0, t1])
    return n


def load(underlyings: list[str] | None = None, rng: str = "5d") -> None:
    storage.init_db()
    for u in (underlyings or list(TICKERS)):
        tk = TICKERS.get(u.upper())
        if not tk:
            print(f"[skip] no Yahoo ticker for {u}")
            continue
        df = fetch_yahoo_1m(tk, rng)
        if df.is_empty():
            print(f"[{u}] no bars returned")
            continue
        df = df.with_columns(pl.lit(u.upper()).alias("underlying"))
        t0, t1 = df["ts"].min(), df["ts"].max()
        removed = _delete_range(u.upper(), t0, t1)
        written = storage.write_spot(df)
        print(f"[{u}] {written:,} bars  {t0}  ->  {t1}  (replaced {removed:,})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--range", default="5d", help="Yahoo range (1d/5d/7d; 1m capped ~7d)")
    ap.add_argument("--underlyings", nargs="*", default=None)
    a = ap.parse_args()
    load(a.underlyings, a.range)


if __name__ == "__main__":
    main()

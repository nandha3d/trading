"""
Upstox 1-min historical backfill — NIFTY + BANKNIFTY options + spot index.

Upstox is the ONLY retail broker that serves 1-min candles (with OI) for EXPIRED
F&O contracts. Run this once to fill the gap not covered by Kaggle data.

Prerequisites
-------------
  Valid Upstox token in data/.upstox_session.json
  Either:  python scripts/upstox_oauth.py
      or:  visit https://trade.animazon.in/api/oauth/upstox

Usage
-----
  python scripts/backfill_upstox.py              # last 60 trading days
  python scripts/backfill_upstox.py --days 30
  python scripts/backfill_upstox.py --from 2026-04-01 --to 2026-06-13
  python scripts/backfill_upstox.py --dry-run    # count instruments, no API calls

Resume
------
  Progress is saved to data/backfill_upstox_done.json after each successful write.
  Re-running the script skips already-completed instrument+chunk combos.

Scale (rough)
-------------
  ~60 days, NIFTY+BANKNIFTY all strikes: ~3 000-6 000 instruments × 2 chunks
  At 5 req/s = 20-40 minutes. Safe to run overnight.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import polars as pl
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.data import storage  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MASTER_URL   = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
HIST_URL     = "https://api.upstox.com/v2/historical-candle/{key}/{interval}/{to}/{frm}"
SESSION_FILE = Path("data/.upstox_session.json")
DONE_FILE    = Path("data/backfill_upstox_done.json")

RATE_PER_SEC = 5          # conservative; Upstox allows higher but be safe
CHUNK_DAYS   = 30         # Upstox 1-min limit per request
HEADERS_BASE = {"accept": "application/json"}

SPOT_KEYS = {
    "NIFTY":     "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
}

# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------

def _token() -> str:
    if not SESSION_FILE.exists():
        sys.exit("No Upstox token. Run: python scripts/upstox_oauth.py")
    try:
        return json.loads(SESSION_FILE.read_text())["access_token"]
    except Exception as e:
        sys.exit(f"Bad session file: {e}")


# ---------------------------------------------------------------------------
# Instrument master
# ---------------------------------------------------------------------------

def _download_master() -> list[dict]:
    print("[master] Downloading Upstox instrument master...", flush=True)
    r = requests.get(MASTER_URL, timeout=60)
    r.raise_for_status()
    raw = gzip.decompress(r.content).decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(raw)))
    print(f"[master] {len(rows):,} total instruments", flush=True)
    return rows


def _filter_options(rows: list[dict], start: date, end: date) -> list[dict]:
    """Keep NIFTY/BANKNIFTY option strikes with expiry in [start, end]."""
    out = []
    for r in rows:
        # Upstox master columns may vary; try both known layouts
        name = (r.get("name") or "").strip().upper()
        # Some Upstox master versions prefix name; strip index suffix
        if name not in ("NIFTY", "BANKNIFTY"):
            ts = (r.get("tradingsymbol") or "").strip().upper()
            if ts.startswith("BANKNIFTY"):
                name = "BANKNIFTY"
            elif ts.startswith("NIFTY"):
                name = "NIFTY"
            else:
                continue
        opt_type = (r.get("option_type") or r.get("instrument_type") or "").strip().upper()
        if opt_type not in ("CE", "PE"):
            continue
        # expiry: "2026-06-26" or "26-06-2026" or similar
        exp_raw = (r.get("expiry") or "").strip()
        try:
            exp = _parse_expiry(exp_raw)
        except ValueError:
            continue
        if exp < start:
            continue
        key = (r.get("instrument_key") or "").strip()
        if not key:
            continue
        strike_raw = r.get("strike") or r.get("strike_price") or "0"
        try:
            strike = int(float(strike_raw))
        except (ValueError, TypeError):
            continue
        out.append({
            "instrument_key": key,
            "underlying": name,
            "expiry": exp,
            "strike": strike,
            "option_type": opt_type,
        })
    return out


def _parse_expiry(s: str) -> date:
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Cannot parse expiry: {s!r}")


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _trading_days(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _date_chunks(start: date, end: date, chunk: int) -> list[tuple[date, date]]:
    chunks, cur = [], start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=chunk - 1), end)
        chunks.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return chunks


# ---------------------------------------------------------------------------
# Progress tracking
# ---------------------------------------------------------------------------

def _load_done() -> set[str]:
    if DONE_FILE.exists():
        try:
            return set(json.loads(DONE_FILE.read_text()))
        except Exception:
            pass
    return set()


def _save_done(done: set[str]) -> None:
    DONE_FILE.parent.mkdir(parents=True, exist_ok=True)
    DONE_FILE.write_text(json.dumps(sorted(done)))


# ---------------------------------------------------------------------------
# Candle fetch + parse
# ---------------------------------------------------------------------------

_last_call = 0.0


def _rate_gate() -> None:
    global _last_call
    gap = 1.0 / RATE_PER_SEC
    wait = gap - (time.time() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.time()


def _fetch_candles(token: str, key: str, frm: date, to: date,
                   retries: int = 4) -> list[list]:
    """Return raw candle arrays [[ts,o,h,l,c,v,oi], ...] or []."""
    url = HIST_URL.format(
        key=quote(key, safe=""),
        interval="1minute",
        to=to.isoformat(),
        frm=frm.isoformat(),
    )
    hdrs = {**HEADERS_BASE, "Authorization": f"Bearer {token}"}
    delay = 2.0
    for attempt in range(retries):
        _rate_gate()
        try:
            r = requests.get(url, headers=hdrs, timeout=20)
        except requests.RequestException as e:
            if attempt < retries - 1:
                time.sleep(delay); delay *= 2
                continue
            print(f"    [net error] {e}")
            return []

        if r.status_code == 200:
            body = r.json()
            return body.get("data", {}).get("candles", [])

        if r.status_code == 401:
            sys.exit("\n[ERROR] Upstox token expired. Re-run: python scripts/upstox_oauth.py")

        if r.status_code == 429:
            wait = delay * (attempt + 1)
            print(f"    [429] rate-limited, sleeping {wait:.1f}s")
            time.sleep(wait); delay *= 2
            continue

        if r.status_code == 400:
            # No data for this instrument/period (e.g. weekend, holiday, no trades)
            return []

        print(f"    [HTTP {r.status_code}] {r.text[:120]}")
        if attempt < retries - 1:
            time.sleep(delay); delay *= 2

    return []


def _parse_ts(s: str) -> datetime:
    """'2026-06-13T09:15:00+05:30' -> naive IST datetime."""
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")


def _candles_to_options_df(
    candles: list[list],
    underlying: str,
    expiry: date,
    strike: int,
    opt_type: str,
) -> pl.DataFrame:
    if not candles:
        return pl.DataFrame()
    rows = []
    for c in candles:
        if len(c) < 6:
            continue
        ts = _parse_ts(c[0])
        rows.append({
            "underlying":  underlying,
            "expiry":      expiry,
            "strike":      strike,
            "option_type": opt_type,
            "ts":          ts,
            "open":        float(c[1] or 0),
            "high":        float(c[2] or 0),
            "low":         float(c[3] or 0),
            "close":       float(c[4] or 0),
            "volume":      int(c[5] or 0),
            "oi":          int(c[6]) if len(c) > 6 and c[6] else 0,
        })
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame(rows).with_columns([
        pl.col("underlying").cast(pl.Utf8),
        pl.col("expiry").cast(pl.Date),
        pl.col("strike").cast(pl.Int32),
        pl.col("option_type").cast(pl.Utf8),
        pl.col("ts").cast(pl.Datetime("us")),
        pl.col("open").cast(pl.Float64),
        pl.col("high").cast(pl.Float64),
        pl.col("low").cast(pl.Float64),
        pl.col("close").cast(pl.Float64),
        pl.col("volume").cast(pl.Int64),
        pl.col("oi").cast(pl.Int64),
    ])


def _candles_to_spot_df(
    candles: list[list],
    underlying: str,
) -> pl.DataFrame:
    if not candles:
        return pl.DataFrame()
    rows = []
    for c in candles:
        if len(c) < 5:
            continue
        rows.append({
            "underlying": underlying,
            "ts":         _parse_ts(c[0]),
            "open":       float(c[1] or 0),
            "high":       float(c[2] or 0),
            "low":        float(c[3] or 0),
            "close":      float(c[4] or 0),
            "volume":     int(c[5]) if len(c) > 5 and c[5] else 0,
        })
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame(rows).with_columns([
        pl.col("underlying").cast(pl.Utf8),
        pl.col("ts").cast(pl.Datetime("us")),
        pl.col("open").cast(pl.Float64),
        pl.col("high").cast(pl.Float64),
        pl.col("low").cast(pl.Float64),
        pl.col("close").cast(pl.Float64),
        pl.col("volume").cast(pl.Int64),
    ])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Upstox historical F&O + spot backfill")
    p.add_argument("--days",    type=int, default=60,
                   help="Number of calendar days to backfill (default 60)")
    p.add_argument("--from",    dest="from_date",
                   help="Start date YYYY-MM-DD (overrides --days)")
    p.add_argument("--to",      dest="to_date",
                   help="End date YYYY-MM-DD (default today)")
    p.add_argument("--dry-run", action="store_true",
                   help="Show instrument count and exit without fetching")
    p.add_argument("--reset",   action="store_true",
                   help="Ignore saved progress and restart from scratch")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    end   = date.fromisoformat(args.to_date)   if args.to_date   else date.today()
    start = date.fromisoformat(args.from_date) if args.from_date else (end - timedelta(days=args.days))

    print(f"[backfill] date range: {start} → {end}", flush=True)

    token     = _token()
    master    = _download_master()
    options   = _filter_options(master, start, end)
    print(f"[backfill] {len(options):,} option instruments to backfill", flush=True)

    if args.dry_run:
        print("[backfill] --dry-run: exiting without API calls")
        return

    storage.init_db()
    done     = set() if args.reset else _load_done()
    chunks   = _date_chunks(start, end, CHUNK_DAYS)
    total    = len(options) * len(chunks)
    n_done   = 0
    n_rows   = 0

    print(f"[backfill] {len(chunks)} date chunk(s) × {len(options):,} instruments = "
          f"{total:,} API calls  ({total / RATE_PER_SEC / 60:.0f} min estimated)",
          flush=True)
    if done:
        print(f"[backfill] resuming — {len(done)} chunks already completed", flush=True)

    # ---- options ----
    for i, inst in enumerate(options):
        key       = inst["instrument_key"]
        und       = inst["underlying"]
        exp       = inst["expiry"]
        strike    = inst["strike"]
        opt_type  = inst["option_type"]

        for frm, to in chunks:
            done_key = f"{key}|{frm}|{to}"
            if done_key in done:
                n_done += 1
                continue

            candles = _fetch_candles(token, key, frm, to)
            if candles:
                df = _candles_to_options_df(candles, und, exp, strike, opt_type)
                if not df.is_empty():
                    rows = storage.write_options(df)
                    n_rows += rows

            done.add(done_key)
            n_done += 1

            if n_done % 100 == 0:
                pct = n_done / total * 100
                print(f"[backfill] {n_done:,}/{total:,} ({pct:.1f}%) — "
                      f"{n_rows:,} rows written", flush=True)
                _save_done(done)

    # ---- spot index ----
    print("[backfill] Fetching spot index candles...", flush=True)
    for und, spot_key in SPOT_KEYS.items():
        for frm, to in chunks:
            done_key = f"SPOT_{und}|{frm}|{to}"
            if done_key in done:
                continue
            candles = _fetch_candles(token, spot_key, frm, to)
            if candles:
                df = _candles_to_spot_df(candles, und)
                if not df.is_empty():
                    storage.write_spot(df)
            done.add(done_key)

    _save_done(done)
    storage.dedupe_options()
    print(f"\n[backfill] DONE — {n_rows:,} option rows written total", flush=True)


if __name__ == "__main__":
    main()

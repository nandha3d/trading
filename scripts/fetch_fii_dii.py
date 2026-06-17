#!/usr/bin/env python3
"""
Fetch NSE participant-wise F&O OI data (FII, DII, Pro, Client) and store in DuckDB.
NSE publishes this daily after market close.

File: https://archives.nseindia.com/content/nsccl/fao_participant_oi_DDMMYYYY.csv

Usage:
    cd /opt/trading
    .venv/bin/python scripts/fetch_fii_dii.py              # today
    .venv/bin/python scripts/fetch_fii_dii.py --from 2026-03-01 --to 2026-06-17
    .venv/bin/python scripts/fetch_fii_dii.py --date 2026-06-16

Run via cron after 18:00 IST:
    0 18 * * 1-5 cd /opt/trading && .venv/bin/python scripts/fetch_fii_dii.py >> logs/fii_dii.log 2>&1
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, timedelta
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("fii_dii")

try:
    import requests
except ImportError:
    log.error("pip install requests")
    sys.exit(1)

from src.data import storage

NSE_URL = "https://archives.nseindia.com/content/nsccl/fao_participant_oi_{date}.csv"
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.nseindia.com/",
}

# NSE CSV client type labels → our canonical names
CLIENT_MAP = {
    "FII": "FII", "FPI": "FII",       # FII / FPI both map to FII
    "DII": "DII",
    "PRO": "Pro", "PROP": "Pro",       # Proprietary
    "CLIENT": "Client",
}

# Column name variants used by NSE (they change occasionally)
_COL_ALIASES = {
    "fut_idx_long":   ["Future Index Long", "Fut Index Long", "FUT INDEX LONG"],
    "fut_idx_short":  ["Future Index Short", "Fut Index Short", "FUT INDEX SHORT"],
    "opt_call_long":  ["Option Index Call Long", "OPT INDEX CALL LONG", "Index Call Long"],
    "opt_call_short": ["Option Index Call Short", "OPT INDEX CALL SHORT", "Index Call Short"],
    "opt_put_long":   ["Option Index Put Long", "OPT INDEX PUT LONG", "Index Put Long"],
    "opt_put_short":  ["Option Index Put Short", "OPT INDEX PUT SHORT", "Index Put Short"],
}


def _to_int(val: str) -> int | None:
    try:
        return int(str(val).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _find_col(header: list[str], aliases: list[str]) -> int | None:
    h = [c.strip().upper() for c in header]
    for a in aliases:
        try:
            return h.index(a.upper())
        except ValueError:
            continue
    return None


def _fetch_day(d: date) -> list[dict]:
    url = NSE_URL.format(date=d.strftime("%d%m%Y"))
    try:
        r = requests.get(url, headers=NSE_HEADERS, timeout=15)
        if r.status_code == 404:
            log.debug(f"  {d}: 404 (holiday or not published yet)")
            return []
        r.raise_for_status()
    except requests.RequestException as e:
        log.warning(f"  {d}: fetch failed — {e}")
        return []

    lines = r.text.strip().splitlines()
    if len(lines) < 2:
        return []

    # Find header line (first line with "Client Type" or similar)
    header_idx = 0
    for i, line in enumerate(lines):
        if "client" in line.lower() or "type" in line.lower():
            header_idx = i
            break

    header = lines[header_idx].split(",")
    col_idxs = {k: _find_col(header, aliases) for k, aliases in _COL_ALIASES.items()}

    # Find client_type column
    ct_idx = None
    for i, h in enumerate(header):
        if "client" in h.lower() or "type" in h.lower():
            ct_idx = i
            break
    if ct_idx is None:
        ct_idx = 0

    rows = []
    for line in lines[header_idx + 1:]:
        parts = line.split(",")
        if len(parts) < 3:
            continue
        raw_ct = parts[ct_idx].strip().upper()
        ct = CLIENT_MAP.get(raw_ct)
        if not ct:
            continue
        row = {"date": d, "client_type": ct}
        for field, idx in col_idxs.items():
            row[field] = _to_int(parts[idx]) if idx is not None and idx < len(parts) else None
        rows.append(row)

    return rows


def _trading_days(from_d: date, to_d: date) -> list[date]:
    out, d = [], from_d
    while d <= to_d:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def main():
    parser = argparse.ArgumentParser(description="Fetch NSE FII/DII participant F&O data")
    parser.add_argument("--date", help="Single date YYYY-MM-DD")
    parser.add_argument("--from", dest="from_date", help="Range start YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", help="Range end YYYY-MM-DD")
    args = parser.parse_args()

    storage.init_db()

    if args.date:
        days = [date.fromisoformat(args.date)]
    elif args.from_date:
        from_d = date.fromisoformat(args.from_date)
        to_d = date.fromisoformat(args.to_date) if args.to_date else date.today()
        days = _trading_days(from_d, to_d)
    else:
        days = [date.today()]

    total = 0
    for d in days:
        rows = _fetch_day(d)
        if rows:
            n = storage.write_fii_dii(rows)
            log.info(f"  {d}: {n} rows written ({len(rows)} parsed)")
            total += n
        else:
            log.info(f"  {d}: no data")
        time.sleep(0.5)

    log.info(f"Done. Total rows written: {total}")


if __name__ == "__main__":
    main()

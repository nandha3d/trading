"""
Download NSE F&O + Index bhav copy → insert EOD snapshot into DB.

NSE publishes bhav after ~17:00 IST. Safe to run from 16:30 IST onward.
Free, no auth. Gives EOD close + OI for all NIFTY/BANKNIFTY option strikes.

Usage:
  python scripts/fetch_eod_bhav.py              # today or last trading day
  python scripts/fetch_eod_bhav.py 2024-12-20   # specific date
  python scripts/fetch_eod_bhav.py --dry-run    # parse only, no DB writes
"""
from __future__ import annotations

import csv
import io
import sys
import zipfile
from datetime import date, datetime, timedelta, time as dtime
from pathlib import Path

import polars as pl
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data import storage  # noqa: E402

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
}
UDIFF_CUTOVER = date(2024, 7, 8)
MONTHS = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
EOD_TIME = dtime(15, 29, 0)


def last_trading_day(ref: date) -> date:
    d = ref
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def fo_bhav_url(d: date) -> str:
    if d >= UDIFF_CUTOVER:
        return (f"https://archives.nseindia.com/content/fo/"
                f"BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip")
    m = MONTHS[d.month - 1]
    return (f"https://archives.nseindia.com/content/historical/DERIVATIVES/"
            f"{d.year}/{m}/fo{d.day:02d}{m}{d.year}bhav.csv.zip")


def index_bhav_url(d: date) -> str:
    return (f"https://archives.nseindia.com/content/indices/"
            f"ind_close_all_{d.day:02d}{MONTHS[d.month - 1]}{d.year}.csv")


def fetch(url: str) -> bytes | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            print(f"  HTTP {r.status_code}: {url}")
            return None
        return r.content
    except Exception as e:
        print(f"  fetch error: {e}")
        return None


def _float(v) -> float:
    try:
        return float(v or 0)
    except (ValueError, TypeError):
        return 0.0


def _int(v) -> int:
    try:
        return int(float(v or 0))
    except (ValueError, TypeError):
        return 0


def parse_fo_bhav(content: bytes, d: date, ts: datetime) -> pl.DataFrame:
    z = zipfile.ZipFile(io.BytesIO(content))
    text = z.read(z.namelist()[0]).decode("utf-8", "ignore").splitlines()
    rows = []
    udiff = d >= UDIFF_CUTOVER

    for row in csv.DictReader(text):
        row = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}

        if udiff:
            sym = row.get("TckrSymb", "")
            otp = row.get("OptnTp", "")
            if otp not in ("CE", "PE") or sym not in ("NIFTY", "BANKNIFTY"):
                continue
            try:
                exp = datetime.strptime(row.get("XpryDt", ""), "%Y-%m-%d").date()
            except ValueError:
                continue
            strike = _int(row.get("StrkPric"))
            close  = _float(row.get("ClsPric"))
            open_  = _float(row.get("OpnPric")) or close
            high   = _float(row.get("HghPric")) or close
            low    = _float(row.get("LwPric"))  or close
            vol    = _int(row.get("TtlTradgVol"))
            oi     = _int(row.get("OpnIntrst"))
        else:
            if row.get("INSTRUMENT", "") != "OPTIDX":
                continue
            sym = row.get("SYMBOL", "")
            if sym not in ("NIFTY", "BANKNIFTY"):
                continue
            otp = row.get("OPTION_TYP", "")
            if otp not in ("CE", "PE"):
                continue
            try:
                exp = datetime.strptime(row.get("EXPIRY_DT", ""), "%d-%b-%Y").date()
            except ValueError:
                continue
            strike = _int(row.get("STRIKE_PR"))
            close  = _float(row.get("CLOSE"))
            open_  = _float(row.get("OPEN"))  or close
            high   = _float(row.get("HIGH"))  or close
            low    = _float(row.get("LOW"))   or close
            vol    = _int(row.get("CONTRACTS"))
            oi     = _int(row.get("OPEN_INT"))

        if close <= 0:
            continue

        rows.append({
            "underlying":  sym,
            "expiry":      exp,
            "strike":      strike,
            "option_type": otp,
            "ts":          ts,
            "open":        open_,
            "high":        high,
            "low":         low,
            "close":       close,
            "volume":      vol,
            "oi":          oi,
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


def parse_index_bhav(content: bytes, ts: datetime) -> pl.DataFrame:
    TARGET = {"Nifty 50": "NIFTY", "Nifty Bank": "BANKNIFTY"}
    rows = []
    for row in csv.DictReader(content.decode("utf-8", "ignore").splitlines()):
        row = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
        name = row.get("Index Name", "").strip()
        if name not in TARGET:
            continue
        close = _float(row.get("Closing") or row.get("Close"))
        if close <= 0:
            continue
        rows.append({
            "underlying": TARGET[name],
            "ts":         ts,
            "open":       _float(row.get("Open"))  or close,
            "high":       _float(row.get("High"))  or close,
            "low":        _float(row.get("Low"))   or close,
            "close":      close,
            "volume":     0,
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


def main():
    dry  = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    target = date.fromisoformat(args[0]) if args else last_trading_day(date.today())
    ts     = datetime.combine(target, EOD_TIME)

    print(f"[bhav] date={target}  ts={ts}  dry={dry}")

    # --- F&O options ---
    url = fo_bhav_url(target)
    print(f"[bhav] F&O  → {url}")
    content = fetch(url)

    if content and content[:2] == b"PK":
        opt_df = parse_fo_bhav(content, target, ts)
        print(f"[bhav] parsed {len(opt_df):,} option rows")
        if not dry and not opt_df.is_empty():
            storage.init_db()
            storage.db().execute(
                "DELETE FROM options_1m WHERE CAST(ts AS DATE)=? AND underlying IN ('NIFTY','BANKNIFTY')",
                [target],
            )
            n = storage.write_options(opt_df)
            print(f"[bhav] wrote {n:,} option rows")
    else:
        print("[bhav] F&O bhav not available (holiday / not published yet)")

    # --- Index spot ---
    url = index_bhav_url(target)
    print(f"[bhav] Spot → {url}")
    content = fetch(url)

    if content:
        spot_df = parse_index_bhav(content, ts)
        print(f"[bhav] parsed {len(spot_df)} spot rows")
        if not dry and not spot_df.is_empty():
            storage.db().execute(
                "DELETE FROM spot_1m WHERE CAST(ts AS DATE)=? AND underlying IN ('NIFTY','BANKNIFTY')",
                [target],
            )
            n = storage.write_spot(spot_df)
            print(f"[bhav] wrote {n} spot rows")
    else:
        print("[bhav] index bhav not available")

    print("[bhav] done")


if __name__ == "__main__":
    main()

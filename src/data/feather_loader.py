"""Load the existing per-day NFO option feather files into the Parquet lake.

Source: historical data/<X>_filtered_feather_folder/**/*-index-nfo-data.feather
Each file = one trading day, columns:
  date(tz-aware IST), open, high, low, close, volume, oi,
  symbol, name(=underlying), expiry(date), strike(float), instrument_type(CE/PE/FUT)

We drop FUT, map name->underlying / instrument_type->option_type, strip tz
(keep IST wall clock), and write via storage.write_options.
"""
from __future__ import annotations

import glob
from pathlib import Path

import pandas as pd
import polars as pl

from config import settings
from . import storage

# default source dir (relative to project root: "historical data")
DEFAULT_SRC = Path("historical data")

FOLDERS = {
    "NIFTY": "filtered_feather_folder",
    "BANKNIFTY": "BANK_filtered_feather_folder",
}

_OUT_COLS = [
    "underlying", "expiry", "strike", "option_type",
    "ts", "open", "high", "low", "close", "volume", "oi",
]


def _load_one(path: str) -> pl.DataFrame:
    pdf = pd.read_feather(path)
    pdf = pdf[pdf["instrument_type"].isin(["CE", "PE"])].copy()
    if pdf.empty:
        return pl.DataFrame()
    pdf = pdf.rename(columns={"name": "underlying", "instrument_type": "option_type"})
    # strip tz -> naive IST wall clock
    pdf["ts"] = pd.to_datetime(pdf["date"]).dt.tz_localize(None)
    pdf = pdf[_OUT_COLS]
    df = pl.from_pandas(pdf)
    return df.with_columns(
        pl.col("strike").cast(pl.Int32),
        pl.col("volume").cast(pl.Int64),
        pl.col("oi").cast(pl.Int64),
        pl.col("open").cast(pl.Float64),
        pl.col("high").cast(pl.Float64),
        pl.col("low").cast(pl.Float64),
        pl.col("close").cast(pl.Float64),
    )


def ingest(underlying: str, src: Path = DEFAULT_SRC, limit: int | None = None) -> int:
    """Ingest all feather days for one underlying. Returns rows written."""
    folder = FOLDERS.get(underlying.upper())
    if not folder:
        raise ValueError(f"unknown underlying {underlying}; have {list(FOLDERS)}")
    pattern = str(src / folder / "**" / "*.feather")
    files = sorted(glob.glob(pattern, recursive=True))
    if limit:
        files = files[:limit]
    if not files:
        raise FileNotFoundError(f"no feather files at {pattern}")
    settings.ensure_dirs()
    if not limit:  # full reload: clear existing rows for clean idempotent ingest
        removed = storage.clear_options(underlying.upper())
        if removed:
            print(f"  [{underlying}] cleared {removed:,} existing rows")
    total = 0
    for i, f in enumerate(files, 1):
        df = _load_one(f)
        if not df.is_empty():
            total += storage.write_options(df)
        if i % 100 == 0 or i == len(files):
            print(f"  [{underlying}] {i}/{len(files)} files, {total:,} rows")
    if not limit:  # finalize: drop duplicate keys from source overlaps
        dups = storage.dedupe_options(underlying.upper())
        if dups:
            print(f"  [{underlying}] deduped {dups:,} duplicate-key rows")
    return total

"""Free historical backfill from Kaggle (works today, no broker API needed).

Known useful datasets (NSE 1-min):
  debashis74017/nifty-50-minute-data                 -> NIFTY index 1-min spot
  debashis74017/stock-market-data-nifty-50-stocks-1-min-data
  rishi2628/bank-nifty-intraday-data                 -> BANKNIFTY spot
  (F&O 1-min option datasets exist too; map columns per dataset.)

Auth: set KAGGLE_USERNAME / KAGGLE_KEY in .env (or ~/.kaggle/kaggle.json).
"""
from __future__ import annotations

import os
from pathlib import Path

import polars as pl

from config import settings
from . import storage


def _auth() -> None:
    if settings.kaggle_username:
        os.environ.setdefault("KAGGLE_USERNAME", settings.kaggle_username)
    if settings.kaggle_key:
        os.environ.setdefault("KAGGLE_KEY", settings.kaggle_key)


def download(slug: str, dest: Path | None = None) -> Path:
    """Download + unzip a Kaggle dataset. Returns the folder with CSVs."""
    _auth()
    import kaggle  # imported late so missing creds don't break import

    dest = dest or (settings.data_dir / "kaggle" / slug.replace("/", "__"))
    dest.mkdir(parents=True, exist_ok=True)
    kaggle.api.dataset_download_files(slug, path=str(dest), unzip=True)
    return dest


# Map a raw Kaggle CSV to our SPOT schema. Override col names per dataset.
def load_spot_csv(
    csv_path: Path,
    underlying: str,
    cols: dict[str, str] | None = None,
) -> int:
    """cols maps raw->canonical, e.g. {'date':'ts','Volume':'volume'}.
    Defaults assume lowercase date/open/high/low/close/volume.
    """
    cols = cols or {
        "date": "ts",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
    }
    df = pl.read_csv(csv_path)
    df = df.rename({k: v for k, v in cols.items() if k in df.columns})
    df = df.with_columns(
        pl.col("ts").str.to_datetime(strict=False).alias("ts"),
        pl.lit(underlying).alias("underlying"),
    )
    if "volume" not in df.columns:
        df = df.with_columns(pl.lit(0, dtype=pl.Int64).alias("volume"))
    df = df.with_columns(pl.col("volume").cast(pl.Int64))
    return storage.write_spot(df)

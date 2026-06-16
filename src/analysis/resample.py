"""Resample 1-minute candles into N-minute buckets for the OI Pulse screens.

Operates on Polars DataFrames in the storage schema:
  spot_1m   : underlying, ts, open, high, low, close, volume
  options_1m: underlying, expiry, strike, option_type, ts, open, high, low,
              close, volume, oi

Buckets are epoch-aligned (09:15 session open divides evenly for 1/3/5/15 min).
Pass `offset` to shift bucket boundaries (e.g. "15m" to anchor 60-min buckets
to the 09:15 open).
"""
from __future__ import annotations

import polars as pl

VALID_INTERVALS = (1, 3, 5, 15, 30, 60)


def _agg_ohlcv() -> list[pl.Expr]:
    return [
        pl.col("open").first().alias("open"),
        pl.col("high").max().alias("high"),
        pl.col("low").min().alias("low"),
        pl.col("close").last().alias("close"),
        pl.col("volume").sum().alias("volume"),
    ]


def resample_spot(df: pl.DataFrame, minutes: int, offset: str = "0m") -> pl.DataFrame:
    """Spot 1m -> N-min OHLCV. Adds price_chg (close-over-close)."""
    if df.is_empty():
        return df
    out = (
        df.sort("ts")
        .group_by_dynamic("ts", every=f"{minutes}m", closed="left",
                          offset=offset, group_by="underlying")
        .agg(_agg_ohlcv())
        .sort("ts")
    )
    out = out.with_columns(
        pl.col("close").diff().over("underlying").alias("price_chg")
    )
    return out


def resample_options(df: pl.DataFrame, minutes: int, offset: str = "0m") -> pl.DataFrame:
    """Options 1m -> N-min per (strike, option_type). oi = last in bucket,
    oi_chg / ltp_chg = bucket-over-bucket diff within each contract."""
    if df.is_empty():
        return df
    out = (
        df.sort("ts")
        .group_by_dynamic(
            "ts", every=f"{minutes}m", closed="left", offset=offset,
            group_by=["underlying", "expiry", "strike", "option_type"],
        )
        .agg(_agg_ohlcv() + [pl.col("oi").last().alias("oi")])
        .sort("ts")
    )
    grp = ["underlying", "expiry", "strike", "option_type"]
    out = out.with_columns([
        pl.col("oi").diff().over(grp).alias("oi_chg"),
        pl.col("close").diff().over(grp).alias("ltp_chg"),
    ])
    return out

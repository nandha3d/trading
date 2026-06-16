"""PCR, synthetic IVR, VIX regime classification utilities."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

import polars as pl

from ..data import storage
from ..data.options_math import calculate_iv


def compute_pcr(df: pl.DataFrame) -> float:
    """PCR = total PE OI / total CE OI. Returns 1.0 if CE OI is zero."""
    if df.is_empty():
        return 1.0
    ce = df.filter(pl.col("option_type") == "CE")["oi"].sum() or 0
    pe = df.filter(pl.col("option_type") == "PE")["oi"].sum() or 0
    return float(pe / ce) if ce > 0 else 1.0


def compute_synthetic_ivr(df: pl.DataFrame, spot: float, dte_years: float,
                           r: float = 0.065) -> float:
    """Average IV (0-100 scale) across strikes within 5% of spot.
    Returns 0.0 if insufficient data.
    """
    if df.is_empty() or dte_years <= 0:
        return 0.0
    near = df.filter((pl.col("strike") - spot).abs() / spot <= 0.05)
    if near.is_empty():
        return 0.0
    ivs: list[float] = []
    for row in near.iter_rows(named=True):
        price = row.get("close") or 0.0
        if price <= 0:
            continue
        iv = calculate_iv(price, spot, float(row["strike"]), dte_years, r, row["option_type"])
        if iv and iv > 0:
            ivs.append(iv * 100.0)
    return float(sum(ivs) / len(ivs)) if ivs else 0.0


def classify_vix_regime(ivr: float) -> str:
    if ivr < 13:   return "low"
    if ivr < 18:   return "normal"
    if ivr < 25:   return "elevated"
    return "extreme"


def fetch_entry_snapshot(underlying: str, day: date, entry_time: time,
                          expiry: date) -> pl.DataFrame:
    """Full options chain snapshot within ±5 min of entry_time."""
    dt = datetime.combine(day, entry_time)
    return storage.read_options(underlying, dt - timedelta(minutes=5),
                                dt + timedelta(minutes=5), expiry=expiry)

"""Connecting Dots — per-interval multi-signal confluence table.

For each N-minute bucket of a trading day, compute bull/bear sub-signals
(Price, OI, VIX, VWAP, Supertrend, RSI) and a composite Trend band.
See docs/SPEC/14-oi-pulse.md.

Reads spot_1m + options_1m via storage. India VIX not wired yet -> VIX signal
is neutral and `has_vix=False` is returned so the UI can mark it.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import polars as pl

from src.data import storage
from src.backtest.indicators import compute_rsi, compute_supertrend, compute_vwap
from .resample import resample_spot, resample_options


def _nan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def _session(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, 9, 15)
    end = datetime(day.year, day.month, day.day, 15, 30)
    return start, end


def _nearest_expiry(underlying: str, day: date):
    exps = storage.list_expiries(underlying)
    fut = [e for e in exps if e >= day]
    return fut[0] if fut else (exps[-1] if exps else None)


def _band(sigs: list[int]) -> str:
    """Composite trend scored over the ACTIVE (non-neutral) sub-signals only.

    Signals that are structurally unavailable for a given day (e.g. OI when no
    options exist, VIX when not wired, VWAP on a volumeless index) read 0 and
    are excluded, so they no longer skew the verdict bearish.
    """
    bull = sum(1 for s in sigs if s > 0)
    bear = sum(1 for s in sigs if s < 0)
    active = bull + bear
    if active == 0:
        return "Neutral"
    ratio = bull / active
    if ratio == 1.0 and active >= 2:
        return "Extreme Bullish"
    if ratio >= 0.6:
        return "Bullish"
    if ratio == 0.0 and active >= 2:
        return "Extreme Bearish"
    if ratio <= 0.4:
        return "Bearish"
    return "Neutral"


def _sig(up: bool, dn: bool) -> int:
    return 1 if up else (-1 if dn else 0)


def _label(ts: datetime, interval: int) -> str:
    nxt = ts + timedelta(minutes=interval)
    return f"{ts.strftime('%H:%M')}-{nxt.strftime('%H:%M')}"


def _pivot_oi(agg: pl.DataFrame):
    """Yield (ts, ce_oi, pe_oi) from a long (ts, option_type, oi) frame."""
    by_ts: dict = {}
    for r in agg.iter_rows(named=True):
        d = by_ts.setdefault(r["ts"], {"CE": 0, "PE": 0})
        d[r["option_type"]] = r["oi"] or 0
    for ts in sorted(by_ts.keys()):
        yield ts, by_ts[ts]["CE"], by_ts[ts]["PE"]


def build_dots(underlying: str, day_iso: str, interval: int = 3,
               mode: str = "historical") -> dict:
    underlying = underlying.upper()
    day = date.fromisoformat(day_iso)
    start, end = _session(day)

    spot = storage.read_spot(underlying, start, end)
    if spot.is_empty():
        return {"rows": [], "underlying": underlying, "date": day_iso,
                "interval": interval, "has_vix": False, "expiry": None,
                "message": f"No spot data for {underlying} on {day_iso}"}

    sp = resample_spot(spot, interval).sort("ts")
    closes, highs, lows, vols = sp["close"], sp["high"], sp["low"], sp["volume"]
    rsi = compute_rsi(closes, 14)
    _st_line, st_dir = compute_supertrend(highs, lows, closes, 10, 3.0)
    vwap = compute_vwap(highs, lows, closes, vols)

    # PCR per bucket from the nearest expiry chain
    exp = _nearest_expiry(underlying, day)
    pcr_by_ts: dict = {}
    if exp:
        opts = storage.read_options(underlying, start, end, expiry=exp)
        if not opts.is_empty():
            ro = resample_options(opts, interval)
            agg = ro.group_by(["ts", "option_type"]).agg(pl.col("oi").sum().alias("oi"))
            for ts, ce, pe in _pivot_oi(agg):
                pcr_by_ts[ts] = (pe / ce) if ce > 0 else None

    rows = []
    prev_close = prev_pcr = None
    for i in range(sp.height):
        ts = sp["ts"][i]
        close = closes[i]
        price_sig = _sig(prev_close is not None and close > prev_close,
                         prev_close is not None and close < prev_close)
        pcr = pcr_by_ts.get(ts)
        oi_sig = _sig(pcr is not None and prev_pcr is not None and pcr > prev_pcr,
                      pcr is not None and prev_pcr is not None and pcr < prev_pcr)
        vix_sig = 0  # no VIX data yet
        vw = vwap[i]
        vwap_sig = 0 if _nan(vw) else _sig(close > vw, close < vw)
        st_sig = int(st_dir[i]) if st_dir[i] is not None else 0
        rv = rsi[i]
        rsi_sig = 0 if rv is None else _sig(rv > 50, rv < 50)

        sigs = [price_sig, oi_sig, vwap_sig, st_sig, rsi_sig, vix_sig]
        rows.append({
            "time": _label(ts, interval),
            "trend": _band(sigs),
            "price": price_sig,
            "oi": oi_sig,
            "vix": vix_sig,
            "vwap": vwap_sig,
            "supertrend": st_sig,
            "rsi": rsi_sig,
            "values": {
                "close": round(float(close), 2),
                "pcr": round(pcr, 3) if pcr is not None else None,
                "rsi": round(float(rv), 1) if rv is not None else None,
                "vwap": None if _nan(vw) else round(float(vw), 2),
            },
        })
        prev_close = close
        if pcr is not None:
            prev_pcr = pcr

    rows.reverse()  # newest on top, like OI Pulse
    return {"rows": rows, "underlying": underlying, "date": day_iso,
            "interval": interval, "has_vix": False,
            "expiry": str(exp) if exp else None,
            "mode": mode, "message": None}

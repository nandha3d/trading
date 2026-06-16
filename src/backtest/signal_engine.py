"""Quantman-style indicator + condition engine.

Given a list of named IndicatorDef and one day's spot candles, computes each
indicator on its own candle interval (real OHLC from spot_1m), aligns every
series onto a common base grid (the finest indicator interval), and evaluates
entry/exit ConditionGroups bar-by-bar — including cross-above / cross-below
using the previous bar.

All values are derived from real stored data; nothing is fabricated. Operands
that cannot be resolved (e.g. VWAP on a volumeless index) yield None and make
their condition False rather than guessing.
"""
from __future__ import annotations

from datetime import datetime, time
from typing import Optional

import polars as pl

from ..analysis.resample import resample_spot
from . import indicators as ind


# ---- per-day context -------------------------------------------------------

class DayContext:
    def __init__(self, bars: list[dict], series: dict[str, list[Optional[float]]],
                 dte: Optional[int] = None):
        self.bars = bars                     # base-grid bars: {ts, open, high, low, close, volume}
        self.series = series                 # "name|sub" -> values aligned to bars
        self.n = len(bars)
        self.dte = dte                       # days to expiry (same for the whole day)

    def bar_time(self, i: int) -> time:
        return self.bars[i]["ts"].time()


def _align(ind_ts: list[datetime], ind_vals: list, base_ts: list[datetime]) -> list[Optional[float]]:
    """Forward-fill indicator-interval values onto the base grid (last closed bar)."""
    out: list[Optional[float]] = []
    j, last = 0, None
    for bt in base_ts:
        while j < len(ind_ts) and ind_ts[j] <= bt:
            last = ind_vals[j]
            j += 1
        out.append(last if last is not None and last == last else None)  # drop NaN
    return out


def _series_for(idef, spot_df: pl.DataFrame) -> dict[str, tuple[list[datetime], list]]:
    """Compute one indicator -> {sub: (ts_list, value_list)} on its own interval."""
    rs = resample_spot(spot_df, max(1, idef.interval)).sort("ts")
    if rs.is_empty():
        return {}
    ts = rs["ts"].to_list()
    o, h, l, c, v = rs["open"], rs["high"], rs["low"], rs["close"], rs["volume"]
    src = {"open": o, "high": h, "low": l, "close": c}.get(idef.field, c)
    t = idef.type.upper()

    if t == "SMA":
        return {"value": (ts, ind.compute_sma(src, idef.period).to_list())}
    if t == "EMA":
        return {"value": (ts, ind.compute_ema(src, idef.period).to_list())}
    if t == "RSI":
        return {"value": (ts, ind.compute_rsi(src, idef.period).to_list())}
    if t == "ATR":
        return {"value": (ts, ind.compute_atr(h, l, c, idef.period).to_list())}
    if t == "SUPERTREND":
        line, d = ind.compute_supertrend(h, l, c, idef.period, idef.multiplier)
        return {"line": (ts, line.to_list()), "dir": (ts, d.to_list())}
    if t == "MACD":
        m, s, hi = ind.compute_macd(src, idef.fast, idef.slow, idef.signal)
        return {"macd": (ts, m.to_list()), "signal": (ts, s.to_list()), "hist": (ts, hi.to_list())}
    if t == "BOLLINGER":
        u, mid, lo = ind.compute_bollinger(src, idef.period, idef.std)
        return {"upper": (ts, u.to_list()), "mid": (ts, mid.to_list()), "lower": (ts, lo.to_list())}
    if t == "VWAP":
        return {"value": (ts, ind.compute_vwap(h, l, c, v).to_list())}
    if t == "RANGE_BREAKOUT":
        return _range_breakout(rs, idef)
    if t == "CURRENT_CANDLE":
        return {"open": (ts, o.to_list()), "high": (ts, h.to_list()),
                "low": (ts, l.to_list()), "close": (ts, c.to_list()),
                "volume": (ts, v.to_list())}
    return {}


def _range_breakout(rs: pl.DataFrame, idef) -> dict:
    """High/low of the [start_time, end_time] opening window; constant afterwards."""
    def _t(s: str) -> time:
        hh, mm = s.split(":")[:2]
        return time(int(hh), int(mm))
    s_t, e_t = _t(idef.start_time), _t(idef.end_time)
    win = rs.filter((pl.col("ts").dt.time() >= s_t) & (pl.col("ts").dt.time() <= e_t))
    hi = float(win["high"].max()) if not win.is_empty() else None
    lo = float(win["low"].min()) if not win.is_empty() else None
    ts = rs["ts"].to_list()
    hi_vals = [hi if t.time() > e_t else None for t in ts]
    lo_vals = [lo if t.time() > e_t else None for t in ts]
    return {"hi": (ts, hi_vals), "lo": (ts, lo_vals)}


def build_context(indicators: list, spot_df: pl.DataFrame,
                  dte: Optional[int] = None) -> Optional[DayContext]:
    if spot_df.is_empty():
        return None
    base_iv = min((max(1, i.interval) for i in indicators), default=1)
    base = resample_spot(spot_df, base_iv).sort("ts")
    if base.is_empty():
        return None
    base_ts = base["ts"].to_list()
    bars = [{"ts": r["ts"], "open": r["open"], "high": r["high"],
             "low": r["low"], "close": r["close"], "volume": r["volume"]}
            for r in base.iter_rows(named=True)]

    series: dict[str, list[Optional[float]]] = {}
    for idef in indicators:
        for sub, (ts, vals) in _series_for(idef, spot_df).items():
            series[f"{idef.name}|{sub}"] = _align(ts, vals, base_ts)
    return DayContext(bars, series, dte)


# ---- operand / condition evaluation ----------------------------------------

def _operand(op, ctx: DayContext, i: int) -> Optional[float]:
    if op.kind == "const":
        return float(op.value)
    if op.kind == "candle":
        b = ctx.bars[i]
        f = op.field
        if f in ("close", "open", "high", "low", "volume"):
            return b.get(f)
        if f == "ltp":
            return b.get("close")
        if f == "time_of_day":
            t = b["ts"].time()
            return t.hour * 100 + t.minute       # HHMM, e.g. 0930 -> 930
        if f == "day_of_week":
            return b["ts"].isoweekday()          # Mon=1 .. Sun=7
        if f == "dte":
            return float(ctx.dte) if ctx.dte is not None else None
        if f == "oi":
            return None                          # spot has no OI; condition stays False
        return b.get("close")
    sub = op.sub or "value"
    arr = ctx.series.get(f"{op.ref}|{sub}")
    if arr is None or i >= len(arr):
        return None
    return arr[i]


def _cmp(op: str, a: float, b: float) -> bool:
    if op == ">":  return a > b
    if op == "<":  return a < b
    if op == ">=": return a >= b
    if op == "<=": return a <= b
    if op == "==": return abs(a - b) < 1e-9
    return False


def _eval_condition(cond, ctx: DayContext, i: int) -> bool:
    a = _operand(cond.lhs, ctx, i)
    b = _operand(cond.rhs, ctx, i)
    if a is None or b is None:
        return False
    if cond.op in ("cross_above", "cross_below"):
        if i == 0:
            return False
        pa = _operand(cond.lhs, ctx, i - 1)
        pb = _operand(cond.rhs, ctx, i - 1)
        if pa is None or pb is None:
            return False
        if cond.op == "cross_above":
            return pa <= pb and a > b
        return pa >= pb and a < b
    return _cmp(cond.op, a, b)


def eval_group(group, ctx: DayContext, i: int) -> bool:
    if group is None or not group.conditions:
        return False
    results = [_eval_condition(c, ctx, i) for c in group.conditions]
    return all(results) if group.logic.upper() == "AND" else any(results)


def first_entry_bar(group, ctx: DayContext, after: time) -> Optional[int]:
    """Index of the first bar at/after `after` where the entry group is true."""
    for i in range(ctx.n):
        if ctx.bar_time(i) < after:
            continue
        if eval_group(group, ctx, i):
            return i
    return None

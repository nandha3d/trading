"""Parametric ATM short-straddle sweep (entry-time x stop-loss%) — vectorized.

Goal: scan thousands of (entry_time, sl_pct) combos over a date range in seconds.

Speed strategy (matches the "columnar / no Python per-candle loop" approach):
  * Preload spot + options for the WHOLE range with one read each (no per-combo
    SQL, no per-day round-trips on the 360M-row table).
  * Per day build, ONCE, a forward-filled close array per (strike, option_type)
    on the day's minute grid (numpy float64).
  * For a SELL leg, a % stop-loss fires the first minute the mark rises past
    entry*(1+sl/100). On the running-max of the price suffix (monotonic
    non-decreasing) that's a single np.searchsorted — so the entire SL axis
    collapses to one binary search per leg, no minute re-walk per SL value.

Result: combos = entry_minutes x sl_values, each costed against the same
in-memory arrays. ~20k combos over ~1 month finish in a few seconds.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import numpy as np
import polars as pl

from ..data import storage
from .costs import CostModel
from .engine import pick_expiry
from .strategy import CONTRACT_SPECS


@dataclass
class GridCell:
    entry_time: str          # "HH:MM"
    sl_pct: float
    net: float
    gross: float
    cost: float
    trades: int
    wins: int
    win_rate: float
    avg: float
    max_dd: float


@dataclass
class GridResult:
    cells: list[GridCell]
    entry_times: list[str]
    sl_values: list[float]
    best: GridCell | None
    days_used: int


def _minutes(day: date, t0: time, t1: time) -> list[datetime]:
    cur = datetime.combine(day, t0)
    end = datetime.combine(day, t1)
    out = []
    while cur <= end:
        out.append(cur)
        cur += timedelta(minutes=1)
    return out


def _ffill_array(pm: dict[datetime, float], grid: list[datetime]) -> np.ndarray:
    """Forward-filled close per grid minute as float64 (np.nan until first known)."""
    out = np.empty(len(grid), dtype=np.float64)
    last = np.nan
    for i, m in enumerate(grid):
        v = pm.get(m)
        if v is not None:
            last = v
        out[i] = last
    return out


def run_straddle_grid(
    underlying: str,
    start: date,
    end: date,
    entry_start: time = time(9, 18),
    entry_end: time = time(13, 0),
    exit_time: time = time(14, 55),
    sl_lo: float = 10.0,
    sl_hi: float = 100.0,
    sl_step: float = 1.0,
    entry_step_min: int = 1,
    expiry_offset: int = 0,
    lots: int = 1,
    costs: CostModel | None = None,
) -> GridResult:
    costs = costs or CostModel()
    cspec = CONTRACT_SPECS[underlying]
    step = cspec["strike_step"]
    qty = lots * cspec["lot_size"]

    sl_values = [float(round(v, 4)) for v in np.arange(sl_lo, sl_hi + 1e-9, sl_step)]
    sl_arr = np.array(sl_values, dtype=np.float64)
    sl_mult = 1.0 + sl_arr / 100.0          # mark threshold = entry * mult
    n_sl = sl_arr.size

    # candidate entry minutes as time-of-day (uniform across days)
    entry_tods: list[time] = []
    cur = datetime.combine(date(2000, 1, 1), entry_start)
    endm = datetime.combine(date(2000, 1, 1), entry_end)
    while cur <= endm:
        entry_tods.append(cur.time())
        cur += timedelta(minutes=entry_step_min)
    n_et = len(entry_tods)
    et_labels = [t.strftime("%H:%M") for t in entry_tods]

    # ---- trading days + expiries ----
    expiries = storage.list_expiries(underlying)
    days: list[tuple[date, date]] = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            exp = pick_expiry(expiries, d, expiry_offset)
            if exp:
                days.append((d, exp))
        d = date.fromordinal(d.toordinal() + 1)
    if not days:
        return GridResult([], et_labels, sl_values, None, 0)
    days_by_month: dict[tuple[int, int], list[tuple[date, date]]] = {}
    for dd, ee in days:
        days_by_month.setdefault((dd.year, dd.month), []).append((dd, ee))

    # accumulators per (entry_time_idx, sl_idx)
    sum_net = np.zeros((n_et, n_sl), dtype=np.float64)
    sum_gross = np.zeros((n_et, n_sl), dtype=np.float64)
    sum_cost = np.zeros((n_et, n_sl), dtype=np.float64)
    wins = np.zeros((n_et, n_sl), dtype=np.int64)
    trades = np.zeros((n_et, n_sl), dtype=np.int64)
    # per-entry running equity / drawdown across days (net only)
    equity = np.zeros((n_et, n_sl), dtype=np.float64)
    peak = np.zeros((n_et, n_sl), dtype=np.float64)
    maxdd = np.zeros((n_et, n_sl), dtype=np.float64)
    days_used = 0

    # process month-by-month: ONE projected scan per month, accumulate across
    # chunks (full multi-year range never held in memory at once).
    cur = storage.db().cursor()
    try:
      for (_yy, _mm), mdays in sorted(days_by_month.items()):
        c0 = datetime.combine(min(d for d, _ in mdays), time(9, 15))
        c1 = datetime.combine(max(d for d, _ in mdays), time(15, 30))
        spot_df = cur.execute(
            "SELECT ts, close FROM spot_1m WHERE underlying=? AND ts>=? AND ts<=? ORDER BY ts",
            [underlying, c0, c1]).pl()
        opt_df = cur.execute(
            "SELECT ts, strike, option_type, close, expiry FROM options_1m "
            "WHERE underlying=? AND ts>=? AND ts<=?",
            [underlying, c0, c1]).pl()
        if spot_df.is_empty() or opt_df.is_empty():
            continue
        spot_by: dict[date, pl.DataFrame] = {}
        for part in spot_df.with_columns(pl.col("ts").dt.date().alias("_d")).partition_by("_d"):
            spot_by[part["_d"][0]] = part.drop("_d")
        opt_by: dict[tuple[date, date], pl.DataFrame] = {}
        for part in opt_df.with_columns(pl.col("ts").dt.date().alias("_d")).partition_by(["_d", "expiry"]):
            opt_by[(part["_d"][0], part["expiry"][0])] = part.drop("_d")

        for day, exp in mdays:
            sd = spot_by.get(day)
            od = opt_by.get((day, exp))
            if sd is None or sd.is_empty() or od is None or od.is_empty():
                continue

            grid = _minutes(day, time(9, 15), exit_time)
            gidx = {m: i for i, m in enumerate(grid)}

            spot_pm = {
                r["ts"].replace(second=0, microsecond=0): r["close"]
                for r in sd.select(["ts", "close"]).iter_rows(named=True)
            }
            spot_arr = _ffill_array(spot_pm, grid)

            opt_pm: dict[tuple[int, str], dict] = {}
            for r in od.select(["strike", "option_type", "ts", "close"]).iter_rows(named=True):
                opt_pm.setdefault((r["strike"], r["option_type"]), {})[
                    r["ts"].replace(second=0, microsecond=0)] = r["close"]
            arr_cache: dict[tuple[int, str], np.ndarray] = {}

            def leg_arr(strike: int, ot: str, _pm=opt_pm, _cache=arr_cache, _grid=grid) -> np.ndarray | None:
                key = (strike, ot)
                if key in _cache:
                    return _cache[key]
                pm = _pm.get(key)
                if not pm:
                    return None
                a = _ffill_array(pm, _grid)
                _cache[key] = a
                return a

            day_contributed = False
            for ei, et in enumerate(entry_tods):
                ge = gidx.get(datetime.combine(day, et))
                if ge is None:
                    continue
                espot = spot_arr[ge]
                if not np.isfinite(espot):
                    continue
                atm = int(round(espot / step) * step)

                ce = leg_arr(atm, "CE")
                pe = leg_arr(atm, "PE")
                if ce is None or pe is None:
                    continue
                ce_s = ce[ge:]
                pe_s = pe[ge:]
                ce_entry = ce_s[0]
                pe_entry = pe_s[0]
                if not (np.isfinite(ce_entry) and np.isfinite(pe_entry)
                        and ce_entry > 0 and pe_entry > 0):
                    continue

                ce_exit = _leg_exits(ce_s, ce_entry, sl_mult, n_sl)
                pe_exit = _leg_exits(pe_s, pe_entry, sl_mult, n_sl)

                # SELL pnl = (entry - exit) * qty, per leg, vectorized over SL
                gross = (ce_entry - ce_exit) * qty + (pe_entry - pe_exit) * qty
                cost = (_vec_cost(ce_entry, ce_exit, qty, costs)
                        + _vec_cost(pe_entry, pe_exit, qty, costs))
                net = gross - cost

                sum_gross[ei] += gross
                sum_cost[ei] += cost
                sum_net[ei] += net
                trades[ei] += 1
                wins[ei] += (net > 0)
                equity[ei] += net
                peak[ei] = np.maximum(peak[ei], equity[ei])
                np.maximum(maxdd[ei], peak[ei] - equity[ei], out=maxdd[ei])
                day_contributed = True

            if day_contributed:
                days_used += 1
    finally:
        cur.close()

    # ---- assemble cells ----
    cells: list[GridCell] = []
    for ei in range(n_et):
        for si in range(n_sl):
            tr = int(trades[ei, si])
            if tr == 0:
                continue
            cells.append(GridCell(
                entry_time=et_labels[ei],
                sl_pct=float(sl_arr[si]),
                net=round(float(sum_net[ei, si]), 2),
                gross=round(float(sum_gross[ei, si]), 2),
                cost=round(float(sum_cost[ei, si]), 2),
                trades=tr,
                wins=int(wins[ei, si]),
                win_rate=round(float(wins[ei, si]) / tr, 4),
                avg=round(float(sum_net[ei, si]) / tr, 2),
                max_dd=round(float(maxdd[ei, si]), 2),
            ))
    best = max(cells, key=lambda c: c.net) if cells else None
    return GridResult(cells, et_labels, sl_values, best, days_used)


def _leg_exits(suffix: np.ndarray, entry_p: float, sl_mult: np.ndarray, n_sl: int) -> np.ndarray:
    """Exit premium per SL value for a SELL leg via running-max + searchsorted."""
    rm = np.maximum.accumulate(suffix)              # monotonic non-decreasing
    thr = entry_p * sl_mult                          # (n_sl,) mark thresholds
    hit = np.searchsorted(rm, thr, side="left")      # first idx where rm >= thr
    last = suffix.size - 1
    exits = np.empty(n_sl, dtype=np.float64)
    hitmask = hit <= last
    exits[hitmask] = suffix[np.minimum(hit[hitmask], last)]  # SL filled at mark
    exits[~hitmask] = suffix[last]                            # no SL -> time exit
    return exits


def _vec_cost(entry_p: float, exit_p, qty: int, c: CostModel):
    """Vectorized CostModel.leg_cost over an array of exit prices (entry scalar)."""
    exit_p = np.asarray(exit_p, dtype=np.float64)
    buy_val = entry_p * qty
    sell_val = exit_p * qty
    brokerage = c.brokerage_per_order * 2
    stt = sell_val * c.stt_sell_pct
    txn = (buy_val + sell_val) * c.exch_txn_pct
    sebi = (buy_val + sell_val) * c.sebi_pct
    stamp = buy_val * c.stamp_buy_pct
    gst = (brokerage + txn) * c.gst_pct
    return brokerage + stt + txn + sebi + stamp + gst

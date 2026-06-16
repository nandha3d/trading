"""Event-driven 1-minute options backtest engine (P1: per-leg risk + greeks).

Per trading day:
  1. read spot 1-min; get entry spot at entry_time
  2. resolve each leg's strike (ATM offset / nearest-premium / nearest-delta)
  3. align each leg on the entry->exit minute grid (forward-filled prices)
  4. walk minutes: per-leg TP / SL / Trail SL (Points / Percent / Underlying)
  5. legs not stopped exit at exit_time; apply costs; record trade

Underlying-unit thresholds are converted to premium points via the leg's
entry delta (premium_move ~= |delta| * underlying_move). Documented approximation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import polars as pl

from ..data import storage
from . import greeks
from .costs import CostModel
from .indicators import compute_ema, compute_rsi, compute_bollinger, last_valid
from .iv_regime import (compute_pcr, compute_synthetic_ivr, classify_vix_regime,
                         fetch_entry_snapshot)
from .metrics import Stats, compute
from . import signal_engine
from .strategy import Action, Leg, RiskRule, Selection, StrategySpec, Unit


@dataclass
class LegFill:
    leg: Leg
    strike: int
    entry: float
    exit: float = 0.0
    qty: int = 0
    exit_reason: str = "TIME"
    exit_time: datetime | None = None


@dataclass
class Trade:
    day: date
    legs: list[LegFill] = field(default_factory=list)
    gross: float = 0.0
    cost: float = 0.0
    net: float = 0.0
    exit_reason: str = ""
    entry_spot: float = 0.0
    skip_reason: str = ""   # non-empty = entry filter rejected this day
    vix: float = 0.0
    expiry: date | None = None
    entry_dt: datetime | None = None


@dataclass
class BacktestResult:
    trades: list[Trade]
    stats: Stats


# ---------- helpers ----------

def _atm(spot: float, step: int) -> int:
    return int(round(spot / step) * step)


def _minute_grid(day: date, entry_t: time, exit_t: time) -> list[datetime]:
    cur = datetime.combine(day, entry_t)
    end = datetime.combine(day, exit_t)
    out = []
    while cur <= end:
        out.append(cur)
        cur += timedelta(minutes=1)
    return out


def _price_map(df: pl.DataFrame) -> dict[datetime, float]:
    """ts(floored to minute) -> close."""
    if df.is_empty():
        return {}
    return {
        r["ts"].replace(second=0, microsecond=0): r["close"]
        for r in df.select(["ts", "close"]).iter_rows(named=True)
    }


def _ffill_at(pm: dict[datetime, float], grid: list[datetime]) -> list[float | None]:
    """Forward-filled price per grid minute (None until first known)."""
    out, last = [], None
    for m in grid:
        if m in pm:
            last = pm[m]
        out.append(last)
    return out


def _favorable(action: Action, entry: float, mark: float) -> float:
    """Premium points in the position's favor."""
    return (entry - mark) if action is Action.SELL else (mark - entry)


def _rule_points(rule: RiskRule, entry_prem: float, entry_spot: float, entry_delta: float) -> float:
    d = abs(entry_delta) if entry_delta else 0.5
    if rule.unit is Unit.POINTS:
        return rule.value
    if rule.unit is Unit.PERCENT:
        return rule.value / 100.0 * entry_prem
    if rule.unit is Unit.UNDERLYING_PTS:
        return rule.value * d
    if rule.unit is Unit.UNDERLYING_PCT:
        return rule.value / 100.0 * entry_spot * d
    return rule.value


# ---------- strike selection ----------

def _resolve_strike(
    spec: StrategySpec, leg: Leg, expiry: date,
    entry_dt: datetime, entry_spot: float,
    start: datetime, end: datetime,
    chain_df: pl.DataFrame | None = None,
) -> int | None:
    step = spec.spec["strike_step"]
    if leg.selection is Selection.ATM:
        return _atm(entry_spot, step) + int(leg.value) * step

    # PREMIUM / DELTA need the chain at the entry minute (preloaded slice if given)
    if chain_df is not None:
        chain = chain_df.filter(pl.col("option_type") == leg.opt_type.value)
    else:
        chain = storage.read_options(
            spec.underlying, start, end, expiry=expiry, option_type=leg.opt_type.value
        )
    if chain.is_empty():
        return None
    et = entry_dt.time()
    snap = chain.filter(pl.col("ts").dt.time() >= et)
    if snap.is_empty():
        return None
    first_ts = snap.select(pl.col("ts").min()).item()
    snap = snap.filter(pl.col("ts") == first_ts)  # one row per strike at entry

    best, best_d = None, None
    t_years = greeks.years_to_expiry(entry_dt, expiry)
    for r in snap.iter_rows(named=True):
        k, prem = r["strike"], r["close"]
        if prem is None or prem <= 0:
            continue
        if leg.selection is Selection.PREMIUM:
            d = abs(prem - leg.value)
        else:  # DELTA
            dl = greeks.delta(prem, entry_spot, k, t_years, leg.opt_type.value)
            if dl is None:
                continue
            d = abs(abs(dl) - abs(leg.value))
        if best_d is None or d < best_d:
            best_d, best = d, k
    return best


# ---------- entry condition check ----------

def _check_entry_conditions(spec: StrategySpec, day: date, expiry: date,
                              entry_spot: float, snapshot: pl.DataFrame | None = None,
                              ivr_val: float = 0.0) -> tuple[bool, str]:
    """Returns (ok, skip_reason). Checks weekday, PCR, IVR, VIX regime, indicator."""
    # Weekday filter
    if spec.entry_weekdays is not None:
        if day.weekday() not in spec.entry_weekdays:
            return False, f"weekday_{day.weekday()}_excluded"

    needs_snapshot = any([spec.min_pcr, spec.max_pcr, spec.min_iv_rank, spec.max_iv_rank,
                           spec.use_vix_gate])
    if needs_snapshot and snapshot is None:
        snapshot = fetch_entry_snapshot(spec.underlying, day, spec.entry_time, expiry)

    if snapshot is not None and not snapshot.is_empty():
        # PCR filter
        if spec.min_pcr or spec.max_pcr:
            pcr = compute_pcr(snapshot)
            if spec.min_pcr and pcr < spec.min_pcr:
                return False, f"pcr_{pcr:.2f}_below_{spec.min_pcr}"
            if spec.max_pcr and pcr > spec.max_pcr:
                return False, f"pcr_{pcr:.2f}_above_{spec.max_pcr}"

        # IVR / VIX regime filter
        if spec.min_iv_rank or spec.max_iv_rank or spec.use_vix_gate:
            if not ivr_val:
                entry_dt = datetime.combine(day, spec.entry_time)
                exp_dt = expiry
                dte = max((exp_dt - day).days, 0) / 365.0
                ivr_val = compute_synthetic_ivr(snapshot, entry_spot, dte)
            if spec.min_iv_rank and ivr_val < spec.min_iv_rank:
                return False, f"ivr_{ivr_val:.1f}_below_{spec.min_iv_rank}"
            if spec.max_iv_rank and ivr_val > spec.max_iv_rank:
                return False, f"ivr_{ivr_val:.1f}_above_{spec.max_iv_rank}"
            if spec.use_vix_gate:
                regime = classify_vix_regime(ivr_val)
                if regime not in spec.vix_regimes:
                    return False, f"vix_regime_{regime}_not_allowed"

    # Indicator filter (requires spot_1m history)
    if spec.indicator_type:
        hist_end = datetime.combine(day, spec.entry_time)
        hist_start = datetime.combine(date.fromordinal(day.toordinal() - 60),
                                       spec.entry_time)
        spot_df = storage.read_spot(spec.underlying, hist_start, hist_end)
        if not spot_df.is_empty():
            import polars as pl
            daily = (
                spot_df
                .with_columns(pl.col("ts").dt.date().alias("d"))
                .group_by("d").agg(pl.col("close").last())
                .sort("d")
            )["close"]

            p = spec.indicator_params
            if spec.indicator_type == "EMA_CROSS":
                fast = compute_ema(daily, p.get("ema_fast", 9))
                slow = compute_ema(daily, p.get("ema_slow", 21))
                fv, sv = last_valid(fast), last_valid(slow)
                if fv is not None and sv is not None:
                    bullish = fv > sv
                    if p.get("ema_signal", "above") == "above" and not bullish:
                        return False, "ema_bearish"
                    if p.get("ema_signal", "above") == "below" and bullish:
                        return False, "ema_bullish"

            elif spec.indicator_type == "RSI":
                rsi = compute_rsi(daily, p.get("rsi_period", 14))
                rv = last_valid(rsi)
                if rv is not None:
                    ob, os_ = p.get("rsi_overbought", 70), p.get("rsi_oversold", 30)
                    if os_ <= rv <= ob:
                        return False, f"rsi_{rv:.1f}_neutral"

            elif spec.indicator_type == "BOLLINGER":
                upper, mid, lower = compute_bollinger(daily, p.get("bb_period", 20),
                                                       p.get("bb_std", 2.0))
                spot_now = last_valid(daily)
                u, m, l = last_valid(upper), last_valid(mid), last_valid(lower)
                sig = p.get("bb_signal", "squeeze")
                if spot_now and u and l and m:
                    width = (u - l) / m
                    if sig == "squeeze" and width > 0.04:
                        return False, f"bb_not_squeeze"
                    elif sig == "upper" and spot_now < u * 0.995:
                        return False, "not_near_upper_band"
                    elif sig == "lower" and spot_now > l * 1.005:
                        return False, "not_near_lower_band"

    return True, ""


# ---------- per-day ----------

def run_day(spec: StrategySpec, day: date, expiry: date, costs: CostModel,
            spot_day: pl.DataFrame | None = None,
            opt_day: pl.DataFrame | None = None) -> Trade | None:
    start = datetime.combine(day, time(9, 15))
    end = datetime.combine(day, time(15, 30))

    spot_df = spot_day if spot_day is not None else storage.read_spot(spec.underlying, start, end)
    if spot_df.is_empty():
        return None
    es = spot_df.filter(pl.col("ts").dt.time() >= spec.entry_time)
    if es.is_empty():
        return None
    entry_spot = es.row(0, named=True)["close"]
    entry_dt = datetime.combine(day, spec.entry_time)

    # Compute entry synthetic IVR
    snapshot = fetch_entry_snapshot(spec.underlying, day, spec.entry_time, expiry)
    dte = max((expiry - day).days, 0) / 365.0
    ivr_val = compute_synthetic_ivr(snapshot, entry_spot, dte) if not snapshot.is_empty() else 0.0

    ok, skip_rsn = _check_entry_conditions(spec, day, expiry, entry_spot, snapshot, ivr_val)
    if not ok:
        return Trade(day=day, skip_reason=skip_rsn, entry_spot=entry_spot, vix=ivr_val, expiry=expiry)

    # ---- Quantman-style indicator/condition signals (optional) ----
    sig_ctx = None
    eff_entry_time = spec.entry_time
    has_entry_sig = bool(spec.signal_indicators and spec.entry_signal
                         and getattr(spec.entry_signal, "conditions", None))
    has_exit_sig = bool(spec.signal_indicators and spec.exit_signal
                        and getattr(spec.exit_signal, "conditions", None))
    if has_entry_sig or has_exit_sig:
        sig_ctx = signal_engine.build_context(spec.signal_indicators, spot_df,
                                              dte=max((expiry - day).days, 0))
    if has_entry_sig:
        if sig_ctx is None:
            return Trade(day=day, skip_reason="no_signal_data", entry_spot=entry_spot, vix=ivr_val, expiry=expiry)
        bi = signal_engine.first_entry_bar(spec.entry_signal, sig_ctx, spec.entry_time)
        if bi is None:
            return Trade(day=day, skip_reason="entry_signal_not_met", entry_spot=entry_spot, vix=ivr_val, expiry=expiry)
        eb = sig_ctx.bars[bi]
        eff_entry_time = eb["ts"].time()
        entry_spot = eb["close"]
        entry_dt = eb["ts"]

    grid = _minute_grid(day, eff_entry_time, spec.exit_time)
    t_years = greeks.years_to_expiry(entry_dt, expiry)

    # map each grid minute -> latest closed exit-signal bar index
    exit_bar_at: list[int] | None = None
    if has_exit_sig and sig_ctx is not None:
        bts = [b["ts"] for b in sig_ctx.bars]
        exit_bar_at = []
        j = 0
        for m in grid:
            while j + 1 < len(bts) and bts[j + 1] <= m:
                j += 1
            exit_bar_at.append(j if bts and bts[j] <= m else -1)

    # Pass 1: resolve every leg's strike
    resolved: list[tuple[Leg, int]] = []
    for leg in spec.legs:
        strike = _resolve_strike(spec, leg, expiry, entry_dt, entry_spot, start, end, chain_df=opt_day)
        if strike is None:
            return None
        resolved.append((leg, strike))

    # Single batched option read for ALL strikes (kills the per-leg N+1 queries).
    # When opt_day is preloaded (whole range scanned once), slice in memory.
    want_strikes = sorted({s for _, s in resolved})
    if opt_day is not None:
        opt_all = opt_day.filter(pl.col("strike").is_in(want_strikes))
    else:
        opt_all = storage.read_options(spec.underlying, start, end, expiry=expiry, strikes=want_strikes)
    if opt_all.is_empty():
        return None
    pm_by: dict[tuple[int, str], dict] = {}
    for r in opt_all.select(["strike", "option_type", "ts", "close"]).iter_rows(named=True):
        pm_by.setdefault((r["strike"], r["option_type"]), {})[
            r["ts"].replace(second=0, microsecond=0)] = r["close"]

    legs: list[LegFill] = []
    leg_prices: list[list[float | None]] = []
    leg_meta: list[dict] = []
    for leg, strike in resolved:
        pm = pm_by.get((strike, leg.opt_type.value))
        if not pm:
            return None
        prices = _ffill_at(pm, grid)
        if prices[0] is None:
            return None
        entry_prem = prices[0]
        edelta = greeks.delta(entry_prem, entry_spot, strike, t_years, leg.opt_type.value) or 0.5
        legs.append(LegFill(leg=leg, strike=strike, entry=entry_prem,
                            qty=leg.lots * spec.spec["lot_size"]))
        leg_prices.append(prices)
        leg_meta.append({"edelta": edelta})

    # net premium for portfolio-level pct thresholds
    entry_net = sum(
        (fill.entry if fill.leg.action is Action.SELL else -fill.entry) * fill.qty
        for fill in legs
    )
    prem_base = abs(entry_net) if entry_net != 0 else 1.0
    peak_combined = 0.0

    # walk minutes, per-leg exits
    n = len(legs)
    done = [False] * n
    peak_fav = [0.0] * n
    for gi in range(len(grid)):
        for li in range(n):
            if done[li]:
                continue
            mark = leg_prices[li][gi]
            if mark is None:
                continue
            fill = legs[li]
            leg = fill.leg
            es_ = entry_spot
            ed = leg_meta[li]["edelta"]
            fav = _favorable(leg.action, fill.entry, mark)
            # take profit
            if leg.tp and fav >= _rule_points(leg.tp, fill.entry, es_, ed):
                fill.exit, fill.exit_reason, fill.exit_time, done[li] = mark, "TARGET", grid[gi], True
                continue
            # stop loss
            if leg.sl and fav <= -_rule_points(leg.sl, fill.entry, es_, ed):
                fill.exit, fill.exit_reason, fill.exit_time, done[li] = mark, "STOPLOSS", grid[gi], True
                continue
            # trailing SL
            if leg.trail_trigger and leg.trail_step:
                trig = _rule_points(leg.trail_trigger, fill.entry, es_, ed)
                stepp = _rule_points(leg.trail_step, fill.entry, es_, ed)
                if fav >= trig:
                    peak_fav[li] = max(peak_fav[li], fav)
                    if fav <= peak_fav[li] - stepp:
                        fill.exit, fill.exit_reason, fill.exit_time, done[li] = mark, "TRAIL", grid[gi], True
                        continue

        # exit-signal check (Quantman-style exit conditions)
        if exit_bar_at is not None:
            bidx = exit_bar_at[gi]
            if bidx >= 0 and signal_engine.eval_group(spec.exit_signal, sig_ctx, bidx):
                for li in range(n):
                    if not done[li]:
                        m = leg_prices[li][gi]
                        if m is not None:
                            legs[li].exit, legs[li].exit_reason, legs[li].exit_time, done[li] = m, "SIGNAL", grid[gi], True
                break

        # portfolio-level exit check (target / overall SL / trailing SL)
        if spec.target_pct or spec.stoploss_pct or spec.trailing_sl_pct:
            combined = sum(
                _favorable(legs[li].leg.action, legs[li].entry, leg_prices[li][gi]) * legs[li].qty
                for li in range(n)
                if not done[li] and leg_prices[li][gi] is not None
            )
            if combined > peak_combined:
                peak_combined = combined
            port_exit, port_rsn = False, "TIME"
            if spec.target_pct and combined >= prem_base * (spec.target_pct / 100):
                port_exit, port_rsn = True, "TARGET"
            elif spec.stoploss_pct and combined <= -prem_base * (spec.stoploss_pct / 100):
                port_exit, port_rsn = True, "STOPLOSS"
            elif spec.trailing_sl_pct and peak_combined > 0:
                if combined <= peak_combined - prem_base * (spec.trailing_sl_pct / 100):
                    port_exit, port_rsn = True, "TRAIL"
            if port_exit:
                for li in range(n):
                    if done[li]:
                        continue
                    m = leg_prices[li][gi]
                    if m is not None:
                        legs[li].exit, legs[li].exit_reason, legs[li].exit_time, done[li] = m, port_rsn, grid[gi], True
                break  # exit minute walk

    # legs still open -> exit at last known price on grid
    for li in range(n):
        if not done[li]:
            last = next((p for p in reversed(leg_prices[li]) if p is not None), legs[li].entry)
            legs[li].exit = last
            legs[li].exit_reason = "TIME"
            legs[li].exit_time = grid[-1] if grid else entry_dt

    trade = Trade(day=day, legs=legs, entry_spot=entry_spot, vix=ivr_val,
                  expiry=expiry, entry_dt=entry_dt)
    for f in legs:
        trade.gross += _favorable(f.leg.action, f.entry, f.exit) * f.qty
        trade.cost += costs.leg_cost(f.entry, f.exit, f.qty)
    trade.net = trade.gross - trade.cost
    reasons = {f.exit_reason for f in legs}
    trade.exit_reason = reasons.pop() if len(reasons) == 1 else "MIXED"
    return trade


# ---------- range driver ----------

def pick_expiry(expiries: list[date], day: date, offset: int) -> date | None:
    future = [e for e in expiries if e >= day]
    if not future or offset >= len(future):
        return None
    return future[offset]


def run(spec: StrategySpec, days: list[tuple[date, date]], costs: CostModel | None = None) -> BacktestResult:
    costs = costs or CostModel()
    all_trades = [t for d, e in days if (t := run_day(spec, d, e, costs)) is not None]
    executed = [t for t in all_trades if not t.skip_reason]
    daily = [t.net for t in executed]
    return BacktestResult(trades=all_trades, stats=compute(daily, daily))


def run_range(spec: StrategySpec, start: date, end: date, costs: CostModel | None = None) -> BacktestResult:
    costs = costs or CostModel()
    expiries = storage.list_expiries(spec.underlying)
    days: list[tuple[date, date]] = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            exp = pick_expiry(expiries, d, spec.expiry_offset)
            if exp:
                days.append((d, exp))
        d = date.fromordinal(d.toordinal() + 1)
    if not days:
        return BacktestResult(trades=[], stats=compute([], []))

    # ---- Bulk preload: scan the whole range ONCE, slice per-day in memory.
    # Replaces hundreds of per-day SQL round-trips on the 360M-row table.
    start_dt = datetime.combine(start, time(9, 15))
    end_dt = datetime.combine(end, time(15, 30))
    spot_all = storage.read_spot(spec.underlying, start_dt, end_dt)
    opt_all = storage.read_options(spec.underlying, start_dt, end_dt)

    spot_by: dict[date, pl.DataFrame] = {}
    if not spot_all.is_empty():
        sa = spot_all.with_columns(pl.col("ts").dt.date().alias("_d"))
        for part in sa.partition_by("_d"):
            spot_by[part["_d"][0]] = part.drop("_d")

    opt_by: dict[tuple[date, date], pl.DataFrame] = {}
    if not opt_all.is_empty():
        oa = opt_all.with_columns(pl.col("ts").dt.date().alias("_d"))
        for part in oa.partition_by(["_d", "expiry"]):
            opt_by[(part["_d"][0], part["expiry"][0])] = part.drop("_d")

    trades: list[Trade] = []
    for day, exp in days:
        sd = spot_by.get(day)
        if sd is None or sd.is_empty():
            continue
        t = run_day(spec, day, exp, costs, spot_day=sd, opt_day=opt_by.get((day, exp)))
        if t is not None:
            trades.append(t)

    executed = [t for t in trades if not t.skip_reason]
    daily = [t.net for t in executed]
    return BacktestResult(trades=trades, stats=compute(daily, daily))

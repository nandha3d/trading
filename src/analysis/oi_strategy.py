"""Rule-based NSE OI strategy signal engine.

MVP scope:
- Global no-trade filters that can be evaluated from the current schema.
- CE wall breakout and PE wall breakdown detection.
- Long-premium suggested legs only: BUY ATM CE / BUY ATM PE.

Unavailable production-grade fields such as real bid/ask, futures OI, event
calendar, and F&O ban state are surfaced in data_quality instead of fabricated.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta, time
import math
import random
from typing import Any, Optional

import polars as pl

from src.backtest import signal_engine
from src.backtest.costs import CostModel
from src.backtest.indicators import compute_vwap
from src.backtest.strategy import CONTRACT_SPECS, lot_size_for
from src.data import storage
from .resample import resample_options, resample_spot


SUPPORTED_FACTORS = [
    "oi_wall_unwinding",
    "vwap_confirmation",
    "volume_confirmation",
    "pcr_confirmation",
    "mtf_trend",
    "theta_suitability",
]
DEFAULT_QUALIFICATION_GATES = {
    "max_p_value": 0.05,
    "min_profit_factor": 1.3,
    "min_trades": 200,
}


@dataclass(frozen=True)
class OiStrategyConfig:
    min_option_oi: int = 10_000
    min_option_volume: int = 5_000
    max_bid_ask_spread_percent: float = 3.0
    min_option_ltp: float = 5.0
    oi_wall_multiplier: float = 1.5
    ce_unwinding_threshold_percent: float = -5.0
    pe_unwinding_threshold_percent: float = -5.0
    ce_buildup_threshold_percent: float = 5.0
    pe_buildup_threshold_percent: float = 5.0
    volume_multiplier: float = 1.5
    min_signal_score: int = 75
    strong_signal_score: int = 85
    no_trade_first_minutes: int = 15
    no_fresh_trade_after: str = "14:45"
    force_exit_time: str = "15:15"
    premium_sl_percent: float = 25.0
    premium_target_percent: float = 50.0
    trailing_sl_percent: float = 30.0
    max_trades_per_day: int = 3
    monitor_strikes: int = 5
    oi_lookback_candles: int = 3
    pcr_lookback_candles: int = 3
    volume_avg_candles: int = 20
    trend_timeframes: list[int] = field(default_factory=lambda: [15, 60])
    score_weights: dict[str, int] = field(default_factory=lambda: {
        "oi_wall_unwinding": 25,
        "vwap_confirmation": 15,
        "volume_confirmation": 15,
        "pcr_confirmation": 15,
        "mtf_trend": 15,
        "theta_suitability": 15,
    })
    execution_model: str = "adverse_close"
    slippage_bps: float = 5.0
    estimated_spread_percent: float = 1.0
    initial_capital: float = 500_000.0
    risk_per_trade_percent: float = 1.0
    daily_loss_limit_percent: float = 2.0
    cooldown_after_loss_bars: int = 1
    theta_exit_profile: str = "standard"
    expiry_day_tightening: bool = True
    expiry_day_no_fresh_trade_after: str = "13:30"
    expiry_day_force_exit_time: str = "14:45"
    expiry_day_premium_sl_percent: float = 20.0
    expiry_day_premium_target_percent: float = 35.0
    require_factor_coverage_percent: float = 80.0
    active_factors: list[str] = field(default_factory=lambda: list(SUPPORTED_FACTORS))
    required_factors: list[str] = field(default_factory=list)
    run_ablation_study: bool = False
    ablation_trailing_sl_values: list[float] = field(default_factory=lambda: [20.0, 30.0, 40.0, 0.0])
    qualification_gates: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_QUALIFICATION_GATES))


@dataclass(frozen=True)
class Wall:
    strike: int
    option_type: str
    oi: int
    avg_oi: float
    rank: int
    oi_change: int
    oi_change_percent: Optional[float]
    ltp: Optional[float]
    ltp_change_percent: Optional[float]


def _default_data_quality(mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "real_bid_ask": "unavailable",
        "iv_rank": "unavailable_not_applied",
        "iv_skew": "unavailable_not_applied",
        "futures_oi": "unavailable",
        "event_calendar": "unavailable",
        "fo_ban_filter": "unavailable",
        "spread_filter": "estimated_from_config_without_real_bid_ask",
    }


def _cfg(overrides: dict[str, Any] | None = None) -> OiStrategyConfig:
    cfg = OiStrategyConfig()
    if not overrides:
        return cfg
    allowed = set(asdict(cfg))
    clean = {k: v for k, v in overrides.items() if k in allowed and v is not None}
    if "active_factors" in clean:
        clean["active_factors"] = _clean_factor_list(clean["active_factors"], default=list(SUPPORTED_FACTORS))
    if "required_factors" in clean:
        clean["required_factors"] = _clean_factor_list(clean["required_factors"], default=[])
    if "qualification_gates" in clean:
        gates = dict(DEFAULT_QUALIFICATION_GATES)
        raw_gates = clean["qualification_gates"] or {}
        gates.update({k: float(v) for k, v in raw_gates.items() if k in gates and v is not None})
        clean["qualification_gates"] = gates
    if "ablation_trailing_sl_values" in clean:
        clean["ablation_trailing_sl_values"] = [float(v) for v in clean["ablation_trailing_sl_values"]]
    return replace(cfg, **clean)


def _weight(cfg: OiStrategyConfig, factor: str) -> int:
    return int(cfg.score_weights.get(factor, OiStrategyConfig().score_weights[factor]))


def _clean_factor_list(value: Any, default: list[str]) -> list[str]:
    if not value:
        return list(default)
    return [str(f) for f in value if str(f) in SUPPORTED_FACTORS]


def _active_factor_set(cfg: OiStrategyConfig) -> set[str]:
    return set(_clean_factor_list(cfg.active_factors, list(SUPPORTED_FACTORS)))


def _normalized_score(factors: list[dict[str, Any]]) -> int:
    max_points = sum(int(f.get("max_points") or 0) for f in factors if f.get("available", True))
    points = sum(int(f.get("points") or 0) for f in factors if f.get("available", True))
    return int(round(points / max_points * 100.0)) if max_points else 0


def _required_factor_failures(factors: list[dict[str, Any]], cfg: OiStrategyConfig) -> list[str]:
    by_name = {str(f.get("factor")): f for f in factors}
    failures: list[str] = []
    for factor in _clean_factor_list(cfg.required_factors, []):
        if factor not in _active_factor_set(cfg):
            continue
        item = by_name.get(factor)
        if item is None or not item.get("available", True):
            failures.append(f"Required factor {factor} is unavailable")
        elif not item.get("passed"):
            failures.append(f"Required factor {factor} did not pass")
    return failures


def _factor(
    factor: str,
    label: str,
    max_points: int,
    passed: bool,
    detail: str,
    raw_value: float | str | None = None,
    threshold: float | str | None = None,
    available: bool = True,
) -> dict[str, Any]:
    return {
        "factor": factor,
        "label": label,
        "points": max_points if available and passed else 0,
        "max_points": max_points,
        "passed": bool(passed) if available else False,
        "available": available,
        "detail": detail,
        "raw_value": raw_value,
        "threshold": threshold,
    }


def _factor_coverage(factors: list[dict[str, Any]]) -> dict[str, float]:
    available = sum(float(f["max_points"]) for f in factors if f.get("available", True))
    unavailable = sum(float(f["max_points"]) for f in factors if not f.get("available", True))
    total = available + unavailable
    return {
        "available_weight": round(available, 2),
        "unavailable_weight": round(unavailable, 2),
        "coverage_percent": round(available / total * 100.0, 2) if total else 100.0,
    }


def _parse_hm(value: str) -> time:
    hh, mm = value.split(":")[:2]
    return time(int(hh), int(mm))


def _session(day: date) -> tuple[datetime, datetime]:
    return datetime(day.year, day.month, day.day, 9, 15), datetime(day.year, day.month, day.day, 15, 30)


def _first_eligible_entry_time(cfg: OiStrategyConfig) -> time:
    dt = datetime(2000, 1, 1, 9, 15) + timedelta(minutes=max(0, int(cfg.no_trade_first_minutes)))
    return dt.time()


def _nearest_expiry(underlying: str, day: date) -> date | None:
    expiries = storage.list_expiries(underlying)
    future = [e for e in expiries if e >= day]
    return future[0] if future else (expiries[-1] if expiries else None)


def _strike_step(underlying: str) -> int:
    return int(CONTRACT_SPECS.get(underlying.upper(), {"strike_step": 50})["strike_step"])


def _atm(spot: float, step: int) -> int:
    return int(round(spot / step) * step)


def _pct_change(delta: float | int | None, current: float | int | None) -> Optional[float]:
    if delta is None or current is None:
        return None
    previous = float(current) - float(delta)
    if previous <= 0:
        return None
    return float(delta) / previous * 100.0


def _row_at(rows: list[dict], strike: int, option_type: str) -> dict | None:
    for row in rows:
        if int(row["strike"]) == int(strike) and row["option_type"] == option_type:
            return row
    return None


def _select_bucket(df: pl.DataFrame, target_dt: datetime | None) -> datetime | None:
    if df.is_empty():
        return None
    times = df.select("ts").unique().sort("ts")["ts"].to_list()
    if not times:
        return None
    if target_dt is None:
        return times[-1]
    eligible = [ts for ts in times if ts <= target_dt]
    return eligible[-1] if eligible else None


def _snapshot_rows(options: pl.DataFrame, ts: datetime) -> list[dict]:
    return options.filter(pl.col("ts") == ts).iter_rows(named=True)


def _valid_walls(rows: list[dict], option_type: str, cfg: OiStrategyConfig) -> list[Wall]:
    side = [r for r in rows if r["option_type"] == option_type]
    if not side:
        return []
    avg_oi = sum(int(r["oi"] or 0) for r in side) / len(side)
    ranked = sorted(side, key=lambda r: int(r["oi"] or 0), reverse=True)
    out: list[Wall] = []
    for rank, row in enumerate(ranked, start=1):
        oi = int(row["oi"] or 0)
        strong = (avg_oi > 0 and oi >= cfg.oi_wall_multiplier * avg_oi) or rank <= 2
        if not strong:
            continue
        oi_chg = int(row.get("oi_chg") or 0)
        ltp_chg = float(row.get("ltp_chg") or 0.0)
        close = row.get("close")
        out.append(Wall(
            strike=int(row["strike"]),
            option_type=option_type,
            oi=oi,
            avg_oi=float(avg_oi),
            rank=rank,
            oi_change=oi_chg,
            oi_change_percent=_pct_change(oi_chg, oi),
            ltp=float(close) if close is not None else None,
            ltp_change_percent=_pct_change(ltp_chg, close),
        ))
    return sorted(out, key=lambda w: w.strike)


def detect_oi_walls(
    rows: list[dict],
    spot: float,
    step: int,
    cfg: OiStrategyConfig | None = None,
) -> dict[str, Wall | None]:
    """Return nearest strong CE resistance and PE support around spot."""
    cfg = cfg or OiStrategyConfig()
    atm = _atm(spot, step)
    low = atm - cfg.monitor_strikes * step
    high = atm + cfg.monitor_strikes * step
    monitored = [r for r in rows if low <= int(r["strike"]) <= high]
    ce = _valid_walls(monitored, "CE", cfg)
    pe = _valid_walls(monitored, "PE", cfg)
    ce_broken_or_near = [w for w in ce if w.strike <= spot]
    pe_broken_or_near = [w for w in pe if w.strike >= spot]
    return {
        "ce_wall": max(ce_broken_or_near, key=lambda w: w.strike, default=min(ce, key=lambda w: w.strike, default=None)),
        "pe_wall": min(pe_broken_or_near, key=lambda w: w.strike, default=max(pe, key=lambda w: w.strike, default=None)),
        "next_ce_wall": min([w for w in ce if w.strike > spot], key=lambda w: w.strike, default=None),
        "next_pe_wall": max([w for w in pe if w.strike < spot], key=lambda w: w.strike, default=None),
    }


def _best_oi_change(rows: list[dict], option_type: str, strikes: set[int], positive: bool) -> tuple[float | None, dict | None]:
    best_pct: float | None = None
    best_row: dict | None = None
    for row in rows:
        if row["option_type"] != option_type or int(row["strike"]) not in strikes:
            continue
        pct = _pct_change(row.get("oi_chg"), row.get("oi"))
        if pct is None:
            continue
        if best_pct is None:
            best_pct, best_row = pct, row
            continue
        if positive and pct > best_pct:
            best_pct, best_row = pct, row
        if not positive and pct < best_pct:
            best_pct, best_row = pct, row
    return best_pct, best_row


def _recent_contract_pct_change(
    opt_hist: pl.DataFrame,
    bucket_ts: datetime,
    strike: int,
    option_type: str,
    lookback: int,
    field_name: str = "oi",
) -> float | None:
    rows = (
        opt_hist
        .filter(
            (pl.col("strike") == int(strike))
            & (pl.col("option_type") == option_type)
            & (pl.col("ts") <= bucket_ts)
        )
        .sort("ts")
        .tail(max(2, lookback + 1))
        .iter_rows(named=True)
    )
    vals = [float(r.get(field_name) or 0.0) for r in rows]
    if len(vals) < 2 or vals[0] <= 0:
        return None
    return (vals[-1] - vals[0]) / vals[0] * 100.0


def _pcr_for_rows(rows: list[dict]) -> float | None:
    ce_oi = sum(float(r.get("oi") or 0.0) for r in rows if r.get("option_type") == "CE")
    pe_oi = sum(float(r.get("oi") or 0.0) for r in rows if r.get("option_type") == "PE")
    return pe_oi / ce_oi if ce_oi > 0 else None


def _pcr_change(opt_hist: pl.DataFrame, bucket_ts: datetime, lookback: int) -> tuple[float | None, float | None]:
    times = opt_hist.filter(pl.col("ts") <= bucket_ts).select("ts").unique().sort("ts")["ts"].to_list()
    if not times:
        return None, None
    current_ts = times[-1]
    previous_ts = times[max(0, len(times) - lookback - 1)]
    current = _pcr_for_rows(list(_snapshot_rows(opt_hist, current_ts)))
    previous = _pcr_for_rows(list(_snapshot_rows(opt_hist, previous_ts)))
    if current is None or previous is None:
        return current, None
    return current, current - previous


def _trend_direction(spot_hist: pl.DataFrame, bucket_ts: datetime, timeframe: int) -> tuple[str, float | None]:
    window_start = bucket_ts - timedelta(minutes=timeframe)
    rows = spot_hist.filter((pl.col("ts") >= window_start) & (pl.col("ts") <= bucket_ts)).sort("ts")
    closes = [float(v or 0.0) for v in rows["close"].to_list()] if not rows.is_empty() else []
    if len(closes) < 2:
        return "unavailable", None
    pct = (closes[-1] - closes[0]) / closes[0] * 100.0 if closes[0] else None
    if pct is None:
        return "unavailable", None
    if pct > 0.03:
        return "up", pct
    if pct < -0.03:
        return "down", pct
    return "flat", pct


def _atr_percent(spot_hist: pl.DataFrame, lookback: int = 14) -> float:
    rows = spot_hist.tail(lookback)
    if rows.is_empty():
        return 0.0
    ranges = [(float(r["high"] or 0.0) - float(r["low"] or 0.0)) for r in rows.iter_rows(named=True)]
    close = float(rows["close"][-1] or 0.0)
    return (sum(ranges) / len(ranges) / close * 100.0) if close > 0 and ranges else 0.0


def _regime_for(spot_hist: pl.DataFrame, bucket_ts: datetime, expiry: date) -> str:
    trend, pct = _trend_direction(spot_hist, bucket_ts, 60)
    atr_pct = _atr_percent(spot_hist)
    parts = []
    if trend in ("up", "down") and pct is not None and abs(pct) >= 0.15:
        parts.append("trending")
    else:
        parts.append("range_bound")
    if atr_pct >= 0.35:
        parts.append("high_vol_proxy")
    else:
        parts.append("normal_vol_proxy")
    parts.append("expiry_day" if bucket_ts.date() == expiry else "non_expiry_day")
    return "|".join(parts)


def _classify_price_oi(price_pct: float | None, oi_pct: float | None) -> str:
    if price_pct is None or oi_pct is None:
        return "Unavailable"
    if price_pct > 0 and oi_pct > 0:
        return "Long Buildup"
    if price_pct < 0 and oi_pct > 0:
        return "Short Buildup"
    if price_pct < 0 and oi_pct < 0:
        return "Long Unwinding"
    if price_pct > 0 and oi_pct < 0:
        return "Short Covering"
    return "Neutral"


def _score_breakout(
    direction: str,
    spot_close: float,
    wall: Wall | None,
    rows: list[dict],
    opt_hist: pl.DataFrame,
    spot_hist: pl.DataFrame,
    bucket_ts: datetime,
    expiry: date,
    atm: int,
    step: int,
    current_volume: float,
    avg_volume: float,
    vwap: float | None,
    cfg: OiStrategyConfig,
) -> tuple[int, list[dict], list[str]]:
    breakdown: list[dict] = []
    reasons: list[str] = []
    active_factors = _active_factor_set(cfg)

    def add(item: dict[str, Any]) -> None:
        if str(item.get("factor")) not in active_factors:
            return
        breakdown.append(item)
        if item["passed"] and item.get("available", True):
            reasons.append(item["detail"])

    wall_weight = _weight(cfg, "oi_wall_unwinding")
    vwap_weight = _weight(cfg, "vwap_confirmation")
    volume_weight = _weight(cfg, "volume_confirmation")
    pcr_weight = _weight(cfg, "pcr_confirmation")
    trend_weight = _weight(cfg, "mtf_trend")
    theta_weight = _weight(cfg, "theta_suitability")
    pcr, pcr_delta = _pcr_change(opt_hist, bucket_ts, cfg.pcr_lookback_candles)
    trends = [_trend_direction(spot_hist, bucket_ts, tf) for tf in cfg.trend_timeframes]
    dte = max((expiry - bucket_ts.date()).days, 0)
    theta_cutoff = _parse_hm(cfg.expiry_day_no_fresh_trade_after if dte == 0 and cfg.expiry_day_tightening else cfg.no_fresh_trade_after)

    def add_legacy_reason(detail: str, passed: bool) -> None:
        if passed:
            reasons.append(detail)

    if direction == "bullish":
        premium_row = _row_at(rows, atm, "CE")
        wall_pct = _recent_contract_pct_change(opt_hist, bucket_ts, wall.strike, "CE", cfg.oi_lookback_candles) if wall else None
        if wall_pct is None and wall is not None:
            wall_pct = wall.oi_change_percent
        premium_pct = _pct_change(premium_row.get("ltp_chg"), premium_row.get("close")) if premium_row else None
        oi_class = _classify_price_oi(premium_pct, wall_pct)
        wall_pass = wall is not None and spot_close > wall.strike and wall_pct is not None and wall_pct <= cfg.ce_unwinding_threshold_percent
        add(_factor("oi_wall_unwinding", "CE wall break + OI unwinding", wall_weight, wall_pass, f"Close {spot_close:.2f} broke CE wall {wall.strike}; CE wall OI {wall_pct:.1f}% ({oi_class})" if wall and wall_pct is not None else "CE wall/OI momentum unavailable", wall_pct, f"<= {cfg.ce_unwinding_threshold_percent}%"))
        add(_factor("vwap_confirmation", "Spot above VWAP", vwap_weight, vwap is not None and spot_close > vwap, f"Spot {spot_close:.2f} is above VWAP {vwap:.2f}" if vwap else "VWAP unavailable", spot_close - vwap if vwap else None, "> 0", vwap is not None))
        add(_factor("volume_confirmation", "Volume participation", volume_weight, avg_volume > 0 and current_volume >= cfg.volume_multiplier * avg_volume, f"Volume is {current_volume / avg_volume:.1f}x {cfg.volume_avg_candles}-candle average" if avg_volume > 0 else "Average volume unavailable", current_volume / avg_volume if avg_volume > 0 else None, f">= {cfg.volume_multiplier}x", avg_volume > 0))
        pcr_pass = pcr is not None and ((pcr >= 1.0) or (pcr_delta is not None and pcr_delta > 0))
        add(_factor("pcr_confirmation", "PCR regime/shift", pcr_weight, pcr_pass, f"PCR {pcr:.2f}, change {pcr_delta or 0:.2f} supports bullish bias" if pcr is not None else "PCR unavailable", pcr, ">= 1.0 or rising", pcr is not None))
        trend_pass = any(t == "up" for t, _ in trends) and not any(t == "down" and pct is not None and abs(pct) > 0.15 for t, pct in trends)
        add(_factor("mtf_trend", "Higher-timeframe trend", trend_weight, trend_pass, "15/60 minute trend does not fight bullish setup", ",".join(t for t, _ in trends), "up/not strongly down"))
        theta_pass = bucket_ts.time() <= theta_cutoff and dte >= 0
        add(_factor("theta_suitability", "Theta/time suitability", theta_weight, theta_pass, f"DTE {dte}; fresh-entry cutoff {theta_cutoff.strftime('%H:%M')}", dte, f"<= {theta_cutoff.strftime('%H:%M')}"))
        add_legacy_reason(f"ATM CE premium changed {premium_pct:.1f}%" if premium_pct is not None else "", premium_pct is not None and premium_pct >= 5.0)
    else:
        premium_row = _row_at(rows, atm, "PE")
        wall_pct = _recent_contract_pct_change(opt_hist, bucket_ts, wall.strike, "PE", cfg.oi_lookback_candles) if wall else None
        if wall_pct is None and wall is not None:
            wall_pct = wall.oi_change_percent
        premium_pct = _pct_change(premium_row.get("ltp_chg"), premium_row.get("close")) if premium_row else None
        oi_class = _classify_price_oi(premium_pct, wall_pct)
        wall_pass = wall is not None and spot_close < wall.strike and wall_pct is not None and wall_pct <= cfg.pe_unwinding_threshold_percent
        add(_factor("oi_wall_unwinding", "PE wall break + OI unwinding", wall_weight, wall_pass, f"Close {spot_close:.2f} broke PE wall {wall.strike}; PE wall OI {wall_pct:.1f}% ({oi_class})" if wall and wall_pct is not None else "PE wall/OI momentum unavailable", wall_pct, f"<= {cfg.pe_unwinding_threshold_percent}%"))
        add(_factor("vwap_confirmation", "Spot below VWAP", vwap_weight, vwap is not None and spot_close < vwap, f"Spot {spot_close:.2f} is below VWAP {vwap:.2f}" if vwap else "VWAP unavailable", vwap - spot_close if vwap else None, "> 0", vwap is not None))
        add(_factor("volume_confirmation", "Volume participation", volume_weight, avg_volume > 0 and current_volume >= cfg.volume_multiplier * avg_volume, f"Volume is {current_volume / avg_volume:.1f}x {cfg.volume_avg_candles}-candle average" if avg_volume > 0 else "Average volume unavailable", current_volume / avg_volume if avg_volume > 0 else None, f">= {cfg.volume_multiplier}x", avg_volume > 0))
        pcr_pass = pcr is not None and ((pcr <= 1.0) or (pcr_delta is not None and pcr_delta < 0))
        add(_factor("pcr_confirmation", "PCR regime/shift", pcr_weight, pcr_pass, f"PCR {pcr:.2f}, change {pcr_delta or 0:.2f} supports bearish bias" if pcr is not None else "PCR unavailable", pcr, "<= 1.0 or falling", pcr is not None))
        trend_pass = any(t == "down" for t, _ in trends) and not any(t == "up" and pct is not None and abs(pct) > 0.15 for t, pct in trends)
        add(_factor("mtf_trend", "Higher-timeframe trend", trend_weight, trend_pass, "15/60 minute trend does not fight bearish setup", ",".join(t for t, _ in trends), "down/not strongly up"))
        theta_pass = bucket_ts.time() <= theta_cutoff and dte >= 0
        add(_factor("theta_suitability", "Theta/time suitability", theta_weight, theta_pass, f"DTE {dte}; fresh-entry cutoff {theta_cutoff.strftime('%H:%M')}", dte, f"<= {theta_cutoff.strftime('%H:%M')}"))
        add_legacy_reason(f"ATM PE premium changed {premium_pct:.1f}%" if premium_pct is not None else "", premium_pct is not None and premium_pct >= 5.0)

    return _normalized_score(breakdown), breakdown, reasons


def _liquidity_reasons(option_row: dict | None, cfg: OiStrategyConfig) -> list[str]:
    reasons: list[str] = []
    if option_row is None:
        return ["Suggested ATM option is missing"]
    if int(option_row.get("oi") or 0) < cfg.min_option_oi:
        reasons.append(f"Option OI below minimum {cfg.min_option_oi}")
    if int(option_row.get("volume") or 0) < cfg.min_option_volume:
        reasons.append(f"Option volume below minimum {cfg.min_option_volume}")
    close = option_row.get("close")
    if close is None or float(close) < cfg.min_option_ltp:
        reasons.append(f"Option LTP below minimum {cfg.min_option_ltp}")
    return reasons


def _suggested_leg(direction: str, entry_time: str, cfg: OiStrategyConfig) -> dict:
    return {
        "action": "BUY",
        "opt_type": "CE" if direction == "bullish" else "PE",
        "selection": "ATM",
        "value": 0,
        "lots": 1,
        "sl_pct": cfg.premium_sl_percent,
        "sl_unit": "PERCENT",
        "tp_pct": None,
        "tp_unit": "PERCENT",
        "entry_time": entry_time,
        "exit_time": cfg.force_exit_time,
    }


def _target_levels(direction: str, wall: Wall | None, next_wall: Wall | None) -> dict[str, float | None]:
    if direction == "bullish":
        return {"target_1": float(next_wall.strike) if next_wall else None, "target_2": None, "stop_loss_level": float(wall.strike) if wall else None}
    return {"target_1": float(next_wall.strike) if next_wall else None, "target_2": None, "stop_loss_level": float(wall.strike) if wall else None}


def analyze_oi_frames(
    underlying: str,
    day: date,
    expiry: date,
    spot_df: pl.DataFrame,
    options_df: pl.DataFrame,
    target_dt: datetime | None = None,
    interval: int = 5,
    config: dict[str, Any] | OiStrategyConfig | None = None,
    mode: str = "historical",
) -> dict:
    underlying = underlying.upper()
    cfg = config if isinstance(config, OiStrategyConfig) else _cfg(config)
    data_quality = _default_data_quality(mode)

    if spot_df.is_empty():
        return _no_trade(underlying, expiry, cfg, "No spot data for selected session", data_quality)
    if options_df.is_empty():
        return _no_trade(underlying, expiry, cfg, "No option-chain data for selected session/expiry", data_quality)

    spot = resample_spot(spot_df, interval).sort("ts")
    opts = resample_options(options_df, interval).sort("ts")
    return _analyze_prepared_frames(
        underlying=underlying,
        expiry=expiry,
        spot=spot,
        opts=opts,
        target_dt=target_dt,
        cfg=cfg,
        data_quality=data_quality,
    )


def _analyze_prepared_frames(
    underlying: str,
    expiry: date,
    spot: pl.DataFrame,
    opts: pl.DataFrame,
    target_dt: datetime | None,
    cfg: OiStrategyConfig,
    data_quality: dict,
) -> dict:
    bucket_ts = _select_bucket(spot, target_dt)
    if bucket_ts is None:
        return _no_trade(underlying, expiry, cfg, "No candle bucket available for selected timestamp", data_quality)

    spot_hist = spot.filter(pl.col("ts") <= bucket_ts)
    opt_hist = opts.filter(pl.col("ts") <= bucket_ts)
    snap = list(_snapshot_rows(opt_hist, bucket_ts))
    if not snap:
        return _no_trade(underlying, expiry, cfg, "No option snapshot for selected candle bucket", data_quality, bucket_ts)

    current_spot = spot_hist.filter(pl.col("ts") == bucket_ts).row(0, named=True)
    spot_close = float(current_spot["close"])
    step = _strike_step(underlying)
    atm = _atm(spot_close, step)
    vwap_series = compute_vwap(
        spot_hist["high"].cast(pl.Float64),
        spot_hist["low"].cast(pl.Float64),
        spot_hist["close"].cast(pl.Float64),
        spot_hist["volume"].cast(pl.Float64),
    )
    vwap_val = vwap_series[-1] if len(vwap_series) else None
    vwap = None if vwap_val is None or vwap_val != vwap_val else float(vwap_val)
    volumes = [float(v or 0) for v in spot_hist["volume"].to_list()]
    current_volume = volumes[-1] if volumes else 0.0
    volume_window = volumes[:-1][-cfg.volume_avg_candles:]
    avg_volume = sum(volume_window) / len(volume_window) if volume_window else 0.0
    entry_time = bucket_ts.strftime("%H:%M")

    no_trade_reasons = _time_filter(bucket_ts.time(), cfg)
    walls = detect_oi_walls(snap, spot_close, step, cfg)

    bull_score, bull_breakdown, bull_reasons = _score_breakout(
        "bullish", spot_close, walls["ce_wall"], snap, opt_hist, spot_hist, bucket_ts, expiry, atm, step, current_volume, avg_volume, vwap, cfg
    )
    bear_score, bear_breakdown, bear_reasons = _score_breakout(
        "bearish", spot_close, walls["pe_wall"], snap, opt_hist, spot_hist, bucket_ts, expiry, atm, step, current_volume, avg_volume, vwap, cfg
    )

    candidates = [
        ("bullish", "Bullish OI Wall Breakout", "BUY_CE", bull_score, bull_breakdown, bull_reasons, walls["ce_wall"], walls["next_ce_wall"]),
        ("bearish", "Bearish OI Wall Breakdown", "BUY_PE", bear_score, bear_breakdown, bear_reasons, walls["pe_wall"], walls["next_pe_wall"]),
    ]
    direction, strategy, signal_type, score, score_breakdown, reasons, wall, next_wall = max(candidates, key=lambda c: c[3])
    if score < cfg.min_signal_score:
        no_trade_reasons.append(f"Signal score {score}/100 is below minimum {cfg.min_signal_score}/100")
    coverage = _factor_coverage(score_breakdown)
    if coverage["coverage_percent"] < cfg.require_factor_coverage_percent:
        no_trade_reasons.append(f"Factor coverage {coverage['coverage_percent']:.0f}% is below minimum {cfg.require_factor_coverage_percent:.0f}%")
    no_trade_reasons.extend(_required_factor_failures(score_breakdown, cfg))

    option_row = _row_at(snap, atm, "CE" if direction == "bullish" else "PE")
    no_trade_reasons.extend(_liquidity_reasons(option_row, cfg))

    valid = not no_trade_reasons
    strength = "STRONG" if score >= cfg.strong_signal_score else ("VALID" if score >= cfg.min_signal_score else "NO_TRADE")
    target = _target_levels(direction, wall, next_wall)
    suggested_legs = [_suggested_leg(direction, entry_time, cfg)] if valid else []

    return {
        "underlying": underlying,
        "expiry": expiry.isoformat(),
        "timestamp": bucket_ts.isoformat(),
        "spot_price": round(spot_close, 2),
        "atm_strike": atm,
        "signal_type": signal_type if valid else "NO_TRADE",
        "strategy_name": strategy if valid else "No-trade: confirmation missing",
        "score": int(score),
        "strength": strength if valid else "NO_TRADE",
        "reasons": reasons if valid else [],
        "no_trade_reasons": no_trade_reasons,
        "score_breakdown": score_breakdown,
        "factor_scores": score_breakdown,
        "factor_coverage": coverage,
        "candidate_signal_type": signal_type,
        "candidate_direction": direction,
        "regime": _regime_for(spot_hist, bucket_ts, expiry),
        "walls": {
            "ce_wall": asdict(walls["ce_wall"]) if walls["ce_wall"] else None,
            "pe_wall": asdict(walls["pe_wall"]) if walls["pe_wall"] else None,
        },
        "entry_zone": float(wall.strike) if wall else None,
        "stop_loss": target["stop_loss_level"],
        "target_1": target["target_1"],
        "target_2": target["target_2"],
        "suggested_legs": suggested_legs,
        "data_quality": data_quality,
        "config": asdict(cfg),
    }


def _time_filter(t: time, cfg: OiStrategyConfig) -> list[str]:
    reasons: list[str] = []
    start_block = _first_eligible_entry_time(cfg)
    if t < start_block:
        reasons.append(f"No fresh OI trade before {start_block.strftime('%H:%M')}")
    if t > _parse_hm(cfg.no_fresh_trade_after):
        reasons.append(f"No fresh intraday trade after {cfg.no_fresh_trade_after}")
    if t >= _parse_hm(cfg.force_exit_time):
        reasons.append(f"Force-exit time {cfg.force_exit_time} reached")
    return reasons


def _no_trade(
    underlying: str,
    expiry: date | None,
    cfg: OiStrategyConfig,
    reason: str,
    data_quality: dict,
    ts: datetime | None = None,
) -> dict:
    return {
        "underlying": underlying.upper(),
        "expiry": expiry.isoformat() if expiry else None,
        "timestamp": ts.isoformat() if ts else None,
        "spot_price": None,
        "atm_strike": None,
        "signal_type": "NO_TRADE",
        "strategy_name": "No-trade: confirmation missing",
        "score": 0,
        "strength": "NO_TRADE",
        "reasons": [],
        "no_trade_reasons": [reason],
        "score_breakdown": [],
        "factor_scores": [],
        "factor_coverage": {"available_weight": 0.0, "unavailable_weight": 0.0, "coverage_percent": 0.0},
        "candidate_signal_type": "NO_TRADE",
        "candidate_direction": None,
        "regime": None,
        "walls": {"ce_wall": None, "pe_wall": None},
        "entry_zone": None,
        "stop_loss": None,
        "target_1": None,
        "target_2": None,
        "suggested_legs": [],
        "data_quality": data_quality,
        "config": asdict(cfg),
    }


def analyze_oi_signal(
    underlying: str,
    day: date,
    expiry: date | None = None,
    timestamp: datetime | None = None,
    interval: int = 5,
    config: dict[str, Any] | None = None,
    mode: str = "historical",
) -> dict:
    underlying = underlying.upper()
    exp = expiry or _nearest_expiry(underlying, day)
    cfg = _cfg(config)
    data_quality = _default_data_quality(mode)
    if exp is None:
        return _no_trade(underlying, None, cfg, "No expiry available for selected underlying/date", data_quality)

    start, end = _session(day)
    spot_df = storage.read_spot(underlying, start, end)
    options_df = storage.read_options(underlying, start, end, expiry=exp)
    return analyze_oi_frames(
        underlying=underlying,
        day=day,
        expiry=exp,
        spot_df=spot_df,
        options_df=options_df,
        target_dt=timestamp,
        interval=interval,
        config=cfg,
        mode=mode,
    )


def _trade_dates(underlying: str, start: date, end: date) -> list[date]:
    cur = storage.db().cursor()
    try:
        rows = cur.execute(
            """
            SELECT DISTINCT CAST(ts AS DATE) d
            FROM spot_1m
            WHERE underlying = ? AND CAST(ts AS DATE) >= ? AND CAST(ts AS DATE) <= ?
            ORDER BY d
            """,
            [underlying.upper(), start, end],
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        cur.close()


def _expiry_for_offset(underlying: str, day: date, offset: int = 0) -> date | None:
    expiries = [e for e in storage.list_expiries(underlying) if e >= day]
    if not expiries:
        return _nearest_expiry(underlying, day)
    idx = min(max(offset, 0), len(expiries) - 1)
    return expiries[idx]


def _option_marks(opts: pl.DataFrame, strike: int, option_type: str, start_ts: datetime, end_ts: datetime) -> list[dict]:
    if opts.is_empty():
        return []
    rows = (
        opts
        .filter(
            (pl.col("strike") == int(strike))
            & (pl.col("option_type") == option_type)
            & (pl.col("ts") >= start_ts)
            & (pl.col("ts") <= end_ts)
        )
        .sort("ts")
        .iter_rows(named=True)
    )
    return list(rows)


def _has_conditions(group: Any) -> bool:
    return bool(group and getattr(group, "conditions", None))


def _signal_bar_index_at(ctx: Any, ts: datetime) -> int | None:
    if ctx is None or not getattr(ctx, "bars", None):
        return None
    idx: int | None = None
    for i, bar in enumerate(ctx.bars):
        if bar["ts"] <= ts:
            idx = i
        else:
            break
    return idx


def _signal_group_passes(group: Any, ctx: Any, ts: datetime) -> tuple[bool, str]:
    if not _has_conditions(group):
        return True, ""
    idx = _signal_bar_index_at(ctx, ts)
    if idx is None:
        return False, "indicator_signal_data_unavailable"
    if not signal_engine.eval_group(group, ctx, idx):
        return False, "indicator_entry_signal_not_met"
    return True, ""


def _exit_from_marks(
    marks: list[dict],
    entry_price: float,
    cfg: OiStrategyConfig,
    expiry: date | None = None,
    exit_signal: Any = None,
    signal_ctx: Any = None,
) -> tuple[dict | None, str]:
    if not marks:
        return None, "NO_OPTION_MARKS"
    entry_ts = marks[0].get("ts")
    expiry_day = expiry is not None and isinstance(entry_ts, datetime) and entry_ts.date() == expiry
    sl_pct = cfg.expiry_day_premium_sl_percent if expiry_day and cfg.expiry_day_tightening else cfg.premium_sl_percent
    target_pct = cfg.expiry_day_premium_target_percent if expiry_day and cfg.expiry_day_tightening else cfg.premium_target_percent
    stop_price = entry_price * (1.0 - sl_pct / 100.0)
    target_price = entry_price * (1.0 + target_pct / 100.0)
    trail_active = cfg.trailing_sl_percent > 0
    peak = entry_price
    trail_stop: float | None = None

    for mark in marks[1:]:
        price = float(mark["close"])
        if price > peak:
            peak = price
            if trail_active:
                trail_stop = peak * (1.0 - cfg.trailing_sl_percent / 100.0)
        if price <= stop_price:
            return mark, "SL"
        if price >= target_price:
            return mark, "TARGET"
        if trail_stop is not None and peak > entry_price and price <= trail_stop:
            return mark, "TRAILING_SL"
        if _has_conditions(exit_signal):
            idx = _signal_bar_index_at(signal_ctx, mark["ts"])
            if idx is not None and signal_engine.eval_group(exit_signal, signal_ctx, idx):
                return mark, "SIGNAL"
    return marks[-1], "TIME"


def _execution_price(price: float, cfg: OiStrategyConfig, is_entry: bool, cost_multiplier: float = 1.0) -> float:
    if cfg.execution_model == "close" or cost_multiplier == 0:
        return price
    slippage = price * (cfg.slippage_bps / 10_000.0) * cost_multiplier
    spread = 0.0
    if cfg.execution_model == "estimated_spread":
        spread = price * (cfg.estimated_spread_percent / 100.0) * 0.5 * cost_multiplier
    penalty = slippage + spread
    return price + penalty if is_entry else max(0.01, price - penalty)


def _volatility_scaled_qty(underlying: str, expiry: date, entry_price: float, spot_hist: pl.DataFrame, cfg: OiStrategyConfig) -> int:
    lot = lot_size_for(underlying, expiry)
    risk_budget = max(cfg.initial_capital * cfg.risk_per_trade_percent / 100.0, 0.0)
    per_lot_risk = entry_price * lot * cfg.premium_sl_percent / 100.0
    if per_lot_risk <= 0 or risk_budget <= 0:
        return lot
    atr_pct = _atr_percent(spot_hist)
    vol_scale = 0.5 if atr_pct >= 0.35 else (0.75 if atr_pct >= 0.2 else 1.0)
    lots = max(1, int((risk_budget / per_lot_risk) * vol_scale))
    return lots * lot


def _pnl_for_prices(
    underlying: str,
    expiry: date,
    entry_price: float,
    exit_price: float,
    qty: int,
    cfg: OiStrategyConfig,
    costs: CostModel,
    cost_multiplier: float = 1.0,
) -> tuple[float, float, float, float, float]:
    fill_entry = _execution_price(entry_price, cfg, True, cost_multiplier)
    fill_exit = _execution_price(exit_price, cfg, False, cost_multiplier)
    gross = (fill_exit - fill_entry) * qty
    cost = costs.leg_cost(fill_entry, fill_exit, qty) * cost_multiplier
    net = gross - cost
    return fill_entry, fill_exit, gross, cost, net


def _stats_from_trades(trades: list[dict]) -> dict:
    nets = [float(t["net_pnl"]) for t in trades]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n <= 0]
    equity = []
    running = 0.0
    peak = 0.0
    max_dd = 0.0
    for n in nets:
        running += n
        equity.append(round(running, 2))
        peak = max(peak, running)
        max_dd = min(max_dd, running - peak)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    avg = sum(nets) / len(nets) if nets else 0.0
    variance = sum((n - avg) ** 2 for n in nets) / (len(nets) - 1) if len(nets) > 1 else 0.0
    downside = [min(0.0, n) for n in nets]
    downside_var = sum(n ** 2 for n in downside) / (len(downside) - 1) if len(downside) > 1 else 0.0
    sharpe = (avg / math.sqrt(variance) * math.sqrt(252)) if variance > 0 else 0.0
    sortino = (avg / math.sqrt(downside_var) * math.sqrt(252)) if downside_var > 0 else 0.0
    win_rate = len(wins) / len(trades) if trades else 0.0
    ci = 1.96 * math.sqrt(win_rate * (1 - win_rate) / len(trades)) if trades else 0.0
    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate * 100, 2) if trades else 0.0,
        "net_pnl": round(sum(nets), 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else (999.0 if gross_profit else 0.0),
        "avg_trade": round(sum(nets) / len(nets), 2) if nets else 0.0,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "max_drawdown": round(max_dd, 2),
        "recovery_factor": round(sum(nets) / abs(max_dd), 4) if max_dd else (999.0 if sum(nets) > 0 else 0.0),
        "return_to_mdd_ratio": round(sum(nets) / abs(max_dd), 4) if max_dd else (999.0 if sum(nets) > 0 else 0.0),
        "expectancy": round(avg, 2),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "win_rate_ci_low": round(max(0.0, (win_rate - ci) * 100), 2),
        "win_rate_ci_high": round(min(100.0, (win_rate + ci) * 100), 2),
        "equity_curve": equity,
    }


def _trade_key(trade: dict) -> str:
    return "|".join([
        str(trade.get("day") or ""),
        str(trade.get("entry_time") or "")[:16],
        str(trade.get("strike") or ""),
        str(trade.get("opt_type") or ""),
    ])


def _holding_minutes(trade: dict) -> float:
    try:
        entry = datetime.fromisoformat(str(trade["entry_time"]))
        exit_ts = datetime.fromisoformat(str(trade["exit_time"]))
        return max(0.0, (exit_ts - entry).total_seconds() / 60.0)
    except Exception:
        return 0.0


def _drawdown_analysis(trades: list[dict]) -> dict[str, Any]:
    nets = [float(t["net_pnl"]) for t in trades]
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    current_duration = 0
    max_duration = 0
    drawdowns: list[float] = []
    underwater: list[dict[str, Any]] = []
    for idx, net in enumerate(nets, start=1):
        equity += net
        peak = max(peak, equity)
        dd = equity - peak
        drawdowns.append(dd)
        if dd < 0:
            current_duration += 1
        else:
            current_duration = 0
        max_duration = max(max_duration, current_duration)
        max_dd = min(max_dd, dd)
        trade = trades[idx - 1]
        underwater.append({
            "trade": idx,
            "day": trade.get("day"),
            "equity": round(equity, 2),
            "drawdown": round(dd, 2),
        })
    avg_drawdown = sum(drawdowns) / len(drawdowns) if drawdowns else 0.0
    net_pnl = sum(nets)
    recovery = net_pnl / abs(max_dd) if max_dd else (999.0 if net_pnl > 0 else 0.0)
    return {
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_duration_trades": max_duration,
        "average_drawdown": round(avg_drawdown, 2),
        "recovery_factor": round(recovery, 4),
        "return_to_mdd_ratio": round(recovery, 4),
        "calmar_proxy": round(recovery, 4),
        "underwater_curve": underwater,
    }


def _baseline_per_trade(strategy_trades: list[dict], baseline_trades: list[dict]) -> list[dict[str, Any]]:
    baseline_by_key = {_trade_key(t): t for t in baseline_trades}
    strategy_keys = {_trade_key(t) for t in strategy_trades}
    rows: list[dict[str, Any]] = []
    for trade in strategy_trades:
        key = _trade_key(trade)
        base = baseline_by_key.get(key)
        rows.append({
            "key": key,
            "day": trade.get("day"),
            "entry_time": trade.get("entry_time"),
            "strike": trade.get("strike"),
            "opt_type": trade.get("opt_type"),
            "strategy_net_pnl": round(float(trade.get("net_pnl") or 0.0), 2),
            "baseline_net_pnl": round(float(base.get("net_pnl") or 0.0), 2) if base else None,
            "delta": round(float(trade.get("net_pnl") or 0.0) - float(base.get("net_pnl") or 0.0), 2) if base else None,
            "matched": base is not None,
            "filter_decision": "taken",
        })
    for base in baseline_trades:
        key = _trade_key(base)
        if key in strategy_keys:
            continue
        rows.append({
            "key": key,
            "day": base.get("day"),
            "entry_time": base.get("entry_time"),
            "strike": base.get("strike"),
            "opt_type": base.get("opt_type"),
            "strategy_net_pnl": None,
            "baseline_net_pnl": round(float(base.get("net_pnl") or 0.0), 2),
            "delta": None,
            "matched": False,
            "filter_decision": "skipped_by_filter",
        })
    return rows


def _trade_quality(trades: list[dict], trade_journal: list[dict], baseline_per_trade: list[dict]) -> dict[str, Any]:
    exit_counts: dict[str, int] = {}
    for trade in trades:
        exit_counts[str(trade.get("exit_reason") or "UNKNOWN")] = exit_counts.get(str(trade.get("exit_reason") or "UNKNOWN"), 0) + 1
    winners = [t for t in trades if float(t.get("net_pnl") or 0.0) > 0]
    losers = [t for t in trades if float(t.get("net_pnl") or 0.0) <= 0]
    avg_win_hold = sum(_holding_minutes(t) for t in winners) / len(winners) if winners else 0.0
    avg_loss_hold = sum(_holding_minutes(t) for t in losers) / len(losers) if losers else 0.0
    avg_win = sum(float(t.get("net_pnl") or 0.0) for t in winners) / len(winners) if winners else 0.0
    avg_loss = abs(sum(float(t.get("net_pnl") or 0.0) for t in losers) / len(losers)) if losers else 0.0
    skipped_reasons: dict[str, int] = {}
    for row in trade_journal:
        if row.get("action") != "NO_TRADE":
            continue
        for reason in row.get("no_trade_reasons", []):
            skipped_reasons[str(reason)] = skipped_reasons.get(str(reason), 0) + 1
    skipped_baseline = [r for r in baseline_per_trade if r["filter_decision"] == "skipped_by_filter"]
    skipped_net = sum(float(r.get("baseline_net_pnl") or 0.0) for r in skipped_baseline)
    skipped_profitable = sum(1 for r in skipped_baseline if float(r.get("baseline_net_pnl") or 0.0) > 0)
    return {
        "exit_reason_distribution": exit_counts,
        "avg_holding_minutes": round(sum(_holding_minutes(t) for t in trades) / len(trades), 2) if trades else 0.0,
        "avg_winner_holding_minutes": round(avg_win_hold, 2),
        "avg_loser_holding_minutes": round(avg_loss_hold, 2),
        "payoff_ratio": round(avg_win / avg_loss, 4) if avg_loss else (999.0 if avg_win else 0.0),
        "profit_factor": _stats_from_trades(trades)["profit_factor"],
        "avg_mae": round(sum(float(t.get("mae") or 0.0) for t in trades) / len(trades), 2) if trades else 0.0,
        "avg_mfe": round(sum(float(t.get("mfe") or 0.0) for t in trades) / len(trades), 2) if trades else 0.0,
        "skipped_reason_counts": skipped_reasons,
        "skipped_baseline": {
            "candidates": len(skipped_baseline),
            "profitable": skipped_profitable,
            "win_rate": round(skipped_profitable / len(skipped_baseline) * 100, 2) if skipped_baseline else 0.0,
            "net_pnl": round(skipped_net, 2),
        },
    }


def _bucket_entry_time(value: str) -> str:
    try:
        ts = datetime.fromisoformat(value)
        bucket_min = (ts.minute // 30) * 30
        return f"{ts.hour:02d}:{bucket_min:02d}"
    except Exception:
        return "unknown"


def _duration_bucket(minutes: float) -> str:
    if minutes <= 15:
        return "0-15m"
    if minutes <= 30:
        return "15-30m"
    if minutes <= 60:
        return "30-60m"
    if minutes <= 120:
        return "60-120m"
    return "120m+"


def _timing_analysis(trades: list[dict]) -> dict[str, Any]:
    enriched = []
    for trade in trades:
        try:
            day_value = date.fromisoformat(str(trade["day"]))
            weekday = day_value.strftime("%A")
        except Exception:
            weekday = "unknown"
        expiry_bucket = "expiry_day" if trade.get("day") == trade.get("expiry") else "non_expiry_day"
        hold = _holding_minutes(trade)
        enriched.append({
            **trade,
            "weekday": weekday,
            "expiry_bucket": expiry_bucket,
            "entry_time_bucket": _bucket_entry_time(str(trade.get("entry_time") or "")),
            "holding_duration_bucket": _duration_bucket(hold),
        })
    return {
        "weekday": _summarize_by_key(enriched, "weekday"),
        "expiry": _summarize_by_key(enriched, "expiry_bucket"),
        "entry_time": _summarize_by_key(enriched, "entry_time_bucket"),
        "holding_duration": _summarize_by_key(enriched, "holding_duration_bucket"),
        "iv_regime": {"status": "unavailable_not_applied", "reason": "Historical IV rank/skew is not available in the current DB."},
    }


def _equity_drawdown_for_sequence(nets: list[float]) -> tuple[float, float]:
    equity = 0.0
    peak = 0.0
    mdd = 0.0
    for net in nets:
        equity += net
        peak = max(peak, equity)
        mdd = min(mdd, equity - peak)
    return equity, mdd


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, max(0, int(round((len(sorted_values) - 1) * pct))))
    return sorted_values[idx]


def _monte_carlo(trades: list[dict], runs: int = 2000) -> dict[str, Any]:
    nets = [float(t.get("net_pnl") or 0.0) for t in trades]
    if not nets:
        return {"runs": runs, "mdd_95": 0.0, "mdd_99": 0.0, "median_pnl": 0.0, "pnl_p05": 0.0, "pnl_p95": 0.0}
    rng = random.Random(42)
    pnls: list[float] = []
    drawdowns: list[float] = []
    for _ in range(runs):
        sample = [rng.choice(nets) for _ in nets]
        pnl, mdd = _equity_drawdown_for_sequence(sample)
        pnls.append(pnl)
        drawdowns.append(mdd)
    pnls.sort()
    drawdowns.sort()
    historical_pnl, historical_mdd = _equity_drawdown_for_sequence(nets)
    return {
        "runs": runs,
        "historical_pnl": round(historical_pnl, 2),
        "historical_mdd": round(historical_mdd, 2),
        "mdd_95": round(_percentile(drawdowns, 0.05), 2),
        "mdd_99": round(_percentile(drawdowns, 0.01), 2),
        "median_pnl": round(_percentile(pnls, 0.5), 2),
        "pnl_p05": round(_percentile(pnls, 0.05), 2),
        "pnl_p95": round(_percentile(pnls, 0.95), 2),
        "note": "Bootstrap resamples trade returns to show sequence and small-sample risk.",
    }


def _statistical_significance(trades: list[dict]) -> dict[str, Any]:
    nets = [float(t.get("net_pnl") or 0.0) for t in trades]
    n = len(nets)
    minimum = int(DEFAULT_QUALIFICATION_GATES["min_trades"])
    if n < 2:
        return {
            "trades": n,
            "t_statistic": 0.0,
            "p_value": 1.0,
            "mean_return": round(nets[0], 2) if nets else 0.0,
            "minimum_recommended_trades": minimum,
            "additional_trades_needed": max(0, minimum - n),
            "is_statistically_meaningful": False,
        }
    mean = sum(nets) / n
    variance = sum((x - mean) ** 2 for x in nets) / (n - 1)
    sd = math.sqrt(variance)
    t_stat = mean / (sd / math.sqrt(n)) if sd > 0 else 0.0
    p_value = math.erfc(abs(t_stat) / math.sqrt(2.0))
    return {
        "trades": n,
        "t_statistic": round(t_stat, 4),
        "p_value": round(p_value, 4),
        "mean_return": round(mean, 2),
        "minimum_recommended_trades": minimum,
        "additional_trades_needed": max(0, minimum - n),
        "is_statistically_meaningful": bool(n >= minimum and p_value < 0.05),
        "note": "Uses a normal approximation for the mean-return test; small samples should be treated as directional only.",
    }


def _sample_size_warning(stats: dict[str, Any]) -> dict[str, Any]:
    trades = int(stats.get("trades") or 0)
    minimum = int(DEFAULT_QUALIFICATION_GATES["min_trades"])
    if trades >= minimum:
        return {"level": "ok", "message": f"Sample size is at or above the {minimum}-trade research threshold.", "trades": trades}
    low = stats.get("win_rate_ci_low", 0.0)
    high = stats.get("win_rate_ci_high", 0.0)
    needed = minimum - trades
    return {
        "level": "warning",
        "trades": trades,
        "minimum_recommended_trades": minimum,
        "additional_trades_needed": needed,
        "message": f"Statistical warning: {trades} trades gives a win-rate confidence interval of [{low:.0f}%, {high:.0f}%] at 95% confidence. Run at least {needed} more trades before drawing strategy conclusions.",
    }


def _summarize_by_key(trades: list[dict], key: str) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict]] = {}
    for trade in trades:
        buckets.setdefault(str(trade.get(key) or "unknown"), []).append(trade)
    return [{"name": name, **{k: v for k, v in _stats_from_trades(items).items() if k != "equity_curve"}} for name, items in sorted(buckets.items())]


def _cost_sensitivity(trades: list[dict], cfg: OiStrategyConfig) -> list[dict[str, Any]]:
    costs = CostModel()
    out = []
    for multiplier in (0.0, 1.0, 2.0):
        recalculated = []
        for t in trades:
            raw_entry = float(t.get("raw_entry_price", t["entry_price"]))
            raw_exit = float(t.get("raw_exit_price", t["exit_price"]))
            _, _, gross, cost, net = _pnl_for_prices(
                t["underlying"],
                date.fromisoformat(t["expiry"]),
                raw_entry,
                raw_exit,
                int(t["qty"]),
                cfg,
                costs,
                multiplier,
            )
            recalculated.append({**t, "gross_pnl": round(gross, 2), "cost": round(cost, 2), "net_pnl": round(net, 2)})
        stats = _stats_from_trades(recalculated)
        out.append({"cost_multiplier": multiplier, "net_pnl": stats["net_pnl"], "profit_factor": stats["profit_factor"], "max_drawdown": stats["max_drawdown"]})
    return out


def _trade_identity(trade: dict) -> str:
    return "|".join([
        str(trade.get("entry_time") or ""),
        str(trade.get("strike") or ""),
        str(trade.get("opt_type") or ""),
        str(trade.get("signal_type") or ""),
    ])


def _qualification(stats: dict[str, Any], sig: dict[str, Any], gates: dict[str, float]) -> dict[str, Any]:
    trades = int(stats.get("trades") or 0)
    profit_factor = float(stats.get("profit_factor") or 0.0)
    p_value = float(sig.get("p_value") or 1.0)
    checks = {
        "p_value": p_value < float(gates["max_p_value"]),
        "profit_factor": profit_factor > float(gates["min_profit_factor"]),
        "trade_count": trades >= int(gates["min_trades"]),
    }
    return {
        "research_qualified": all(checks.values()),
        "checks": checks,
        "gates": {
            "max_p_value": float(gates["max_p_value"]),
            "min_profit_factor": float(gates["min_profit_factor"]),
            "min_trades": int(gates["min_trades"]),
        },
        "warning": "" if trades >= int(gates["min_trades"]) else f"{trades} trades is below the {int(gates['min_trades'])}-trade research threshold.",
    }


def _ablation_row(name: str, kind: str, active: list[str], result: dict[str, Any], gates: dict[str, float]) -> dict[str, Any]:
    stats = result.get("stats", {})
    sig = result.get("statistical_significance", {})
    mc = result.get("monte_carlo", {})
    quality = _qualification(stats, sig, gates)
    return {
        "config_id": name,
        "label": name.replace("_", " ").title(),
        "kind": kind,
        "active_factors": active,
        "trades": int(stats.get("trades") or 0),
        "net_pnl": float(stats.get("net_pnl") or 0.0),
        "win_rate": float(stats.get("win_rate") or 0.0),
        "profit_factor": float(stats.get("profit_factor") or 0.0),
        "sharpe": float(stats.get("sharpe") or 0.0),
        "sortino": float(stats.get("sortino") or 0.0),
        "t_statistic": float(sig.get("t_statistic") or 0.0),
        "p_value": float(sig.get("p_value") or 1.0),
        "max_drawdown": float(stats.get("max_drawdown") or 0.0),
        "recovery_factor": float(stats.get("recovery_factor") or 0.0),
        "monte_carlo_mdd_95": float(mc.get("mdd_95") or 0.0),
        "monte_carlo_mdd_99": float(mc.get("mdd_99") or 0.0),
        "research_qualified": quality["research_qualified"],
        "qualification": quality,
    }


def _rank_ablation_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda r: (
            not bool(r["research_qualified"]),
            float(r["p_value"]),
            -float(r["profit_factor"]),
            abs(float(r["max_drawdown"])),
            -float(r["net_pnl"]),
        ),
    )


def _paired_comparison(left: dict[str, Any], right: dict[str, Any], left_label: str, right_label: str) -> dict[str, Any]:
    left_by_key = {_trade_identity(t): t for t in left.get("trades", [])}
    right_by_key = {_trade_identity(t): t for t in right.get("trades", [])}
    overlap = sorted(set(left_by_key) & set(right_by_key))
    rows = []
    for key in overlap:
        l_net = float(left_by_key[key].get("net_pnl") or 0.0)
        r_net = float(right_by_key[key].get("net_pnl") or 0.0)
        rows.append({
            "key": key,
            "left_net_pnl": round(l_net, 2),
            "right_net_pnl": round(r_net, 2),
            "delta": round(l_net - r_net, 2),
        })
    return {
        "left": left_label,
        "right": right_label,
        "overlap_trades": len(rows),
        "left_only_trades": max(0, len(left_by_key) - len(rows)),
        "right_only_trades": max(0, len(right_by_key) - len(rows)),
        "overlap_delta_net_pnl": round(sum(float(r["delta"]) for r in rows), 2),
        "rows": rows[:200],
    }


def _research_verdict(full_row: dict[str, Any] | None, no_oi_row: dict[str, Any] | None, gates: dict[str, float]) -> dict[str, Any]:
    if not full_row or not no_oi_row:
        return {"verdict": "insufficient evidence", "detail": "Full-stack or no-OI-wall comparison is unavailable."}
    delta = float(full_row["net_pnl"]) - float(no_oi_row["net_pnl"])
    if int(full_row["trades"]) < int(gates["min_trades"]) and int(no_oi_row["trades"]) < int(gates["min_trades"]):
        return {
            "verdict": "insufficient evidence",
            "detail": f"Both key configs are below the {int(gates['min_trades'])}-trade threshold; do not allocate capital from this sample.",
            "full_minus_no_oi_net_pnl": round(delta, 2),
        }
    if delta > 0 and float(full_row["p_value"]) < float(gates["max_p_value"]):
        return {
            "verdict": "OI wall improves",
            "detail": "Adding OI wall improves net P&L and the full-stack mean return passes the p-value gate.",
            "full_minus_no_oi_net_pnl": round(delta, 2),
        }
    if delta < 0:
        return {
            "verdict": "OI wall hurts",
            "detail": "The full stack underperforms the same stack without OI wall; treat OI wall as a harmful or overly restrictive filter until proven otherwise.",
            "full_minus_no_oi_net_pnl": round(delta, 2),
        }
    return {
        "verdict": "insufficient evidence",
        "detail": "OI wall did not produce a statistically decisive improvement over the no-OI-wall stack.",
        "full_minus_no_oi_net_pnl": round(delta, 2),
    }


def _run_oi_ablation_study(
    underlying: str,
    start: date,
    end: date,
    expiry_offset: int,
    interval: int,
    cfg: OiStrategyConfig,
    mode: str,
    signal_indicators: list[Any] | None,
    entry_signal: Any,
    exit_signal: Any,
) -> dict[str, Any]:
    gates = dict(DEFAULT_QUALIFICATION_GATES)
    gates.update(cfg.qualification_gates or {})
    base_config = asdict(cfg)
    base_config["run_ablation_study"] = False
    all_factors = list(SUPPORTED_FACTORS)
    configs: list[tuple[str, str, list[str]]] = []
    for factor in all_factors:
        configs.append((f"standalone_{factor}", "standalone", [factor]))
    configs.append(("full_stack", "leave_one_out", all_factors))
    for factor in all_factors:
        configs.append((f"all_minus_{factor}", "leave_one_out", [f for f in all_factors if f != factor]))
    configs.append(("marginal_add_oi_to_non_oi_stack", "marginal", all_factors))

    raw_results: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for config_id, kind, active in configs:
        study_config = {
            **base_config,
            "active_factors": active,
            "required_factors": active,
            "run_ablation_study": False,
        }
        result = backtest_oi_strategy(
            underlying,
            start,
            end,
            expiry_offset=expiry_offset,
            interval=interval,
            config=study_config,
            mode=mode,
            signal_indicators=signal_indicators,
            entry_signal=entry_signal,
            exit_signal=exit_signal,
        )
        raw_results[config_id] = result
        rows.append(_ablation_row(config_id, kind, active, result, gates))

    full = next((r for r in rows if r["config_id"] == "full_stack"), None)
    no_oi = next((r for r in rows if r["config_id"] == "all_minus_oi_wall_unwinding"), None)
    trailing_rows: list[dict[str, Any]] = []
    for value in cfg.ablation_trailing_sl_values:
        trailing_config = {
            **base_config,
            "active_factors": all_factors,
            "required_factors": _clean_factor_list(cfg.required_factors, []),
            "trailing_sl_percent": float(value),
            "run_ablation_study": False,
        }
        result = backtest_oi_strategy(
            underlying,
            start,
            end,
            expiry_offset=expiry_offset,
            interval=interval,
            config=trailing_config,
            mode=mode,
            signal_indicators=signal_indicators,
            entry_signal=entry_signal,
            exit_signal=exit_signal,
        )
        row = _ablation_row(f"trailing_sl_{value:g}", "trailing_sl", all_factors, result, gates)
        row["trailing_sl_percent"] = float(value)
        trailing_rows.append(row)

    return {
        "gates": {
            "max_p_value": float(gates["max_p_value"]),
            "min_profit_factor": float(gates["min_profit_factor"]),
            "min_trades": int(gates["min_trades"]),
        },
        "rows": _rank_ablation_rows(rows),
        "factor_rows": _rank_ablation_rows(rows),
        "trailing_sl_study": _rank_ablation_rows(trailing_rows),
        "oi_marginal_contribution": {
            "full_stack_net_pnl": full["net_pnl"] if full else None,
            "no_oi_wall_net_pnl": no_oi["net_pnl"] if no_oi else None,
            "delta_net_pnl": round(float(full["net_pnl"]) - float(no_oi["net_pnl"]), 2) if full and no_oi else None,
            "full_stack_trades": full["trades"] if full else None,
            "no_oi_wall_trades": no_oi["trades"] if no_oi else None,
        },
        "paired_comparison": _paired_comparison(
            raw_results.get("full_stack", {}),
            raw_results.get("all_minus_oi_wall_unwinding", {}),
            "full_stack",
            "all_minus_oi_wall_unwinding",
        ),
        "research_verdict": _research_verdict(full, no_oi, gates),
    }


def backtest_oi_strategy(
    underlying: str,
    start: date,
    end: date,
    expiry_offset: int = 0,
    interval: int = 5,
    config: dict[str, Any] | None = None,
    mode: str = "historical",
    signal_indicators: list[Any] | None = None,
    entry_signal: Any = None,
    exit_signal: Any = None,
) -> dict:
    """Scan every N-minute candle, enter valid OI signals, and manage exits.

    One position at a time. Long-premium only, using the signal detector's ATM
    BUY CE/PE leg. Risk rules are premium SL, premium target, trailing SL, and
    force-exit time.
    """
    underlying = underlying.upper()
    cfg = _cfg(config)
    costs = CostModel()
    data_quality = _default_data_quality(mode)
    trades: list[dict] = []
    baseline_trades: list[dict] = []
    trade_journal: list[dict] = []
    daily: list[dict] = []
    no_trade_count = 0
    checked_bars = 0
    days = _trade_dates(underlying, start, end)

    for day in days:
        exp = _expiry_for_offset(underlying, day, expiry_offset)
        if exp is None:
            daily.append({"day": day.isoformat(), "trades": 0, "net_pnl": 0.0, "skip_reason": "no_expiry"})
            continue
        session_start, session_end = _session(day)
        spot_raw = storage.read_spot(underlying, session_start, session_end)
        options_raw = storage.read_options(underlying, session_start, session_end, expiry=exp)
        if spot_raw.is_empty() or options_raw.is_empty():
            daily.append({"day": day.isoformat(), "trades": 0, "net_pnl": 0.0, "skip_reason": "missing_spot_or_options"})
            continue

        spot = resample_spot(spot_raw, interval).sort("ts")
        opts = resample_options(options_raw, interval).sort("ts")
        times = spot.select("ts").unique().sort("ts")["ts"].to_list()
        has_entry_signal = bool(signal_indicators and _has_conditions(entry_signal))
        has_exit_signal = bool(signal_indicators and _has_conditions(exit_signal))
        signal_ctx = None
        if has_entry_signal or has_exit_signal:
            signal_ctx = signal_engine.build_context(
                signal_indicators or [],
                spot_raw,
                dte=max((exp - day).days, 0),
            )
        day_trades: list[dict] = []
        day_net = 0.0
        blocked_until: datetime | None = None
        baseline_blocked_until: datetime | None = None
        baseline_day_trades = 0
        daily_loss_limit = -abs(cfg.initial_capital * cfg.daily_loss_limit_percent / 100.0)

        for ts in times:
            if ts.time() < _first_eligible_entry_time(cfg):
                continue
            expiry_day = ts.date() == exp
            no_fresh_after = cfg.expiry_day_no_fresh_trade_after if expiry_day and cfg.expiry_day_tightening else cfg.no_fresh_trade_after
            if ts.time() > _parse_hm(no_fresh_after):
                continue
            if blocked_until and ts <= blocked_until:
                continue
            if len(day_trades) >= cfg.max_trades_per_day:
                break
            if day_net <= daily_loss_limit:
                trade_journal.append({
                    "day": day.isoformat(),
                    "timestamp": ts.isoformat(),
                    "action": "DAILY_LOSS_BREAKER",
                    "no_trade_reasons": [f"Daily loss breaker reached {day_net:.2f} <= {daily_loss_limit:.2f}"],
                })
                break
            checked_bars += 1
            sig = _analyze_prepared_frames(underlying, exp, spot, opts, ts, cfg, data_quality)
            if sig["signal_type"] not in ("BUY_CE", "BUY_PE") or not sig["suggested_legs"]:
                candidate_type = sig.get("candidate_signal_type")
                if (
                    candidate_type in ("BUY_CE", "BUY_PE")
                    and sig.get("atm_strike") is not None
                    and baseline_day_trades < cfg.max_trades_per_day
                    and (baseline_blocked_until is None or ts > baseline_blocked_until)
                ):
                    base_opt_type = "CE" if candidate_type == "BUY_CE" else "PE"
                    base_strike = int(sig["atm_strike"])
                    base_force_exit = cfg.expiry_day_force_exit_time if expiry_day and cfg.expiry_day_tightening else cfg.force_exit_time
                    base_marks = _option_marks(opts, base_strike, base_opt_type, ts, datetime.combine(day, _parse_hm(base_force_exit)))
                    if base_marks:
                        base_entry = base_marks[0]
                        base_exit_mark, base_exit_reason = _exit_from_marks(base_marks, float(base_entry["close"]), cfg, exp)
                        if base_exit_mark is not None:
                            base_qty = lot_size_for(underlying, exp)
                            base_entry_fill, base_exit_fill, base_gross, base_cost, base_net = _pnl_for_prices(
                                underlying,
                                exp,
                                float(base_entry["close"]),
                                float(base_exit_mark["close"]),
                                base_qty,
                                replace(cfg, execution_model="close"),
                                costs,
                                1.0,
                            )
                            baseline_trades.append({
                                "underlying": underlying,
                                "day": day.isoformat(),
                                "expiry": exp.isoformat(),
                                "entry_time": base_entry["ts"].isoformat(),
                                "exit_time": base_exit_mark["ts"].isoformat(),
                                "signal_type": candidate_type,
                                "strategy_name": "Naive ATM long premium baseline",
                                "score": sig.get("score", 0),
                                "strength": "BASELINE",
                                "strike": base_strike,
                                "opt_type": base_opt_type,
                                "qty": base_qty,
                                "entry_price": round(base_entry_fill, 2),
                                "exit_price": round(base_exit_fill, 2),
                                "raw_entry_price": round(float(base_entry["close"]), 2),
                                "raw_exit_price": round(float(base_exit_mark["close"]), 2),
                                "exit_reason": base_exit_reason,
                                "gross_pnl": round(base_gross, 2),
                                "cost": round(base_cost, 2),
                                "net_pnl": round(base_net, 2),
                                "entry_spot": sig.get("spot_price"),
                                "reasons": ["Naive baseline candidate; factor gate ignored"],
                                "factor_scores": sig.get("factor_scores", []),
                                "factor_coverage": sig.get("factor_coverage", {}),
                                "wall_strike": sig.get("entry_zone"),
                                "regime": sig.get("regime"),
                                "mae": round((min(float(m["close"]) for m in base_marks) - float(base_entry["close"])) * base_qty, 2),
                                "mfe": round((max(float(m["close"]) for m in base_marks) - float(base_entry["close"])) * base_qty, 2),
                            })
                            baseline_day_trades += 1
                            baseline_blocked_until = base_exit_mark["ts"] + timedelta(minutes=interval)
                no_trade_count += 1
                if sig.get("no_trade_reasons"):
                    trade_journal.append({
                        "day": day.isoformat(),
                        "timestamp": ts.isoformat(),
                        "action": "NO_TRADE",
                        "candidate_signal_type": sig.get("candidate_signal_type", "NO_TRADE"),
                        "score": sig.get("score", 0),
                        "factor_scores": sig.get("factor_scores", []),
                        "no_trade_reasons": sig.get("no_trade_reasons", []),
                        "regime": sig.get("regime"),
                    })
                continue

            opt_type = sig["suggested_legs"][0]["opt_type"]
            strike = int(sig["atm_strike"])
            signal_ts = datetime.fromisoformat(sig["timestamp"])
            if has_entry_signal:
                indicator_ok, indicator_reason = _signal_group_passes(entry_signal, signal_ctx, signal_ts)
                if not indicator_ok:
                    no_trade_count += 1
                    trade_journal.append({
                        "day": day.isoformat(),
                        "timestamp": signal_ts.isoformat(),
                        "action": "NO_TRADE",
                        "candidate_signal_type": sig.get("candidate_signal_type", sig.get("signal_type", "NO_TRADE")),
                        "score": sig.get("score", 0),
                        "factor_scores": sig.get("factor_scores", []),
                        "no_trade_reasons": [indicator_reason],
                        "regime": sig.get("regime"),
                    })
                    continue
            force_exit_time = cfg.expiry_day_force_exit_time if expiry_day and cfg.expiry_day_tightening else cfg.force_exit_time
            force_exit_dt = datetime.combine(day, _parse_hm(force_exit_time))
            marks = _option_marks(opts, strike, opt_type, signal_ts, force_exit_dt)
            if not marks:
                no_trade_count += 1
                continue
            entry = marks[0]
            raw_entry_price = float(entry["close"])
            exit_mark, exit_reason = _exit_from_marks(
                marks,
                raw_entry_price,
                cfg,
                exp,
                exit_signal=exit_signal if has_exit_signal else None,
                signal_ctx=signal_ctx,
            )
            if exit_mark is None:
                no_trade_count += 1
                continue
            raw_exit_price = float(exit_mark["close"])
            qty = _volatility_scaled_qty(underlying, exp, raw_entry_price, spot.filter(pl.col("ts") <= entry["ts"]), cfg)
            entry_price, exit_price, gross, cost, net = _pnl_for_prices(
                underlying, exp, raw_entry_price, raw_exit_price, qty, cfg, costs, 1.0
            )
            baseline_entry, baseline_exit, baseline_gross, baseline_cost, baseline_net = _pnl_for_prices(
                underlying, exp, raw_entry_price, raw_exit_price, qty, replace(cfg, execution_model="close"), costs, 1.0
            )
            trade = {
                "underlying": underlying,
                "day": day.isoformat(),
                "expiry": exp.isoformat(),
                "entry_time": entry["ts"].isoformat(),
                "exit_time": exit_mark["ts"].isoformat(),
                "signal_type": sig["signal_type"],
                "strategy_name": sig["strategy_name"],
                "score": sig["score"],
                "strength": sig["strength"],
                "strike": strike,
                "opt_type": opt_type,
                "qty": qty,
                "entry_price": round(entry_price, 2),
                "exit_price": round(exit_price, 2),
                "raw_entry_price": round(raw_entry_price, 2),
                "raw_exit_price": round(raw_exit_price, 2),
                "exit_reason": exit_reason,
                "gross_pnl": round(gross, 2),
                "cost": round(cost, 2),
                "net_pnl": round(net, 2),
                "entry_spot": sig.get("spot_price"),
                "reasons": sig.get("reasons", []),
                "factor_scores": sig.get("factor_scores", []),
                "factor_coverage": sig.get("factor_coverage", {}),
                "wall_strike": sig.get("entry_zone"),
                "regime": sig.get("regime"),
                "mae": round((min(float(m["close"]) for m in marks) - raw_entry_price) * qty, 2),
                "mfe": round((max(float(m["close"]) for m in marks) - raw_entry_price) * qty, 2),
            }
            baseline_trade = {
                **trade,
                "strategy_name": "Naive ATM long premium baseline",
                "entry_price": round(baseline_entry, 2),
                "exit_price": round(baseline_exit, 2),
                "gross_pnl": round(baseline_gross, 2),
                "cost": round(baseline_cost, 2),
                "net_pnl": round(baseline_net, 2),
            }
            trades.append(trade)
            baseline_trades.append(baseline_trade)
            baseline_day_trades += 1
            baseline_blocked_until = exit_mark["ts"] + timedelta(minutes=interval)
            day_trades.append(trade)
            day_net += float(trade["net_pnl"])
            trade_journal.append({
                "day": day.isoformat(),
                "timestamp": entry["ts"].isoformat(),
                "action": "TRADE",
                "signal_type": sig["signal_type"],
                "score": sig["score"],
                "wall_strike": sig.get("entry_zone"),
                "entry_price": trade["entry_price"],
                "exit_price": trade["exit_price"],
                "net_pnl": trade["net_pnl"],
                "cost": trade["cost"],
                "exit_reason": exit_reason,
                "factor_scores": sig.get("factor_scores", []),
                "no_trade_reasons": [],
                "regime": sig.get("regime"),
            })
            cooldown_bars = cfg.cooldown_after_loss_bars if net <= 0 else 1
            blocked_until = exit_mark["ts"] + timedelta(minutes=interval * max(cooldown_bars, 1))

        daily.append({
            "day": day.isoformat(),
            "trades": len(day_trades),
            "net_pnl": round(sum(float(t["net_pnl"]) for t in day_trades), 2),
            "skip_reason": "" if day_trades else "no_valid_signal",
        })

    stats = _stats_from_trades(trades)
    baseline_stats = _stats_from_trades(baseline_trades)
    baseline_per_trade = _baseline_per_trade(trades, baseline_trades)
    baseline_comparison = {
        "name": "Naive same-entry ATM long premium baseline",
        "stats": {k: v for k, v in baseline_stats.items() if k != "equity_curve"},
        "equity_curve": baseline_stats["equity_curve"],
        "per_trade": baseline_per_trade,
        "net_pnl_delta": round(stats["net_pnl"] - baseline_stats["net_pnl"], 2),
        "note": "Baseline buys the ATM CE/PE at candidate signal times while ignoring the factor score gate, using close-price fills.",
    }
    regime_summary = _summarize_by_key(trades, "regime")
    factor_summary = _summarize_by_key(
        [
            {**t, "factor_combo": ",".join(f["factor"] for f in t.get("factor_scores", []) if f.get("passed")) or "none"}
            for t in trades
        ],
        "factor_combo",
    )
    trade_days = sorted({t["day"] for t in trades})
    split = max(1, len(trade_days) // 3) if trade_days else 0
    walk_forward = []
    if trade_days:
        windows = [
            ("train", trade_days[:split]),
            ("validate", trade_days[split:split * 2]),
            ("test", trade_days[split * 2:]),
        ]
        for name, window_days in windows:
            items = [t for t in trades if t["day"] in set(window_days)]
            window_stats = _stats_from_trades(items)
            walk_forward.append({
                "window": name,
                "start": window_days[0] if window_days else None,
                "end": window_days[-1] if window_days else None,
                "stats": {k: v for k, v in window_stats.items() if k != "equity_curve"},
            })
    ablation = {}
    if cfg.run_ablation_study:
        ablation = _run_oi_ablation_study(
            underlying,
            start,
            end,
            expiry_offset,
            interval,
            cfg,
            mode,
            signal_indicators,
            entry_signal,
            exit_signal,
        )
    return {
        "underlying": underlying,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "interval": interval,
        "expiry_offset": expiry_offset,
        "stats": {k: v for k, v in stats.items() if k != "equity_curve"},
        "equity_curve": stats["equity_curve"],
        "trades": trades,
        "daily": daily,
        "checked_bars": checked_bars,
        "no_trade_bars": no_trade_count,
        "trade_journal": trade_journal,
        "baseline_comparison": baseline_comparison,
        "cost_sensitivity": _cost_sensitivity(trades, cfg),
        "drawdown_analysis": _drawdown_analysis(trades),
        "trade_quality": _trade_quality(trades, trade_journal, baseline_per_trade),
        "timing_analysis": _timing_analysis(trades),
        "monte_carlo": _monte_carlo(trades),
        "statistical_significance": _statistical_significance(trades),
        "sample_size_warning": _sample_size_warning(stats),
        "regime_summary": regime_summary,
        "factor_summary": factor_summary,
        "walk_forward_summary": walk_forward,
        "ablation_study": ablation.get("rows", []),
        "trailing_sl_study": ablation.get("trailing_sl_study", []),
        "oi_marginal_contribution": ablation.get("oi_marginal_contribution", {}),
        "paired_comparison": ablation.get("paired_comparison", {}),
        "research_verdict": ablation.get("research_verdict", {}),
        "ablation_gates": ablation.get("gates", {}),
        "data_quality": data_quality,
        "config": asdict(cfg),
    }

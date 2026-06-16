"""Strategy specification for multi-leg options backtests.

A strategy = N legs entered at entry_time, exited at exit_time or on SL/TP.
Strike selection per leg: ATM offset (steps), or nearest-premium, or delta.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from enum import Enum


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OptType(str, Enum):
    CE = "CE"
    PE = "PE"


class Selection(str, Enum):
    ATM = "ATM"            # value = strike offset in steps (e.g. +2, -1)
    PREMIUM = "PREMIUM"    # value = target premium, pick nearest strike
    DELTA = "DELTA"        # value = target delta (needs IV/greeks)


class Unit(str, Enum):
    """Units for TP/SL/Trail thresholds (AlgoTest parity)."""
    POINTS = "POINTS"            # premium points
    PERCENT = "PERCENT"          # % of entry premium
    UNDERLYING_PTS = "UND_PTS"   # underlying move -> premium via entry delta
    UNDERLYING_PCT = "UND_PCT"   # underlying move % -> premium via entry delta


@dataclass
class RiskRule:
    value: float
    unit: Unit = Unit.PERCENT


# Per-underlying contract specs (lot size + strike step). Extend as needed.
CONTRACT_SPECS: dict[str, dict] = {
    "NIFTY": {"lot_size": 75, "strike_step": 50},
    "BANKNIFTY": {"lot_size": 35, "strike_step": 100},
    "FINNIFTY": {"lot_size": 65, "strike_step": 50},
}


@dataclass
class Leg:
    action: Action
    opt_type: OptType
    selection: Selection = Selection.ATM
    value: float = 0           # meaning depends on selection
    lots: int = 1
    tp: RiskRule | None = None          # take-profit
    sl: RiskRule | None = None          # stop-loss
    trail_trigger: RiskRule | None = None   # start trailing once profit >= this
    trail_step: RiskRule | None = None      # tighten SL by this as profit grows


@dataclass
class StrategySpec:
    underlying: str
    legs: list[Leg]
    entry_time: time = time(9, 20)
    exit_time: time = time(15, 15)
    expiry_offset: int = 0
    # Portfolio-level exits (% of net entry premium; 0/None = disabled)
    target_pct: float | None = None
    stoploss_pct: float | None = None
    trailing_sl_pct: float | None = None
    sl_per_leg_pct: float | None = None
    # Entry filters
    entry_weekdays: list[int] | None = None   # None = all; [0..4] Mon..Fri
    min_pcr: float | None = None
    max_pcr: float | None = None
    min_iv_rank: float | None = None
    max_iv_rank: float | None = None
    use_vix_gate: bool = False
    vix_regimes: list[str] = field(default_factory=lambda: ["normal", "elevated"])
    indicator_type: str = ""
    indicator_params: dict = field(default_factory=dict)
    # Quantman-style named indicators + condition groups (optional)
    signal_indicators: list = field(default_factory=list)   # list[IndicatorDef]
    entry_signal: object | None = None                       # ConditionGroup | None
    exit_signal: object | None = None                        # ConditionGroup | None

    @property
    def spec(self) -> dict:
        return CONTRACT_SPECS[self.underlying]


def atm_strike(spot: float, step: int) -> int:
    return int(round(spot / step) * step)


def select_strike(spot: float, step: int, sel: Selection, value: float) -> int:
    if sel is Selection.ATM:
        return atm_strike(spot, step) + int(value) * step
    # PREMIUM / DELTA selection resolved in engine (needs option chain), fallback ATM
    return atm_strike(spot, step)

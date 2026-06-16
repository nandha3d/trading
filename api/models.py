from __future__ import annotations
from datetime import date
from typing import Optional
from pydantic import BaseModel, Field


class LegSpec(BaseModel):
    action: str = "SELL"
    opt_type: str = "CE"
    selection: str = "ATM"
    value: float = 0
    lots: int = 1
    sl_pct: Optional[float] = None
    sl_unit: str = "PERCENT"
    tp_pct: Optional[float] = None
    tp_unit: str = "PERCENT"


class ExitConditions(BaseModel):
    overall_sl_pct: float = 0.0       # % of net entry premium; 0 = disabled
    overall_target_pct: float = 0.0   # % of net entry premium; 0 = disabled
    trailing_sl_pct: float = 0.0      # % drop from peak profit; 0 = disabled
    force_exit_time: str = "15:20"    # HH:MM hard exit
    re_entry_after_sl: bool = False


class IndicatorEntry(BaseModel):
    type: str = ""           # "" | "EMA_CROSS" | "RSI" | "BOLLINGER" | "VWAP"
    ema_fast: int = 9
    ema_slow: int = 21
    ema_signal: str = "above"
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    bb_period: int = 20
    bb_std: float = 2.0
    bb_signal: str = "squeeze"
    vwap_signal: str = "above"


class EntryConditions(BaseModel):
    weekdays: list[int] = Field(default=[0, 1, 2, 3, 4])  # 0=Mon 4=Fri
    min_pcr: float = 0.0
    max_pcr: float = 0.0
    min_iv_rank: float = 0.0
    max_iv_rank: float = 0.0
    use_vix_gate: bool = False
    vix_regimes: list[str] = Field(default=["normal", "elevated"])
    indicator: IndicatorEntry = Field(default_factory=IndicatorEntry)


class IndicatorDef(BaseModel):
    """A named, parameterised indicator (Quantman-style 'Add Indicator')."""
    id: str = ""
    type: str = "EMA"        # SMA EMA RSI SUPERTREND MACD BOLLINGER VWAP ATR RANGE_BREAKOUT CURRENT_CANDLE
    name: str = ""           # user label referenced by conditions
    interval: int = 5        # candle interval (minutes)
    field: str = "close"     # source field on the underlying candle: close/open/high/low
    period: int = 14
    fast: int = 12
    slow: int = 26
    signal: int = 9
    multiplier: float = 2.0  # supertrend
    std: float = 2.0         # bollinger
    start_time: str = "09:30"  # range breakout window
    end_time: str = "10:30"


class Operand(BaseModel):
    """One side of a condition."""
    kind: str = "const"      # "indicator" | "candle" | "const"
    ref: str = ""            # indicator name (kind == indicator)
    sub: str = ""            # indicator sub-output: macd/signal/hist | upper/mid/lower | line/dir | hi/lo | value
    field: str = "close"     # candle field (kind == candle): close/open/high/low/volume/oi
    value: float = 0.0       # literal (kind == const)


class Condition(BaseModel):
    lhs: Operand
    op: str = ">"            # > < >= <= == cross_above cross_below
    rhs: Operand


class ConditionGroup(BaseModel):
    logic: str = "AND"       # AND | OR across conditions
    conditions: list[Condition] = Field(default_factory=list)


class BacktestRequest(BaseModel):
    underlying: str = "NIFTY"
    start: date
    end: date
    entry_time: str = "09:20"
    exit_time: str = "15:15"
    legs: list[LegSpec]
    expiry_offset: int = 0
    exit_conditions: ExitConditions = Field(default_factory=ExitConditions)
    entry_conditions: EntryConditions = Field(default_factory=EntryConditions)
    # Quantman-style indicator + condition engine (optional; empty = legacy behaviour)
    indicators: list[IndicatorDef] = Field(default_factory=list)
    entry_signal: Optional[ConditionGroup] = None
    exit_signal: Optional[ConditionGroup] = None


class LegResult(BaseModel):
    strike: int
    entry: float
    exit: float
    qty: int
    exit_reason: str
    action: str = "SELL"
    opt_type: str = "CE"
    exit_time: Optional[str] = None   # ISO timestamp the leg exited


class TradeResult(BaseModel):
    day: str
    gross: float
    cost: float
    net: float
    exit_reason: str
    legs: list[LegResult]
    entry_spot: float = 0.0
    skip_reason: str = ""
    vix: float = 0.0
    expiry: Optional[str] = None
    entry_time: Optional[str] = None  # ISO timestamp the trade entered


class StatsResult(BaseModel):
    trades: int
    win_rate: float
    net_pnl: float
    expectancy: float
    avg_win: float
    avg_loss: float
    max_drawdown: float
    sharpe: float


class BacktestResponse(BaseModel):
    stats: StatsResult
    trades: list[TradeResult]
    equity_curve: list[float]
    skipped_days: int = 0


# ---- Parametric grid sweep (entry-time x stop-loss%) ----

class GridRequest(BaseModel):
    underlying: str = "NIFTY"
    start: date
    end: date
    entry_start: str = "09:18"
    entry_end: str = "13:00"
    exit_time: str = "14:55"
    sl_lo: float = 10.0
    sl_hi: float = 100.0
    sl_step: float = 1.0
    entry_step_min: int = 1
    expiry_offset: int = 0
    lots: int = 1


class GridCellResult(BaseModel):
    entry_time: str
    sl_pct: float
    net: float
    gross: float
    cost: float
    trades: int
    wins: int
    win_rate: float
    avg: float
    max_dd: float


class GridResponse(BaseModel):
    cells: list[GridCellResult]
    entry_times: list[str]
    sl_values: list[float]
    best: Optional[GridCellResult] = None
    days_used: int = 0


# ---- Payoff Builder ----

class PayoffLegSpec(BaseModel):
    action: str = "SELL"
    opt_type: str = "CE"
    strike: int
    lots: int = 1
    entry_price: float
    underlying: str = "NIFTY"


class PayoffRequest(BaseModel):
    underlying: str = "NIFTY"
    spot: float
    expiry: str
    current_date: str
    legs: list[PayoffLegSpec]
    r: float = 0.065
    lot_size: Optional[int] = None   # client-supplied (from live chain); overrides default


class PayoffPoint(BaseModel):
    spot: float
    expiry_pnl: float
    today_pnl: float


class NetGreeks(BaseModel):
    delta: float
    gamma: float
    theta: float
    vega: float


class PayoffResponse(BaseModel):
    curve: list[PayoffPoint]
    breakevens: list[float]
    max_profit: Optional[float] = None   # None = unbounded (frontend shows "Unlimited")
    max_loss: Optional[float] = None     # None = unbounded
    net_premium: float
    net_greeks: NetGreeks


class SaveStrategyRequest(BaseModel):
    name: str
    underlying: str
    expiry: str
    legs: list[PayoffLegSpec]


class SavedStrategyResponse(BaseModel):
    id: str
    name: str
    underlying: str
    expiry: str
    created_at: str
    legs: list[PayoffLegSpec]


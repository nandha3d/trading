"""Performance metrics from a trade log / equity curve."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Stats:
    trades: int
    wins: int
    win_rate: float
    gross_pnl: float
    net_pnl: float
    avg_win: float
    avg_loss: float
    expectancy: float
    max_drawdown: float
    sharpe: float


def compute(daily_pnl: list[float], net_per_trade: list[float]) -> Stats:
    n = len(net_per_trade)
    wins = [p for p in net_per_trade if p > 0]
    losses = [p for p in net_per_trade if p <= 0]
    win_rate = len(wins) / n if n else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    expectancy = (sum(net_per_trade) / n) if n else 0.0

    # equity curve + max drawdown from daily pnl
    equity, peak, mdd = 0.0, 0.0, 0.0
    for p in daily_pnl:
        equity += p
        peak = max(peak, equity)
        mdd = min(mdd, equity - peak)

    # daily Sharpe annualized (~252 trading days)
    if len(daily_pnl) > 1:
        mean = sum(daily_pnl) / len(daily_pnl)
        var = sum((x - mean) ** 2 for x in daily_pnl) / (len(daily_pnl) - 1)
        sd = math.sqrt(var)
        sharpe = (mean / sd * math.sqrt(252)) if sd else 0.0
    else:
        sharpe = 0.0

    return Stats(
        trades=n,
        wins=len(wins),
        win_rate=win_rate,
        gross_pnl=sum(net_per_trade),
        net_pnl=sum(net_per_trade),
        avg_win=avg_win,
        avg_loss=avg_loss,
        expectancy=expectancy,
        max_drawdown=mdd,
        sharpe=sharpe,
    )

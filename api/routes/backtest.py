from __future__ import annotations
import asyncio
from datetime import time
from itertools import accumulate

from fastapi import APIRouter, HTTPException

from api.models import (BacktestRequest, BacktestResponse, GridCellResult, GridRequest,
                        GridResponse, LegResult, StatsResult, TradeResult)
from src.backtest import engine, grid
from src.backtest.strategy import Action, Leg, OptType, RiskRule, Selection, StrategySpec, Unit

router = APIRouter()

_ACTION = {"BUY": Action.BUY, "SELL": Action.SELL}
_OPT = {"CE": OptType.CE, "PE": OptType.PE}
_SEL = {"ATM": Selection.ATM, "PREMIUM": Selection.PREMIUM, "DELTA": Selection.DELTA}
_UNIT = {
    "POINTS": Unit.POINTS,
    "PERCENT": Unit.PERCENT,
    "UND_PTS": Unit.UNDERLYING_PTS,
    "UND_PCT": Unit.UNDERLYING_PCT,
}


def _build_and_run(req: BacktestRequest):
    try:
        eh, em = map(int, req.entry_time.split(":"))
        xh, xm = map(int, req.exit_time.split(":"))
    except ValueError:
        raise ValueError("invalid time format — use HH:MM")

    legs = []
    for ls in req.legs:
        sl = RiskRule(ls.sl_pct, _UNIT.get(ls.sl_unit, Unit.PERCENT)) if ls.sl_pct else None
        tp = RiskRule(ls.tp_pct, _UNIT.get(ls.tp_unit, Unit.PERCENT)) if ls.tp_pct else None
        legs.append(Leg(
            action=_ACTION.get(ls.action, Action.SELL),
            opt_type=_OPT.get(ls.opt_type, OptType.CE),
            selection=_SEL.get(ls.selection, Selection.ATM),
            value=ls.value,
            lots=ls.lots,
            sl=sl,
            tp=tp,
        ))

    ec = req.exit_conditions
    en = req.entry_conditions
    ind = en.indicator

    spec = StrategySpec(
        underlying=req.underlying,
        legs=legs,
        entry_time=time(eh, em),
        exit_time=time(xh, xm),
        expiry_offset=req.expiry_offset,
        target_pct=ec.overall_target_pct or None,
        stoploss_pct=ec.overall_sl_pct or None,
        trailing_sl_pct=ec.trailing_sl_pct or None,
        entry_weekdays=en.weekdays if set(en.weekdays) != {0,1,2,3,4} else None,
        min_pcr=en.min_pcr or None,
        max_pcr=en.max_pcr or None,
        min_iv_rank=en.min_iv_rank or None,
        max_iv_rank=en.max_iv_rank or None,
        use_vix_gate=en.use_vix_gate,
        vix_regimes=en.vix_regimes,
        indicator_type=ind.type,
        indicator_params={
            "ema_fast": ind.ema_fast, "ema_slow": ind.ema_slow, "ema_signal": ind.ema_signal,
            "rsi_period": ind.rsi_period, "rsi_oversold": ind.rsi_oversold,
            "rsi_overbought": ind.rsi_overbought, "bb_period": ind.bb_period,
            "bb_std": ind.bb_std, "bb_signal": ind.bb_signal, "vwap_signal": ind.vwap_signal,
        },
        signal_indicators=req.indicators,
        entry_signal=req.entry_signal,
        exit_signal=req.exit_signal,
    )
    return engine.run_range(spec, req.start, req.end)


@router.post("/backtest", response_model=BacktestResponse)
async def run_backtest(req: BacktestRequest):
    try:
        result = await asyncio.to_thread(_build_and_run, req)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"backtest error: {e}")

    s = result.stats
    skipped = [t for t in result.trades if t.skip_reason]
    executed = [t for t in result.trades if not t.skip_reason]

    trades_out = [
        TradeResult(
            day=t.day.isoformat(),
            gross=round(t.gross, 2),
            cost=round(t.cost, 2),
            net=round(t.net, 2),
            exit_reason=t.exit_reason,
            entry_spot=round(t.entry_spot, 2),
            skip_reason=t.skip_reason,
            vix=round(t.vix, 2),
            expiry=t.expiry.isoformat() if t.expiry else None,
            entry_time=t.entry_dt.isoformat() if t.entry_dt else None,
            legs=[
                LegResult(
                    strike=f.strike,
                    entry=round(f.entry, 2),
                    exit=round(f.exit, 2),
                    qty=f.qty,
                    exit_reason=f.exit_reason,
                    action=f.leg.action.value,
                    opt_type=f.leg.opt_type.value,
                    exit_time=f.exit_time.isoformat() if f.exit_time else None,
                )
                for f in t.legs
            ],
        )
        for t in result.trades
    ]
    equity = list(accumulate([0.0] + [t.net for t in executed]))

    return BacktestResponse(
        stats=StatsResult(
            trades=s.trades,
            win_rate=round(s.win_rate, 4),
            net_pnl=round(s.net_pnl, 2),
            expectancy=round(s.expectancy, 2),
            avg_win=round(s.avg_win, 2),
            avg_loss=round(s.avg_loss, 2),
            max_drawdown=round(s.max_drawdown, 2),
            sharpe=round(s.sharpe, 4),
        ),
        trades=trades_out,
        equity_curve=[round(v, 2) for v in equity],
        skipped_days=len(skipped),
    )


def _parse_hm(s: str) -> time:
    h, m = map(int, s.split(":"))
    return time(h, m)


def _run_grid(req: GridRequest) -> GridResponse:
    res = grid.run_straddle_grid(
        underlying=req.underlying,
        start=req.start,
        end=req.end,
        entry_start=_parse_hm(req.entry_start),
        entry_end=_parse_hm(req.entry_end),
        exit_time=_parse_hm(req.exit_time),
        sl_lo=req.sl_lo,
        sl_hi=req.sl_hi,
        sl_step=req.sl_step,
        entry_step_min=req.entry_step_min,
        expiry_offset=req.expiry_offset,
        lots=req.lots,
    )
    cells = [GridCellResult(**vars(c)) for c in res.cells]
    best = GridCellResult(**vars(res.best)) if res.best else None
    return GridResponse(
        cells=cells, entry_times=res.entry_times, sl_values=res.sl_values,
        best=best, days_used=res.days_used,
    )


@router.post("/backtest/grid", response_model=GridResponse)
async def run_grid(req: GridRequest):
    try:
        return await asyncio.to_thread(_run_grid, req)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"grid error: {e}")

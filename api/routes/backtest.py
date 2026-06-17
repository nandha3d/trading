from __future__ import annotations
import asyncio
import uuid
import json
import csv
import random
from io import StringIO
from datetime import date, time

from itertools import accumulate

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from api.models import (BacktestRequest, BacktestResponse, GridCellResult, GridRequest,
                        GridResponse, LegResult, StatsResult, TradeResult)
from src.backtest import engine, grid
from src.backtest.strategy import Action, Leg, OptType, RiskRule, Selection, StrategySpec, Unit
from src.data import storage

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
    run_id = f"bt_{uuid.uuid4().hex[:10]}"
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

    response_data = BacktestResponse(
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
        run_id=run_id
    )

    try:
        storage.save_backtest_run(
            run_id=run_id,
            strategy_id=None,
            request_json=req.json(),
            stats_json=response_data.json(),
            status="COMPLETED"
        )
        storage.log_audit_event("BACKTEST_RUN", "BACKTEST", run_id, {"net_pnl": s.net_pnl})
    except Exception as e:
        print(f"Error saving backtest run: {e}")

    return response_data


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


@router.post("/backtests", response_model=BacktestResponse)
async def run_and_save_backtest(req: BacktestRequest):
    run_id = f"bt_{uuid.uuid4().hex[:10]}"
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

    response_data = BacktestResponse(
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
        run_id=run_id
    )

    # Save to database
    try:
        storage.save_backtest_run(
            run_id=run_id,
            strategy_id=None,
            request_json=req.json(),
            stats_json=response_data.json(),
            status="COMPLETED"
        )
        storage.log_audit_event("BACKTEST_RUN", "BACKTEST", run_id, {"net_pnl": s.net_pnl})
    except Exception as e:
        print(f"Error saving backtest run: {e}")

    # For UI history tab, we want to expose the newly generated run_id, but the response schema is fixed.
    # So we'll save the run in DB, and frontend can check list of runs.
    return response_data


@router.get("/backtests/history")
async def get_backtest_history():
    try:
        return await asyncio.to_thread(storage.list_backtest_runs)
    except Exception as e:
        raise HTTPException(500, f"Failed to get history: {e}")


@router.post("/backtests/sweep", response_model=GridResponse)
async def run_sweep(req: GridRequest):
    return await run_grid(req)


@router.get("/backtests/{run_id}/analytics")
async def get_backtest_analytics(run_id: str):
    run = await asyncio.to_thread(storage.get_backtest_run, run_id)
    if not run:
        raise HTTPException(404, "Backtest run not found")
    
    stats_data = run.get("stats")
    if not stats_data:
        return {"message": "No statistics available"}
        
    trades = stats_data.get("trades", [])
    executed_trades = [t for t in trades if not t.get("skip_reason")]
    
    # 1. Monthly P&L
    monthly_pnl_map = {}
    for t in executed_trades:
        day_str = t.get("day")
        if day_str:
            dt = date.fromisoformat(day_str[:10])
            key = (dt.year, dt.month)
            monthly_pnl_map[key] = monthly_pnl_map.get(key, 0.0) + t.get("net", 0.0)
            
    monthly_pnl = [
        {"year": k[0], "month": k[1], "pnl": round(v, 2)}
        for k, v in sorted(monthly_pnl_map.items())
    ]
    
    # 2. Weekday P&L
    weekday_pnl_map = {}
    for t in executed_trades:
        day_str = t.get("day")
        if day_str:
            dt = date.fromisoformat(day_str[:10])
            wd = dt.weekday()
            weekday_pnl_map[wd] = weekday_pnl_map.get(wd, 0.0) + t.get("net", 0.0)
            
    weekday_pnl = [
        {"weekday": k, "pnl": round(v, 2)}
        for k, v in sorted(weekday_pnl_map.items())
    ]
    
    # 3. Exit Reason Distribution
    exit_reasons = {}
    for t in executed_trades:
        r = t.get("exit_reason", "UNKNOWN")
        exit_reasons[r] = exit_reasons.get(r, 0) + 1
        
    exit_reason_dist = [
        {"reason": k, "count": v}
        for k, v in exit_reasons.items()
    ]
    
    # 4. Drawdown Periods
    drawdown_periods = []
    equity = 0.0
    peak = 0.0
    peak_idx = -1
    for i, t in enumerate(executed_trades):
        equity += t.get("net", 0.0)
        if equity > peak:
            if peak_idx != -1 and peak - equity > 0:
                drawdown_periods.append({
                    "peak_idx": peak_idx,
                    "valley_idx": i,
                    "drawdown": round(peak - equity, 2)
                })
            peak = equity
            peak_idx = i
            
    # 5. Monte Carlo Simulation (5000 runs)
    pnl_vals = [t.get("net", 0.0) for t in executed_trades]
    mc_results = {}
    if len(pnl_vals) > 0:
        sim_pnls = []
        sim_drawdowns = []
        for _ in range(5000):
            sample = [random.choice(pnl_vals) for _ in range(len(pnl_vals))]
            sim_pnl = sum(sample)
            sim_pnls.append(sim_pnl)
            
            # max drawdown of sample
            eq = 0.0
            pk = 0.0
            mdd = 0.0
            for val in sample:
                eq += val
                pk = max(pk, eq)
                mdd = min(mdd, eq - pk)
            sim_drawdowns.append(mdd)
            
        sim_pnls.sort()
        sim_drawdowns.sort()
        
        loss_prob = sum(1 for p in sim_pnls if p < 0) / 5000.0
        mc_results = {
            "iterations": 5000,
            "confidence": 0.95,
            "worst_case_drawdown_95": round(sim_drawdowns[int(0.05 * 5000)], 2),
            "median_pnl": round(sim_pnls[2500], 2),
            "loss_probability": round(loss_prob, 4)
        }
        
    # 6. Overfitting warnings
    overfitting_warnings = []
    num_trades = len(executed_trades)
    
    # Too few trades
    if num_trades < 20:
        overfitting_warnings.append({
            "severity": "HIGH",
            "code": "SMALL_SAMPLE_SIZE",
            "message": f"Strategy has only {num_trades} trades. Results might not be statistically reliable."
        })
        
    # Profit concentration
    if num_trades >= 5:
        sorted_pnls = sorted(pnl_vals, reverse=True)
        top_3_sum = sum(sorted_pnls[:3])
        total_pnl = sum(pnl_vals)
        if total_pnl > 0 and (top_3_sum / total_pnl) > 0.70:
            overfitting_warnings.append({
                "severity": "MEDIUM",
                "code": "PROFIT_CONCENTRATION",
                "message": f"Over 70% of profit comes from top 3 trades. Strategy might be highly sensitive to single outsized moves."
            })
            
    # Too many conditions
    req_indicators = run.get("request", {}).get("indicators", [])
    if len(req_indicators) > 5 and num_trades < 40:
        overfitting_warnings.append({
            "severity": "HIGH",
            "code": "OVERFITTING_RISK",
            "message": f"Strategy has {len(req_indicators)} indicators with only {num_trades} trades. High risk of curve fitting."
        })
        
    return {
        "monthly_pnl": monthly_pnl,
        "weekday_pnl": weekday_pnl,
        "exit_reason_distribution": exit_reason_dist,
        "drawdown_periods": drawdown_periods,
        "monte_carlo": mc_results,
        "overfitting_warnings": overfitting_warnings
    }


@router.get("/backtests/{run_id}/export")
async def export_backtest_logs(run_id: str, format: str = "csv"):
    run = await asyncio.to_thread(storage.get_backtest_run, run_id)
    if not run or not run.get("stats"):
        raise HTTPException(404, "Backtest run stats not found")
        
    trades = run["stats"].get("trades", [])
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Headers
    writer.writerow([
        "Date", "Entry Time", "Exit Time", "Underlying Spot", 
        "Gross PnL", "Net PnL", "Charges", "Exit Reason", "Legs Count"
    ])
    
    for t in trades:
        writer.writerow([
            t.get("day", ""),
            t.get("entry_time", "") or "",
            t.get("legs", [{}])[0].get("exit_time", "") if t.get("legs") else "",
            t.get("entry_spot", 0.0),
            t.get("gross", 0.0),
            t.get("net", 0.0),
            t.get("cost", 0.0),
            t.get("exit_reason", ""),
            len(t.get("legs", []))
        ])
        
    output.seek(0)
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=backtest_{run_id}.csv"}
    )

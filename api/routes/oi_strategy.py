from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, HTTPException

from api.models import (
    OiStrategyBacktestRequest,
    OiStrategyBacktestResponse,
    OiStrategySignalRequest,
    OiStrategySignalResponse,
)
from src.analysis import oi_strategy as engine

router = APIRouter()


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    clean = value.replace("T", " ")
    if len(clean) == 16:
        clean = f"{clean}:00"
    return datetime.fromisoformat(clean)


def _detect(req: OiStrategySignalRequest) -> dict:
    interval = max(1, int(req.interval or 5))
    ts = _parse_timestamp(req.timestamp)
    return engine.analyze_oi_signal(
        underlying=req.underlying,
        day=req.date,
        expiry=req.expiry,
        timestamp=ts,
        interval=interval,
        config=req.config,
        mode=req.mode,
    )


def _backtest(req: OiStrategyBacktestRequest) -> dict:
    interval = max(1, int(req.interval or 5))
    if req.end < req.start:
        raise ValueError("end must be on or after start")
    return engine.backtest_oi_strategy(
        underlying=req.underlying,
        start=req.start,
        end=req.end,
        expiry_offset=req.expiry_offset,
        interval=interval,
        config=req.config,
        mode=req.mode,
    )


@router.post("/oi-strategy/signal", response_model=OiStrategySignalResponse)
async def detect_oi_strategy_signal(req: OiStrategySignalRequest):
    try:
        return await asyncio.to_thread(_detect, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OI strategy error: {e}")


@router.post("/oi-strategy/backtest", response_model=OiStrategyBacktestResponse)
async def run_oi_strategy_backtest(req: OiStrategyBacktestRequest):
    try:
        return await asyncio.to_thread(_backtest, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OI strategy backtest error: {e}")

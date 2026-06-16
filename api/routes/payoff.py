from __future__ import annotations
import asyncio
import uuid
import json
from datetime import date, datetime

from fastapi import APIRouter, HTTPException

from api.models import NetGreeks, PayoffPoint, PayoffRequest, PayoffResponse, SaveStrategyRequest, SavedStrategyResponse
from src.backtest.strategy import CONTRACT_SPECS
from src.data import storage
from src.data.options_math import bs_price, calculate_greeks, calculate_iv

router = APIRouter()

_DEFAULT_LOT = {"NIFTY": 75, "BANKNIFTY": 35, "FINNIFTY": 65}


def _lot_size(underlying: str) -> int:
    spec = CONTRACT_SPECS.get(underlying.upper())
    return spec["lot_size"] if spec else _DEFAULT_LOT.get(underlying.upper(), 25)


def _compute_payoff(req: PayoffRequest) -> PayoffResponse:
    exp_date = date.fromisoformat(req.expiry)
    cur_date = date.fromisoformat(req.current_date)
    dte_years = max((exp_date - cur_date).days, 0) / 365.0

    spot = req.spot
    r = req.r
    n_steps = 80
    pct_range = 0.12  # ±12% from spot
    spots = [spot * (1 - pct_range + 2 * pct_range * i / n_steps) for i in range(n_steps + 1)]

    # Per-leg: resolve IV from entry_price at current spot
    leg_ivs: list[float] = []
    for leg in req.legs:
        t = dte_years if dte_years > 0 else 1 / 365
        iv = calculate_iv(leg.entry_price, spot, leg.strike, t, r, leg.opt_type.upper())
        leg_ivs.append(max(iv, 0.05))  # floor at 5%

    curve: list[PayoffPoint] = []
    for s in spots:
        expiry_pnl = 0.0
        today_pnl = 0.0
        for leg, sigma in zip(req.legs, leg_ivs):
            lot = _lot_size(leg.underlying or req.underlying)
            qty = leg.lots * lot
            sign = -1 if leg.action.upper() == "SELL" else 1

            if leg.opt_type.upper() == "CE":
                intrinsic = max(0.0, s - leg.strike)
            else:
                intrinsic = max(0.0, leg.strike - s)

            expiry_pnl += sign * (intrinsic - leg.entry_price) * qty

            if dte_years > 0:
                mkt = bs_price(s, leg.strike, dte_years, r, sigma, leg.opt_type.upper())
            else:
                mkt = intrinsic
            today_pnl += sign * (mkt - leg.entry_price) * qty

        curve.append(PayoffPoint(
            spot=round(s, 2),
            expiry_pnl=round(expiry_pnl, 2),
            today_pnl=round(today_pnl, 2),
        ))

    # Breakevens: zero crossings in expiry curve
    expiry_vals = [p.expiry_pnl for p in curve]
    breakevens: list[float] = []
    for i in range(len(expiry_vals) - 1):
        p1, p2 = expiry_vals[i], expiry_vals[i + 1]
        if p1 * p2 <= 0 and p2 - p1 != 0:
            be = spots[i] + (0 - p1) * (spots[i + 1] - spots[i]) / (p2 - p1)
            breakevens.append(round(be, 2))

    max_profit = max(expiry_vals)
    max_loss = min(expiry_vals)

    net_premium = 0.0
    for leg in req.legs:
        lot = _lot_size(leg.underlying or req.underlying)
        qty = leg.lots * lot
        sign = 1 if leg.action.upper() == "SELL" else -1
        net_premium += sign * leg.entry_price * qty

    ng = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    t0 = dte_years if dte_years > 0 else 1 / 365
    for leg, sigma in zip(req.legs, leg_ivs):
        lot = _lot_size(leg.underlying or req.underlying)
        qty = leg.lots * lot
        sign = -1 if leg.action.upper() == "SELL" else 1
        g = calculate_greeks(spot, leg.strike, t0, r, sigma, leg.opt_type.upper())
        for k in ng:
            ng[k] += sign * g[k] * qty

    return PayoffResponse(
        curve=curve,
        breakevens=breakevens,
        max_profit=round(max_profit, 2),
        max_loss=round(max_loss, 2),
        net_premium=round(net_premium, 2),
        net_greeks=NetGreeks(**{k: round(v, 4) for k, v in ng.items()}),
    )


@router.post("/strategy/payoff", response_model=PayoffResponse)
async def get_payoff(req: PayoffRequest):
    try:
        return await asyncio.to_thread(_compute_payoff, req)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"payoff error: {e}")


def _save_strategy(req: SaveStrategyRequest):
    storage.init_db()
    con = storage.db().cursor()
    try:
        strategy_id = str(uuid.uuid4())
        created_at = datetime.now()
        legs_list = [leg.dict() for leg in req.legs]
        legs_json = json.dumps(legs_list)
        con.execute(
            "INSERT INTO saved_strategies (id, name, underlying, expiry, created_at, legs) VALUES (?, ?, ?, ?, ?, ?)",
            [strategy_id, req.name, req.underlying.upper(), date.fromisoformat(req.expiry), created_at, legs_json]
        )
        return {"id": strategy_id, "status": "success"}
    finally:
        con.close()


def _list_strategies():
    storage.init_db()
    con = storage.db().cursor()
    try:
        rows = con.execute("SELECT id, name, underlying, expiry, created_at, legs FROM saved_strategies ORDER BY created_at DESC").fetchall()
        out = []
        for r_id, name, underlying, expiry, created_at, legs_json in rows:
            out.append({
                "id": r_id,
                "name": name,
                "underlying": underlying,
                "expiry": expiry.isoformat() if hasattr(expiry, "isoformat") else str(expiry),
                "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
                "legs": json.loads(legs_json)
            })
        return out
    finally:
        con.close()


def _delete_strategy(strategy_id: str):
    storage.init_db()
    con = storage.db().cursor()
    try:
        con.execute("DELETE FROM saved_strategies WHERE id = ?", [strategy_id])
        return {"status": "success"}
    finally:
        con.close()


@router.post("/strategies/save")
async def save_strategy(req: SaveStrategyRequest):
    try:
        return await asyncio.to_thread(_save_strategy, req)
    except Exception as e:
        raise HTTPException(500, f"Failed to save strategy: {e}")


@router.get("/strategies/list", response_model=list[SavedStrategyResponse])
async def list_strategies():
    try:
        return await asyncio.to_thread(_list_strategies)
    except Exception as e:
        raise HTTPException(500, f"Failed to list strategies: {e}")


@router.delete("/strategies/{strategy_id}")
async def delete_strategy(strategy_id: str):
    try:
        return await asyncio.to_thread(_delete_strategy, strategy_id)
    except Exception as e:
        raise HTTPException(500, f"Failed to delete strategy: {e}")

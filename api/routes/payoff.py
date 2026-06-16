from __future__ import annotations
import asyncio
import uuid
import json
from datetime import date, datetime

from fastapi import APIRouter, HTTPException

from api.models import NetGreeks, PayoffPoint, PayoffRequest, PayoffResponse, SaveStrategyRequest, SavedStrategyResponse
from src.backtest.strategy import lot_size_for
from src.data import storage
from src.data.options_math import bs_price, calculate_greeks, calculate_iv

router = APIRouter()


def _lot_size(underlying: str, expiry: date | None = None) -> int:
    # date-aware (honours the 1 Jan 2026 NSE lot revision)
    return lot_size_for(underlying, expiry)


def _compute_payoff(req: PayoffRequest) -> PayoffResponse:
    if not req.legs:
        raise ValueError("No legs in request")
    if req.spot <= 0:
        raise ValueError("spot must be > 0")

    exp_date = date.fromisoformat(req.expiry)
    cur_date = date.fromisoformat(req.current_date)
    dte_years = max((exp_date - cur_date).days, 0) / 365.0

    def resolve_lot(u: str) -> int:
        # client-supplied lot (from live chain / broker scrip) wins for the
        # primary underlying; else date-aware default
        if req.lot_size and u.upper() == req.underlying.upper():
            return req.lot_size
        return _lot_size(u, exp_date)

    spot = req.spot
    r = req.r

    # Pre-resolve per-leg specs once: signed qty, IV, opt_type, strike, entry.
    legs_info = []
    for leg in req.legs:
        t = dte_years if dte_years > 0 else 1 / 365
        iv = calculate_iv(leg.entry_price, spot, leg.strike, t, r, leg.opt_type.upper())
        legs_info.append({
            "strike": float(leg.strike),
            "opt": leg.opt_type.upper(),
            "entry": leg.entry_price,
            "qty": leg.lots * resolve_lot(leg.underlying or req.underlying),
            "sign": -1 if leg.action.upper() == "SELL" else 1,
            "iv": min(max(iv, 0.05), 2.0),  # clamp 5%–200%
        })

    def expiry_pnl(s: float) -> float:
        """Exact piecewise-linear payoff at expiry (intrinsic only)."""
        total = 0.0
        for li in legs_info:
            if li["opt"] == "CE":
                intrinsic = max(0.0, s - li["strike"])
            else:
                intrinsic = max(0.0, li["strike"] - s)
            total += li["sign"] * (intrinsic - li["entry"]) * li["qty"]
        return total

    def today_pnl(s: float) -> float:
        """Theoretical P&L on the target date (Black-Scholes)."""
        total = 0.0
        for li in legs_info:
            if dte_years > 0:
                mkt = bs_price(s, li["strike"], dte_years, r, li["iv"], li["opt"])
            else:
                mkt = max(0.0, s - li["strike"]) if li["opt"] == "CE" else max(0.0, li["strike"] - s)
            total += li["sign"] * (mkt - li["entry"]) * li["qty"]
        return total

    # ---- chart curve: uniform grid + exact strike kinks (no sampling artifacts) ----
    n_steps = 100
    pct_range = 0.15  # ±15% from spot
    strikes = sorted({li["strike"] for li in legs_info})
    spots = [spot * (1 - pct_range + 2 * pct_range * i / n_steps) for i in range(n_steps + 1)]
    lo, hi = spots[0], spots[-1]
    for k in strikes:                       # land an exact sample on every kink
        if lo < k < hi:
            spots.append(k)
    spots = sorted(set(spots))

    curve = [
        PayoffPoint(spot=round(s, 2), expiry_pnl=round(expiry_pnl(s), 2),
                    today_pnl=round(today_pnl(s), 2))
        for s in spots
    ]

    # ---- analytic max profit / max loss (extrema of a piecewise-linear curve
    # occur only at kinks; unbounded sides are detected from the tail slope) ----
    min_k, max_k = strikes[0], strikes[-1]
    slope_below = expiry_pnl(min_k - 1.0) - expiry_pnl(min_k - 2.0)   # d/dS, S < all strikes
    slope_above = expiry_pnl(max_k + 2.0) - expiry_pnl(max_k + 1.0)   # d/dS, S > all strikes
    eps = 1e-6
    unbounded_profit = slope_below < -eps or slope_above > eps        # rises without limit
    unbounded_loss = slope_below > eps or slope_above < -eps          # falls without limit

    kink_pnls = [expiry_pnl(k) for k in strikes]
    max_profit = None if unbounded_profit else round(max(kink_pnls), 2)
    max_loss = None if unbounded_loss else round(min(kink_pnls), 2)

    # ---- breakevens: exact zero crossings (segments are linear, so interp is exact) ----
    breakevens: list[float] = []
    for i in range(len(curve) - 1):
        p1, p2 = curve[i].expiry_pnl, curve[i + 1].expiry_pnl
        if p1 == 0.0:
            breakevens.append(round(curve[i].spot, 2))
        elif p1 * p2 < 0:
            s1, s2 = curve[i].spot, curve[i + 1].spot
            breakevens.append(round(s1 + (0 - p1) * (s2 - s1) / (p2 - p1), 2))
    breakevens = sorted(set(breakevens))

    net_premium = sum(
        (1 if li["sign"] == -1 else -1) * li["entry"] * li["qty"] for li in legs_info
    )

    # ---- net Greeks at current spot ----
    ng = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    t0 = dte_years if dte_years > 0 else 1 / 365
    for li in legs_info:
        g = calculate_greeks(spot, li["strike"], t0, r, li["iv"], li["opt"])
        for k in ng:
            ng[k] += li["sign"] * g[k] * li["qty"]

    return PayoffResponse(
        curve=curve,
        breakevens=breakevens,
        max_profit=max_profit,
        max_loss=max_loss,
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

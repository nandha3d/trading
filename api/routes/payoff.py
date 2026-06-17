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

    req_exp_date = date.fromisoformat(req.expiry.split("T")[0].split(" ")[0])
    cur_date = date.fromisoformat(req.current_date.split("T")[0].split(" ")[0])

    def resolve_lot(u: str) -> int:
        # client-supplied lot (from live chain / broker scrip) wins for the
        # primary underlying; else date-aware default
        if req.lot_size and u.upper() == req.underlying.upper():
            return req.lot_size
        return _lot_size(u, req_exp_date)

    spot = req.spot
    r = req.r

    # Per-leg expiry: use leg.expiry if set, else fall back to req.expiry.
    # primary_exp = earliest leg expiry; used as the evaluation date for expiry_pnl.
    leg_exp_dates = [
        date.fromisoformat(leg.expiry.split("T")[0].split(" ")[0]) if leg.expiry else req_exp_date
        for leg in req.legs
    ]
    primary_exp = min(leg_exp_dates)
    is_multi_expiry = len(set(leg_exp_dates)) > 1

    # Pre-resolve per-leg specs once: signed qty, IV, DTE fields.
    legs_info = []
    for leg, leg_exp in zip(req.legs, leg_exp_dates):
        dte_today = max((leg_exp - cur_date).days, 0) / 365.0
        t = dte_today if dte_today > 0 else 1 / 365
        iv = calculate_iv(leg.entry_price, spot, leg.strike, t, r, leg.opt_type.upper())
        dte_primary = (leg_exp - primary_exp).days / 365.0  # remaining DTE at primary expiry
        legs_info.append({
            "strike": float(leg.strike),
            "opt": leg.opt_type.upper(),
            "entry": leg.entry_price,
            "qty": leg.lots * resolve_lot(leg.underlying or req.underlying),
            "sign": -1 if leg.action.upper() == "SELL" else 1,
            "iv": min(max(iv, 0.05), 2.0),
            "dte_today": dte_today,
            "dte_primary": dte_primary,
        })

    def expiry_pnl(s: float) -> float:
        """P&L at primary expiry (earliest leg expiry).
        Near legs → intrinsic. Far legs → BS with remaining DTE."""
        total = 0.0
        for li in legs_info:
            if li["dte_primary"] <= 0:
                val = max(0.0, s - li["strike"]) if li["opt"] == "CE" else max(0.0, li["strike"] - s)
            else:
                val = bs_price(s, li["strike"], li["dte_primary"], r, li["iv"], li["opt"])
            total += li["sign"] * (val - li["entry"]) * li["qty"]
        return total

    def today_pnl(s: float) -> float:
        """Theoretical P&L on the current/selected date (each leg at its own DTE)."""
        total = 0.0
        for li in legs_info:
            if li["dte_today"] > 0:
                mkt = bs_price(s, li["strike"], li["dte_today"], r, li["iv"], li["opt"])
            else:
                mkt = max(0.0, s - li["strike"]) if li["opt"] == "CE" else max(0.0, li["strike"] - s)
            total += li["sign"] * (mkt - li["entry"]) * li["qty"]
        return total

    # ---- chart curve: uniform grid + exact strike kinks (no sampling artifacts) ----
    n_steps = 100
    pct_range = 0.15  # ±15% from spot
    strikes = sorted({li["strike"] for li in legs_info})
    raw = [spot * (1 - pct_range + 2 * pct_range * i / n_steps) for i in range(n_steps + 1)]
    lo, hi = raw[0], raw[-1]
    raw += [k for k in strikes if lo < k < hi]   # land an exact sample on every kink
    spots = sorted({round(s, 2) for s in raw})

    curve = [
        PayoffPoint(spot=round(s, 2), expiry_pnl=round(expiry_pnl(s), 2),
                    today_pnl=round(today_pnl(s), 2))
        for s in spots
    ]

    # ---- max profit / max loss ----
    # Unbounded detection: tail slopes beyond outermost strike
    min_k, max_k = strikes[0], strikes[-1]
    slope_below = expiry_pnl(min_k - 1.0) - expiry_pnl(min_k - 2.0)
    slope_above = expiry_pnl(max_k + 2.0) - expiry_pnl(max_k + 1.0)
    eps = 1e-6
    unbounded_profit = slope_below < -eps or slope_above > eps
    unbounded_loss   = slope_below > eps  or slope_above < -eps

    if is_multi_expiry:
        # Far leg has BS value at primary_exp → curve is smooth, not piecewise-linear.
        # Use dense grid (all spots already include kinks) for extrema.
        expiry_vals = [p.expiry_pnl for p in curve]
        max_profit = None if unbounded_profit else round(max(expiry_vals), 2)
        max_loss   = None if unbounded_loss   else round(min(expiry_vals), 2)
    else:
        # Single expiry: piecewise-linear → extrema only at strike kinks (exact).
        kink_pnls = [expiry_pnl(k) for k in strikes]
        max_profit = None if unbounded_profit else round(max(kink_pnls), 2)
        max_loss   = None if unbounded_loss   else round(min(kink_pnls), 2)

    # ---- breakevens: exact zero crossings ----
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

    # ---- net Greeks at current spot (each leg at its own DTE from cur_date) ----
    ng = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for li in legs_info:
        t0 = li["dte_today"] if li["dte_today"] > 0 else 1 / 365
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



# Legacy strategy CRUD endpoints removed — now handled by api/routes/strategies.py


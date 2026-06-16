from __future__ import annotations
import asyncio
from datetime import date, datetime, time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from src.data import storage
from src.data.options_math import calculate_iv, calculate_greeks

RISK_FREE = 0.065
router = APIRouter()


class OptionData(BaseModel):
    close: Optional[float] = None
    volume: Optional[int] = None
    oi: Optional[int] = None
    iv: Optional[float] = None
    delta: Optional[float] = None
    theta: Optional[float] = None
    oi_change: Optional[int] = None


class OptionsChainRow(BaseModel):
    strike: int
    ce: Optional[OptionData] = None
    pe: Optional[OptionData] = None


class OptionsChainSummary(BaseModel):
    pcr: float
    max_pain: int
    total_ce_oi: int
    total_pe_oi: int


class OptionsChainResponse(BaseModel):
    underlying: str
    expiry: str
    timestamp: str
    spot_price: Optional[float] = None
    future_price: Optional[float] = None
    future_expiry: Optional[str] = None
    lot_size: Optional[int] = None
    chain: list[OptionsChainRow]
    summary: Optional[OptionsChainSummary] = None


def _dte_years(ts_dt: datetime, exp_date: date) -> float:
    exp_dt = datetime.combine(exp_date, time(15, 30))
    secs = max((exp_dt - ts_dt).total_seconds(), 60.0)
    return secs / (365.0 * 86400)


def _compute_max_pain(strikes_map: dict) -> int:
    """Strike where total payout to option buyers is minimized."""
    candidates = sorted(strikes_map.keys())
    if not candidates:
        return 0
    min_pain, best = float("inf"), candidates[0]
    for target in candidates:
        pain = 0
        for strike, data in strikes_map.items():
            ce_oi = data.get("ce_oi") or 0
            pe_oi = data.get("pe_oi") or 0
            if target > strike:
                pain += (target - strike) * ce_oi
            elif target < strike:
                pain += (strike - target) * pe_oi
        if pain < min_pain:
            min_pain, best = pain, target
    return best


def _get_trade_dates(underlying: str, expiry: str):
    storage.init_db()
    con = storage.db().cursor()
    try:
        und = underlying.upper()
        exp_date = date.fromisoformat(expiry)
        rows = con.execute(
            "SELECT DISTINCT CAST(ts AS DATE) d FROM options_1m WHERE underlying = ? AND expiry = ? ORDER BY d DESC",
            [und, exp_date],
        ).fetchall()
        return {"dates": [r[0].isoformat() for r in rows]}
    finally:
        con.close()


def _get_options_chain_data(underlying: str, expiry: str, ts: str):
    storage.init_db()
    con = storage.db().cursor()
    try:
        und = underlying.upper()
        exp_date = date.fromisoformat(expiry)

        ts_str = ts.replace("T", " ")
        try:
            ts_val = datetime.fromisoformat(ts_str)
        except ValueError:
            if len(ts_str) == 16:
                ts_val = datetime.fromisoformat(f"{ts_str}:00")
            else:
                raise ValueError("Invalid timestamp format")

        spot_row = con.execute(
            "SELECT close FROM spot_1m WHERE underlying = ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
            [und, ts_val],
        ).fetchone()
        spot_price: Optional[float] = spot_row[0] if spot_row else None

        options_rows = con.execute(
            """
            SELECT strike, option_type, close, volume, oi
            FROM options_1m
            WHERE underlying = ? AND expiry = ? AND ts = ?
            """,
            [und, exp_date, ts_val],
        ).fetchall()

        # OI at day open (for oi_change)
        day_date = ts_val.date()
        open_ts_row = con.execute(
            "SELECT MIN(ts) FROM options_1m WHERE underlying = ? AND expiry = ? AND CAST(ts AS DATE) = ?",
            [und, exp_date, day_date],
        ).fetchone()
        open_oi: dict[tuple, int] = {}
        if open_ts_row and open_ts_row[0]:
            open_rows = con.execute(
                "SELECT strike, option_type, oi FROM options_1m WHERE underlying = ? AND expiry = ? AND ts = ?",
                [und, exp_date, open_ts_row[0]],
            ).fetchall()
            for s, ot, oi in open_rows:
                open_oi[(s, ot)] = oi or 0
    finally:
        con.close()

    t_years = _dte_years(ts_val, exp_date)

    strikes_map: dict[int, dict] = {}
    for strike, opt_type, close, volume, oi in options_rows:
        if strike not in strikes_map:
            strikes_map[strike] = {"strike": strike, "ce": None, "pe": None,
                                   "ce_oi": 0, "pe_oi": 0}

        iv_val: Optional[float] = None
        delta_val: Optional[float] = None
        theta_val: Optional[float] = None
        if spot_price and close and close > 0 and t_years > 0:
            iv_val = calculate_iv(close, spot_price, strike, t_years, RISK_FREE, opt_type)
            if iv_val and iv_val > 0:
                g = calculate_greeks(spot_price, strike, t_years, RISK_FREE, iv_val, opt_type)
                delta_val = g["delta"]
                theta_val = g["theta"]
                iv_val = round(iv_val * 100, 2)  # as percentage

        oi_chg: Optional[int] = None
        if oi is not None:
            open_val = open_oi.get((strike, opt_type))
            if open_val is not None:
                oi_chg = (oi or 0) - open_val

        opt_data = OptionData(
            close=close, volume=volume, oi=oi,
            iv=iv_val, delta=delta_val, theta=theta_val,
            oi_change=oi_chg,
        )
        if opt_type == "CE":
            strikes_map[strike]["ce"] = opt_data
            strikes_map[strike]["ce_oi"] = oi or 0
        elif opt_type == "PE":
            strikes_map[strike]["pe"] = opt_data
            strikes_map[strike]["pe_oi"] = oi or 0

    chain = sorted(
        [OptionsChainRow(strike=v["strike"], ce=v["ce"], pe=v["pe"])
         for v in strikes_map.values()],
        key=lambda x: x.strike,
    )

    summary: Optional[OptionsChainSummary] = None
    if strikes_map:
        total_ce = sum(v["ce_oi"] for v in strikes_map.values())
        total_pe = sum(v["pe_oi"] for v in strikes_map.values())
        pcr = round(total_pe / total_ce, 3) if total_ce > 0 else 0.0
        mp = _compute_max_pain(strikes_map)
        summary = OptionsChainSummary(
            pcr=pcr, max_pain=mp,
            total_ce_oi=total_ce, total_pe_oi=total_pe,
        )

    return OptionsChainResponse(
        underlying=und, expiry=expiry, timestamp=ts,
        spot_price=spot_price, chain=chain, summary=summary,
    )


@router.get("/options-chain/dates/{underlying}/{expiry}")
async def get_trade_dates(underlying: str, expiry: str):
    try:
        return await asyncio.to_thread(_get_trade_dates, underlying, expiry)
    except ValueError:
        raise HTTPException(400, "Invalid expiry date format. Use YYYY-MM-DD.")
    except Exception as e:
        raise HTTPException(500, f"Database error: {e}")


@router.get("/options-chain/data", response_model=OptionsChainResponse)
async def get_options_chain_data(underlying: str, expiry: str, ts: str):
    try:
        return await asyncio.to_thread(_get_options_chain_data, underlying, expiry, ts)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Database error: {e}")


class PayoffLeg(BaseModel):
    action: str
    opt_type: str
    strike: int
    lots: int
    entry_price: float
    underlying: str


class PayoffRequest(BaseModel):
    underlying: str
    spot: float
    expiry: str
    current_date: str
    r: Optional[float] = 0.065
    legs: list[PayoffLeg]


class PayoffCurvePoint(BaseModel):
    spot: float
    expiry_pnl: float
    today_pnl: float


class PayoffResponse(BaseModel):
    curve: list[PayoffCurvePoint]
    breakevens: list[float]
    max_profit: Optional[float] = None
    max_loss: Optional[float] = None
    net_premium: float
    net_greeks: dict[str, float]


def _calculate_payoff(req: PayoffRequest) -> PayoffResponse:
    underlying = req.underlying.upper()
    spot = req.spot
    expiry_date = date.fromisoformat(req.expiry)
    current_dt = date.fromisoformat(req.current_date)
    r = req.r or 0.065
    
    # Calculate DTE in years
    days = (expiry_date - current_dt).days
    T_start = max(0.0001, days) / 365.0
    
    from src.backtest.strategy import lot_size_for
    from src.data.options_math import calculate_iv, calculate_greeks, bs_price

    # date-aware lot (honours 1 Jan 2026 NSE revision)
    lot_size = lot_size_for(underlying, expiry_date)
    
    legs_data = []
    net_premium = 0.0
    for leg in req.legs:
        qty = leg.lots * lot_size
        # Solve IV today
        iv = calculate_iv(leg.entry_price, spot, leg.strike, T_start, r, leg.opt_type)
        if iv <= 0:
            iv = 0.15  # Fallback to standard volatility
            
        g = calculate_greeks(spot, leg.strike, T_start, r, iv, leg.opt_type)
        
        legs_data.append({
            "leg": leg,
            "qty": qty,
            "iv": iv,
            "greeks": g
        })
        
        premium_val = leg.entry_price * qty
        if leg.action.upper() == "BUY":
            net_premium -= premium_val
        else:
            net_premium += premium_val
            
    # Generate payoff curve (±10% around spot)
    curve: list[PayoffCurvePoint] = []
    steps = 100
    low_spot = spot * 0.90
    high_spot = spot * 1.10
    step_size = (high_spot - low_spot) / steps
    
    for i in range(steps + 1):
        s_price = low_spot + i * step_size
        expiry_pnl = 0.0
        today_pnl = 0.0
        
        for item in legs_data:
            leg = item["leg"]
            qty = item["qty"]
            iv = item["iv"]
            
            # Expiry P&L
            if leg.opt_type.upper() == "CE":
                intrinsic = max(0.0, s_price - leg.strike)
            else:
                intrinsic = max(0.0, leg.strike - s_price)
                
            if leg.action.upper() == "BUY":
                leg_exp_pnl = (intrinsic - leg.entry_price) * qty
            else:
                leg_exp_pnl = (leg.entry_price - intrinsic) * qty
            expiry_pnl += leg_exp_pnl
            
            # Today/T+0 P&L
            new_price = bs_price(s_price, leg.strike, T_start, r, iv, leg.opt_type)
            if leg.action.upper() == "BUY":
                leg_today_pnl = (new_price - leg.entry_price) * qty
            else:
                leg_today_pnl = (leg.entry_price - new_price) * qty
            today_pnl += leg_today_pnl
            
        curve.append(PayoffCurvePoint(
            spot=round(s_price, 2),
            expiry_pnl=round(expiry_pnl, 2),
            today_pnl=round(today_pnl, 2)
        ))
        
    # Scan wider range for max profit, max loss, and breakevens
    scan_steps = 200
    scan_low = spot * 0.5
    scan_high = spot * 1.5
    scan_step = (scan_high - scan_low) / scan_steps
    
    scan_pnl = []
    for i in range(scan_steps + 1):
        s_price = scan_low + i * scan_step
        expiry_pnl = 0.0
        for item in legs_data:
            leg = item["leg"]
            qty = item["qty"]
            if leg.opt_type.upper() == "CE":
                intrinsic = max(0.0, s_price - leg.strike)
            else:
                intrinsic = max(0.0, leg.strike - s_price)
            if leg.action.upper() == "BUY":
                expiry_pnl += (intrinsic - leg.entry_price) * qty
            else:
                expiry_pnl += (leg.entry_price - intrinsic) * qty
        scan_pnl.append((s_price, expiry_pnl))
        
    # Determine if unlimited
    buy_ce_qty = sum(item["qty"] for item in legs_data if item["leg"].action.upper() == "BUY" and item["leg"].opt_type.upper() == "CE")
    sell_ce_qty = sum(item["qty"] for item in legs_data if item["leg"].action.upper() == "SELL" and item["leg"].opt_type.upper() == "CE")
    buy_pe_qty = sum(item["qty"] for item in legs_data if item["leg"].action.upper() == "BUY" and item["leg"].opt_type.upper() == "PE")
    sell_pe_qty = sum(item["qty"] for item in legs_data if item["leg"].action.upper() == "SELL" and item["leg"].opt_type.upper() == "PE")
    
    max_loss = None if (sell_ce_qty > buy_ce_qty or sell_pe_qty > buy_pe_qty) else round(min(p[1] for p in scan_pnl), 2)
    max_profit = None if (buy_ce_qty > sell_ce_qty or buy_pe_qty > sell_pe_qty) else round(max(p[1] for p in scan_pnl), 2)
    
    # Breakevens
    breakevens = []
    for i in range(len(scan_pnl) - 1):
        s1, p1 = scan_pnl[i]
        s2, p2 = scan_pnl[i+1]
        if (p1 <= 0 and p2 > 0) or (p1 > 0 and p2 <= 0):
            be = s1 + (0 - p1) * (s2 - s1) / (p2 - p1)
            breakevens.append(round(be, 2))
            
    # Portfolio Greeks
    net_greeks = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for item in legs_data:
        leg = item["leg"]
        qty = item["qty"]
        g = item["greeks"]
        mult = qty if leg.action.upper() == "BUY" else -qty
        net_greeks["delta"] += g["delta"] * mult
        net_greeks["gamma"] += g["gamma"] * mult
        net_greeks["theta"] += g["theta"] * mult
        net_greeks["vega"] += g["vega"] * mult
        
    for k in net_greeks:
        net_greeks[k] = round(net_greeks[k], 4)
        
    return PayoffResponse(
        curve=curve,
        breakevens=breakevens,
        max_profit=max_profit,
        max_loss=max_loss,
        net_premium=round(net_premium, 2),
        net_greeks=net_greeks
    )


@router.post("/strategy/payoff", response_model=PayoffResponse)
async def calculate_strategy_payoff(req: PayoffRequest):
    try:
        return await asyncio.to_thread(_calculate_payoff, req)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Payoff calculation error: {e}")

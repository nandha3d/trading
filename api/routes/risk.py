from __future__ import annotations
import asyncio
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.data import storage
from src.backtest.strategy import lot_size_for

router = APIRouter()

# --- Models ---
class RiskPrecheckLeg(BaseModel):
    action: str
    opt_type: str
    strike_offset: Optional[float] = 0.0
    sl_pct: Optional[float] = None
    lots: int = 1

class RiskPrecheckRequest(BaseModel):
    underlying: str
    legs: List[RiskPrecheckLeg]
    capital: float = 200000.0
    mode: str = "BACKTEST"

class RiskWarning(BaseModel):
    code: str
    severity: str
    message: str

class RiskPrecheckResponse(BaseModel):
    risk_score: int
    risk_level: str
    allowed: bool
    warnings: List[RiskWarning]
    required_confirmations: List[str]

class MarginLeg(BaseModel):
    action: str
    opt_type: str
    strike: int
    lots: int = 1
    entry_price: float = 100.0

class MarginEstimateRequest(BaseModel):
    underlying: str
    expiry: str
    legs: List[MarginLeg]

class MarginEstimateResponse(BaseModel):
    estimated_margin: float
    hedge_benefit: float
    margin_source: str
    note: str

class SlippageRow(BaseModel):
    slippage_pct: float
    net_pnl: float
    max_drawdown: float
    profit_factor: float

class SlippageResponse(BaseModel):
    rows: List[SlippageRow]

class KillSwitchRequest(BaseModel):
    scope: str = "ALL"
    reason: str = "Manual emergency stop"

class KillSwitchResponse(BaseModel):
    status: str
    stopped_strategies: int
    timestamp: str


def _calculate_margin(underlying: str, legs: List[MarginLeg]) -> MarginEstimateResponse:
    # Lot size
    lot_size = lot_size_for(underlying)
    
    total_buy_premium = 0.0
    naked_sell_margin = 0.0
    hedge_benefit = 0.0
    
    # Separate buy and sell legs
    buy_legs = [l for l in legs if l.action.upper() == "BUY"]
    sell_legs = [l for l in legs if l.action.upper() == "SELL"]
    
    for l in buy_legs:
        total_buy_premium += l.entry_price * l.lots * lot_size
        
    for l in sell_legs:
        # Naked sell margin approx 1.5L per lot
        leg_margin = 150000.0 * l.lots
        
        # Check if there is a corresponding hedge buy leg
        is_hedged = False
        for h in buy_legs:
            if h.opt_type.upper() == l.opt_type.upper():
                # Hedge condition:
                # CE: buy strike is higher than sell strike (limited risk)
                # PE: buy strike is lower than sell strike (limited risk)
                if (l.opt_type.upper() == "CE" and h.strike > l.strike) or \
                   (l.opt_type.upper() == "PE" and h.strike < l.strike):
                    is_hedged = True
                    break
        
        if is_hedged:
            # Hedged sell leg gets 70% margin discount
            discount = leg_margin * 0.70
            hedge_benefit += discount
            naked_sell_margin += (leg_margin - discount)
        else:
            naked_sell_margin += leg_margin
            
    estimated_margin = total_buy_premium + naked_sell_margin
    
    return MarginEstimateResponse(
        estimated_margin=round(estimated_margin, 2),
        hedge_benefit=round(hedge_benefit, 2),
        margin_source="internal_estimate",
        note="Use broker margin API before live order placement."
    )


@router.post("/risk/precheck", response_model=RiskPrecheckResponse)
async def risk_precheck(req: RiskPrecheckRequest):
    warnings = []
    required_confirmations = []
    allowed = True
    
    has_naked_sell = False
    has_sl = False
    
    buy_legs = [l for l in req.legs if l.action.upper() == "BUY"]
    sell_legs = [l for l in req.legs if l.action.upper() == "SELL"]
    
    for l in sell_legs:
        is_hedged = False
        for h in buy_legs:
            if h.opt_type.upper() == l.opt_type.upper():
                is_hedged = True
                break
        if not is_hedged:
            has_naked_sell = True
            
    for l in req.legs:
        if l.sl_pct is not None:
            has_sl = True
            
    # Warnings
    if has_naked_sell:
        warnings.append(RiskWarning(
            code="NAKED_OPTION_SELL",
            severity="HIGH",
            message="This strategy sells options without hedge legs."
        ))
        required_confirmations.append("I understand this strategy has naked option selling risk.")
        
    if not has_sl:
        warnings.append(RiskWarning(
            code="NO_STOPLOSS",
            severity="MEDIUM",
            message="No stop loss configured for option legs."
        ))
        required_confirmations.append("I acknowledge there is no defined stop loss rule.")
        
    # Capital vs estimated margin — block trade if insufficient
    margin_req = 150000.0 * len(sell_legs)
    # Apply hedge benefit (70% discount for hedged legs)
    for l in sell_legs:
        for h in buy_legs:
            if h.opt_type.upper() == l.opt_type.upper():
                margin_req -= 150000.0 * 0.70
                break
    margin_req = max(margin_req, 0)
    
    if req.capital < margin_req:
        warnings.append(RiskWarning(
            code="INSUFFICIENT_CAPITAL",
            severity="HIGH",
            message=f"Capital ₹{req.capital:,.0f} is less than estimated margin ₹{margin_req:,.0f}. Trade blocked."
        ))
        allowed = False  # Block the trade
        
    # Daily max loss enforcement
    daily_max_loss = req.capital * 0.03  # 3% of capital
    try:
        storage.init_db()
        today_pnl = storage.get_daily_pnl(datetime.now().date())
        if today_pnl is not None and today_pnl < -daily_max_loss:
            warnings.append(RiskWarning(
                code="DAILY_MAX_LOSS_BREACHED",
                severity="HIGH",
                message=f"Daily loss ₹{abs(today_pnl):,.0f} exceeds max daily loss limit ₹{daily_max_loss:,.0f}. New trades blocked."
            ))
            allowed = False
    except Exception:
        pass  # If daily PnL not available, skip
        
    # Max trades per day (limit: 10 trades)
    MAX_TRADES_PER_DAY = 10
    try:
        today_trade_count = storage.get_daily_trade_count(datetime.now().date())
        if today_trade_count >= MAX_TRADES_PER_DAY:
            warnings.append(RiskWarning(
                code="MAX_TRADES_EXCEEDED",
                severity="MEDIUM",
                message=f"Already placed {today_trade_count} trades today. Max limit is {MAX_TRADES_PER_DAY}."
            ))
            allowed = False
    except Exception:
        pass
        
    # Cooldown rule: prevent entry within 5 minutes of last exit
    COOLDOWN_SECONDS = 300
    try:
        last_exit = storage.get_last_trade_exit_time()
        if last_exit:
            elapsed = (datetime.now() - last_exit).total_seconds()
            if elapsed < COOLDOWN_SECONDS:
                remaining = int(COOLDOWN_SECONDS - elapsed)
                warnings.append(RiskWarning(
                    code="COOLDOWN_ACTIVE",
                    severity="LOW",
                    message=f"Cooldown active. Wait {remaining}s before next entry."
                ))
    except Exception:
        pass
        
    # Kill switch check
    try:
        if storage.is_kill_switch_active():
            warnings.append(RiskWarning(
                code="KILL_SWITCH_ACTIVE",
                severity="HIGH",
                message="Kill switch is active. All trading halted."
            ))
            allowed = False
    except Exception:
        pass
        
    # Risk Score
    score = 2
    if has_naked_sell:
        score += 3
    if not has_sl:
        score += 2
    if len(req.legs) > 4:
        score += 1
    if req.capital < 150000.0 and len(sell_legs) > 0:
        score += 2
        
    score = min(score, 10)
    
    if score <= 3:
        level = "LOW"
    elif score <= 6:
        level = "MEDIUM"
    elif score <= 8:
        level = "HIGH"
    else:
        level = "VERY_HIGH"
        
    return RiskPrecheckResponse(
        risk_score=score,
        risk_level=level,
        allowed=allowed,
        warnings=warnings,
        required_confirmations=required_confirmations
    )



@router.post("/risk/margin-estimate", response_model=MarginEstimateResponse)
async def margin_estimate(req: MarginEstimateRequest):
    try:
        return await asyncio.to_thread(_calculate_margin, req.underlying, req.legs)
    except Exception as e:
        raise HTTPException(500, f"Error estimating margin: {e}")


@router.post("/risk/slippage-sensitivity", response_model=SlippageResponse)
async def slippage_sensitivity(
    run_id: str = Query(...),
    slippage_values: List[float] = Query(default=[0.0, 0.01, 0.03, 0.05, 0.10])
):
    run = await asyncio.to_thread(storage.get_backtest_run, run_id)
    if not run or not run.get("stats"):
        raise HTTPException(404, "Backtest run not found")
        
    trades = run["stats"].get("trades", [])
    executed_trades = [t for t in trades if not t.get("skip_reason")]
    
    rows = []
    for slip in slippage_values:
        total_pnl = 0.0
        gross_profit = 0.0
        gross_loss = 0.0
        peak = 0.0
        mdd = 0.0
        
        for t in executed_trades:
            # Apply slippage costs to each trade
            original_net = t.get("net", 0.0)
            original_gross = t.get("gross", 0.0)
            original_cost = t.get("cost", 0.0)
            
            # Estimate additional slippage cost:
            # slippage_penalty = sum(entry_price * slip * qty) + sum(exit_price * slip * qty)
            slip_penalty = 0.0
            for leg in t.get("legs", []):
                qty = leg.get("qty", 1)
                entry = leg.get("entry", 0.0)
                exit = leg.get("exit", 0.0)
                slip_penalty += (entry * slip * qty) + (exit * slip * qty)
                
            net_after_slip = original_net - slip_penalty
            total_pnl += net_after_slip
            
            if net_after_slip > 0:
                gross_profit += net_after_slip
            else:
                gross_loss += abs(net_after_slip)
                
            peak = max(peak, total_pnl)
            mdd = min(mdd, total_pnl - peak)
            
        pf = (gross_profit / gross_loss) if gross_loss > 0.0 else gross_profit
        
        rows.append(SlippageRow(
            slippage_pct=slip,
            net_pnl=round(total_pnl, 2),
            max_drawdown=round(mdd, 2),
            profit_factor=round(pf, 3)
        ))
        
    return SlippageResponse(rows=rows)


@router.post("/risk/kill-switch", response_model=KillSwitchResponse)
async def kill_switch(req: KillSwitchRequest):
    storage.init_db()
    # Activate kill switch in database
    storage.activate_kill_switch(req.reason)
    # Log emergency override to audit trail
    storage.log_audit_event("KILL_SWITCH", "SYSTEM", None, {"scope": req.scope, "reason": req.reason})
    
    # Count active/recent strategies that would be stopped
    try:
        today_count = storage.get_daily_trade_count(datetime.now().date())
    except Exception:
        today_count = 0
    
    return KillSwitchResponse(
        status="STOPPED",
        stopped_strategies=today_count,
        timestamp=datetime.now().isoformat()
    )


@router.post("/risk/kill-switch/reset")
async def reset_kill_switch():
    """Deactivate the kill switch to resume trading."""
    storage.init_db()
    storage.deactivate_kill_switch()
    storage.log_audit_event("KILL_SWITCH_RESET", "SYSTEM", None)
    return {"status": "ACTIVE", "timestamp": datetime.now().isoformat()}


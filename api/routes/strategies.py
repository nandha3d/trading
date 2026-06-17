from __future__ import annotations
import asyncio
import uuid
import json
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.data import storage
from api.models import SavedStrategyResponse, PayoffLegSpec

router = APIRouter()

# --- Models ---
class StrategyLeg(BaseModel):
    action: str
    opt_type: str
    strike: int
    lots: int
    entry_price: float
    underlying: Optional[str] = None
    expiry: Optional[str] = None

class StrategySaveRequest(BaseModel):
    name: str
    underlying: str
    expiry: str
    legs: List[StrategyLeg]

class StrategyUpdateRequest(BaseModel):
    name: str
    underlying: str
    expiry: str
    legs: List[StrategyLeg]

class TemplateLeg(BaseModel):
    action: str
    opt_type: str
    selection: str
    value: float
    lots: int

class StrategyTemplate(BaseModel):
    template_id: str
    name: str
    description: str
    risk_level: str
    suitable_regime: List[str]
    legs: List[TemplateLeg]
    entry_time: str
    exit_time: str
    overall_sl_pct: Optional[float] = None
    overall_target_pct: Optional[float] = None

class ValidationIssue(BaseModel):
    field: str
    message: str

class ValidationResponse(BaseModel):
    valid: bool
    errors: List[ValidationIssue]
    warnings: List[ValidationIssue]

# Predefined templates
TEMPLATES = [
    StrategyTemplate(
        template_id="short_straddle",
        name="ATM Short Straddle",
        description="Sell ATM CE and PE with fixed SL and time exit",
        risk_level="HIGH",
        suitable_regime=["SIDEWAYS", "LOW_VOLATILITY"],
        legs=[
            TemplateLeg(action="SELL", opt_type="CE", selection="ATM", value=0, lots=1),
            TemplateLeg(action="SELL", opt_type="PE", selection="ATM", value=0, lots=1)
        ],
        entry_time="09:20",
        exit_time="15:15",
        overall_sl_pct=50.0,
        overall_target_pct=30.0
    ),
    StrategyTemplate(
        template_id="short_strangle",
        name="OTM Short Strangle",
        description="Sell OTM CE and PE options to collect premium in range-bound market",
        risk_level="HIGH",
        suitable_regime=["SIDEWAYS"],
        legs=[
            TemplateLeg(action="SELL", opt_type="CE", selection="ATM", value=2.0, lots=1),  # value=2 means ATM + 2 strikes
            TemplateLeg(action="SELL", opt_type="PE", selection="ATM", value=-2.0, lots=1)
        ],
        entry_time="09:30",
        exit_time="15:15",
        overall_sl_pct=50.0,
        overall_target_pct=25.0
    ),
    StrategyTemplate(
        template_id="iron_condor",
        name="Iron Condor",
        description="Hedged option selling strategy with limited risk and limited profit",
        risk_level="MEDIUM",
        suitable_regime=["SIDEWAYS", "LOW_VOLATILITY"],
        legs=[
            TemplateLeg(action="SELL", opt_type="CE", selection="ATM", value=2.0, lots=1),
            TemplateLeg(action="SELL", opt_type="PE", selection="ATM", value=-2.0, lots=1),
            TemplateLeg(action="BUY", opt_type="CE", selection="ATM", value=4.0, lots=1),
            TemplateLeg(action="BUY", opt_type="PE", selection="ATM", value=-4.0, lots=1)
        ],
        entry_time="09:30",
        exit_time="15:15",
        overall_sl_pct=30.0,
        overall_target_pct=20.0
    ),
    StrategyTemplate(
        template_id="bull_call_spread",
        name="Bull Call Spread",
        description="Directional bullish spread buying ITM/ATM CE and selling OTM CE",
        risk_level="LOW",
        suitable_regime=["BULLISH_TREND"],
        legs=[
            TemplateLeg(action="BUY", opt_type="CE", selection="ATM", value=0, lots=1),
            TemplateLeg(action="SELL", opt_type="CE", selection="ATM", value=2.0, lots=1)
        ],
        entry_time="09:20",
        exit_time="15:15"
    ),
    StrategyTemplate(
        template_id="bear_put_spread",
        name="Bear Put Spread",
        description="Directional bearish spread buying ITM/ATM PE and selling OTM PE",
        risk_level="LOW",
        suitable_regime=["BEARISH_TREND"],
        legs=[
            TemplateLeg(action="BUY", opt_type="PE", selection="ATM", value=0, lots=1),
            TemplateLeg(action="SELL", opt_type="PE", selection="ATM", value=-2.0, lots=1)
        ],
        entry_time="09:20",
        exit_time="15:15"
    )
]

def _save_strategy(req: StrategySaveRequest) -> Dict[str, Any]:
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
        storage.log_audit_event("STRATEGY_CREATE", "STRATEGY", strategy_id, {"name": req.name})
        return {"id": strategy_id, "status": "success"}
    finally:
        con.close()

def _update_strategy(strategy_id: str, req: StrategyUpdateRequest) -> Dict[str, Any]:
    storage.init_db()
    con = storage.db().cursor()
    try:
        legs_list = [leg.dict() for leg in req.legs]
        legs_json = json.dumps(legs_list)
        con.execute(
            "UPDATE saved_strategies SET name = ?, underlying = ?, expiry = ?, legs = ? WHERE id = ?",
            [req.name, req.underlying.upper(), date.fromisoformat(req.expiry), legs_json, strategy_id]
        )
        storage.log_audit_event("STRATEGY_UPDATE", "STRATEGY", strategy_id, {"name": req.name})
        return {"status": "success"}
    finally:
        con.close()

def _delete_strategy(strategy_id: str) -> Dict[str, Any]:
    storage.init_db()
    con = storage.db().cursor()
    try:
        con.execute("DELETE FROM saved_strategies WHERE id = ?", [strategy_id])
        storage.log_audit_event("STRATEGY_DELETE", "STRATEGY", strategy_id)
        return {"status": "success"}
    finally:
        con.close()

def _clone_strategy(strategy_id: str) -> Dict[str, Any]:
    storage.init_db()
    con = storage.db().cursor()
    try:
        row = con.execute(
            "SELECT name, underlying, expiry, legs FROM saved_strategies WHERE id = ?",
            [strategy_id]
        ).fetchone()
        if not row:
            raise HTTPException(404, "Strategy not found")
        name, underlying, expiry, legs_json = row
        new_id = str(uuid.uuid4())
        con.execute(
            "INSERT INTO saved_strategies (id, name, underlying, expiry, created_at, legs) VALUES (?, ?, ?, ?, ?, ?)",
            [new_id, f"Copy of {name}", underlying, expiry, datetime.now(), legs_json]
        )
        storage.log_audit_event("STRATEGY_CLONE", "STRATEGY", new_id, {"source_id": strategy_id})
        return {"id": new_id, "status": "success"}
    finally:
        con.close()

def _list_strategies() -> List[SavedStrategyResponse]:
    storage.init_db()
    con = storage.db().cursor()
    try:
        rows = con.execute("SELECT id, name, underlying, expiry, created_at, legs FROM saved_strategies ORDER BY created_at DESC").fetchall()
        out = []
        for r_id, name, underlying, expiry, created_at, legs_json in rows:
            out.append(SavedStrategyResponse(
                id=r_id,
                name=name,
                underlying=underlying,
                expiry=expiry.isoformat() if hasattr(expiry, "isoformat") else str(expiry),
                created_at=created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
                legs=[PayoffLegSpec(**l) for l in json.loads(legs_json)]
            ))
        return out
    finally:
        con.close()

@router.get("/strategies/templates", response_model=Dict[str, List[StrategyTemplate]])
async def get_templates():
    return {"templates": TEMPLATES}

@router.post("/strategies/validate", response_model=ValidationResponse)
async def validate_strategy(req: Dict[str, Any]):
    errors = []
    warnings = []
    
    legs = req.get("legs", [])
    underlying = req.get("underlying")
    
    if not legs:
        errors.append(ValidationIssue(field="legs", message="Strategy must have at least one leg"))
        
    for i, leg in enumerate(legs):
        action = leg.get("action")
        opt_type = leg.get("opt_type")
        if action not in ["BUY", "SELL"]:
            errors.append(ValidationIssue(field=f"legs[{i}].action", message="Action must be BUY or SELL"))
        if opt_type not in ["CE", "PE"]:
            errors.append(ValidationIssue(field=f"legs[{i}].opt_type", message="Option type must be CE or PE"))
            
    # Warnings check
    has_sl = False
    has_naked_sell = False
    
    for leg in legs:
        if leg.get("sl_pct") or leg.get("sl"):
            has_sl = True
        if leg.get("action") == "SELL":
            # Check if there is an offsetting BUY leg of same option type
            is_hedged = False
            for hedge in legs:
                if hedge.get("action") == "BUY" and hedge.get("opt_type") == leg.get("opt_type"):
                    is_hedged = True
                    break
            if not is_hedged:
                has_naked_sell = True
                
    if not has_sl:
        warnings.append(ValidationIssue(field="exit_conditions", message="No stop loss configured for legs or overall portfolio"))
    if has_naked_sell:
        warnings.append(ValidationIssue(field="legs", message="Strategy contains naked option selling legs. Margin requirement will be high."))
        
    return ValidationResponse(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings
    )

@router.post("/strategies")
async def create_strategy(req: StrategySaveRequest):
    try:
        return await asyncio.to_thread(_save_strategy, req)
    except Exception as e:
        raise HTTPException(500, f"Failed to save strategy: {e}")

@router.get("/strategies", response_model=List[SavedStrategyResponse])
async def list_strategies():
    try:
        return await asyncio.to_thread(_list_strategies)
    except Exception as e:
        raise HTTPException(500, f"Failed to list strategies: {e}")

@router.put("/strategies/{strategy_id}")
async def update_strategy(strategy_id: str, req: StrategyUpdateRequest):
    try:
        return await asyncio.to_thread(_update_strategy, strategy_id, req)
    except Exception as e:
        raise HTTPException(500, f"Failed to update strategy: {e}")

@router.delete("/strategies/{strategy_id}")
async def delete_strategy(strategy_id: str):
    try:
        return await asyncio.to_thread(_delete_strategy, strategy_id)
    except Exception as e:
        raise HTTPException(500, f"Failed to delete strategy: {e}")

@router.post("/strategies/{strategy_id}/clone")
async def clone_strategy(strategy_id: str):
    try:
        return await asyncio.to_thread(_clone_strategy, strategy_id)
    except Exception as e:
        raise HTTPException(500, f"Failed to clone strategy: {e}")

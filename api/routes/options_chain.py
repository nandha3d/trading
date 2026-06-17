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



@router.get("/options-chain/expiries-for-date")
async def expiries_for_date(underlying: str, date: str):
    """Return expiries that have options data for the given date. Used for auto-expiry."""
    def _query():
        storage.init_db()
        con = storage.db().cursor()
        try:
            rows = con.execute(
                "SELECT DISTINCT expiry FROM options_1m WHERE underlying=? AND ts::DATE=? ORDER BY expiry",
                [underlying.upper(), date],
            ).fetchall()
            return {"expiries": [r[0].isoformat() for r in rows]}
        finally:
            con.close()
    try:
        return await asyncio.to_thread(_query)
    except Exception as e:
        raise HTTPException(500, str(e))

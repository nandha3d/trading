"""FlowMatrix API — Connecting Dots + OI Analysis screens.

GET /api/dots                    -> per-interval confluence rows
GET /api/oi-analysis             -> per-strike Call/Put OI interpretation rows
GET /api/oi-analysis/expiries    -> expiries that traded on a date
GET /api/oi-analysis/strikes     -> strikes that traded for an expiry on a date
GET /api/flow/dates              -> trading dates available for an underlying
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query

import calendar
from datetime import date as _date, datetime as _dt

from src.analysis import connecting_dots as cd
from src.analysis import oi_analysis as oia
from src.analysis import oi_tools as oit
from src.analysis.resample import resample_spot
from src.data import storage

router = APIRouter()


@router.get("/dots")
async def get_dots(
    underlying: str = Query(...),
    date: str = Query(..., description="ISO date YYYY-MM-DD"),
    interval: int = Query(3),
    mode: str = Query("historical"),
):
    try:
        return await asyncio.to_thread(cd.build_dots, underlying, date, interval, mode)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/oi-analysis")
async def get_oi_analysis(
    underlying: str = Query(...),
    date: str = Query(...),
    expiry: str = Query(...),
    strike: int = Query(...),
    interval: int = Query(60),
    mode: str = Query("historical"),
):
    try:
        return await asyncio.to_thread(
            oia.build_oi_analysis, underlying, date, expiry, strike, interval, mode
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def _candles(underlying: str, day_iso: str, interval: int) -> list[dict]:
    day = _date.fromisoformat(day_iso)
    start = _dt(day.year, day.month, day.day, 9, 15)
    end = _dt(day.year, day.month, day.day, 15, 30)
    df = storage.read_spot(underlying.upper(), start, end)
    if df.is_empty():
        return []
    sp = resample_spot(df, interval).sort("ts")
    out = []
    for r in sp.iter_rows(named=True):
        ts = r["ts"]
        # treat naive IST clock as UTC epoch so the time axis shows 09:15..15:30
        epoch = calendar.timegm(ts.timetuple())
        out.append({
            "time": int(epoch),
            "open": round(float(r["open"]), 2),
            "high": round(float(r["high"]), 2),
            "low": round(float(r["low"]), 2),
            "close": round(float(r["close"]), 2),
            "volume": int(r["volume"] or 0),
        })
    return out


@router.get("/chart/candles")
async def get_chart_candles(
    underlying: str = Query(...),
    date: str = Query(...),
    interval: int = Query(5),
):
    try:
        candles = await asyncio.to_thread(_candles, underlying, date, interval)
        return {"underlying": underlying.upper(), "date": date,
                "interval": interval, "candles": candles}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/oi-tools")
async def get_oi_tools(
    underlying: str = Query(...),
    date: str = Query(...),
    expiry: str = Query(...),
    interval: int = Query(15),
):
    try:
        return await asyncio.to_thread(oit.build_oi_tools, underlying, date, expiry, interval)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/oi-analysis/expiries")
async def get_oia_expiries(underlying: str = Query(...), date: str = Query(...)):
    try:
        return {"expiries": await asyncio.to_thread(oia.expiries_on, underlying, date)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/oi-analysis/strikes")
async def get_oia_strikes(
    underlying: str = Query(...), date: str = Query(...), expiry: str = Query(...)
):
    try:
        return {"strikes": await asyncio.to_thread(oia.list_strikes, underlying, date, expiry)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def _trading_dates(underlying: str) -> list[str]:
    cur = storage.db().cursor()
    try:
        rows = cur.execute(
            "SELECT DISTINCT CAST(ts AS DATE) d FROM spot_1m WHERE underlying=? ORDER BY d DESC",
            [underlying.upper()],
        ).fetchall()
        return [str(r[0]) for r in rows]
    finally:
        cur.close()


@router.get("/flow/dates")
async def get_flow_dates(underlying: str = Query(...)):
    try:
        return {"dates": await asyncio.to_thread(_trading_dates, underlying)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def _flow_live(underlying: str, expiry: str) -> dict:
    """Institutional live OI-flow from the in-process Angel feed singleton."""
    from src.data import angelone_scrip as scrip
    from src.data.angelone_feed import get_feed

    exp = expiry
    if not exp:
        # nearest non-expired expiry from the scrip master
        exps = scrip.list_expiries(underlying)
        today = _date.today().isoformat()
        future = [e for e in exps if e >= today]
        exp = future[0] if future else (exps[-1] if exps else "")
    if not exp:
        raise ValueError(f"No expiry available for {underlying}")

    feed = get_feed(underlying, exp)
    return feed.get_flow_payload()


@router.get("/flow/live")
async def get_flow_live(
    underlying: str = Query(...),
    expiry: str = Query("", description="ISO expiry; blank = nearest"),
):
    try:
        return await asyncio.to_thread(_flow_live, underlying, expiry)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

from __future__ import annotations
import asyncio
from fastapi import APIRouter, HTTPException, Query
from src.data import storage

router = APIRouter()


@router.get("/fii-dii")
async def get_fii_dii(days: int = Query(default=30, ge=1, le=365)):
    """Return FII/DII/Pro/Client participant-wise F&O data for last N days."""
    def _query():
        storage.init_db()
        return storage.read_fii_dii(days)
    try:
        rows = await asyncio.to_thread(_query)
        # Group by date for easier frontend consumption
        by_date: dict[str, list] = {}
        for r in rows:
            d = r["date"]
            if d not in by_date:
                by_date[d] = []
            by_date[d].append(r)
        return {
            "days": [{"date": d, "participants": v} for d, v in by_date.items()]
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/fii-dii/latest")
async def get_fii_dii_latest():
    """Return the most recent date's FII/DII data."""
    def _query():
        storage.init_db()
        rows = storage.read_fii_dii(1)
        return rows
    try:
        rows = await asyncio.to_thread(_query)
        return {"participants": rows}
    except Exception as e:
        raise HTTPException(500, str(e))

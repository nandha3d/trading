from __future__ import annotations
import asyncio
import subprocess
import sys
from datetime import date, timedelta
from fastapi import APIRouter, BackgroundTasks, Query
from fastapi.responses import JSONResponse
from src.data import storage

router = APIRouter()


def _run_bhav(target_date: str) -> dict:
    """Fetch NSE bhav inside the API process — shares the DuckDB connection."""
    import sys
    from pathlib import Path
    scripts_dir = str(Path(__file__).parent.parent.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    # Import lazily so it doesn't run at startup
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_fetch_eod_bhav",
        Path(scripts_dir) / "scripts" / "fetch_eod_bhav.py",
    )
    mod = importlib.util.module_from_spec(spec)
    old_argv, sys.argv = sys.argv[:], ["fetch_eod_bhav.py", target_date]
    try:
        spec.loader.exec_module(mod)
        mod.main()
        return {"ok": True, "date": target_date}
    except SystemExit:
        return {"ok": True, "date": target_date}
    except Exception as e:
        return {"ok": False, "error": str(e), "date": target_date}
    finally:
        sys.argv = old_argv


@router.post("/admin/fetch-bhav")
async def fetch_bhav(
    background_tasks: BackgroundTasks,
    d: str = Query(default="", description="YYYY-MM-DD, default=yesterday"),
):
    """Trigger NSE Bhav EOD fetch from inside the API (avoids DuckDB lock). Admin use only."""
    if not d:
        d = (date.today() - timedelta(days=1)).isoformat()
    background_tasks.add_task(_run_bhav, d)
    return JSONResponse({"status": "queued", "date": d})


@router.get("/admin/fetch-bhav-range")
async def fetch_bhav_range(
    background_tasks: BackgroundTasks,
    days: int = Query(default=7, description="Number of past calendar days to fetch"),
):
    """Fetch bhav for last N days (skips weekends). Admin use only."""
    dates = []
    d = date.today() - timedelta(days=1)
    fetched = 0
    while fetched < days:
        if d.weekday() < 5:
            dates.append(d.isoformat())
            fetched += 1
        d -= timedelta(days=1)
    for dt in dates:
        background_tasks.add_task(_run_bhav, dt)
    return JSONResponse({"status": "queued", "dates": dates})


import threading
import time

_STATUS_CACHE = None
_STATUS_CACHE_TIME = 0.0
_STATUS_LOCK = threading.Lock()


def _db_status():
    global _STATUS_CACHE, _STATUS_CACHE_TIME
    with _STATUS_LOCK:
        now = time.time()
        if _STATUS_CACHE is not None and (now - _STATUS_CACHE_TIME) < 600.0:
            return _STATUS_CACHE

        storage.init_db()
        v = storage.verify(fast=True)
        for tbl in v.values():
            tbl["ts_min"] = str(tbl["ts_min"]) if tbl["ts_min"] else None
            tbl["ts_max"] = str(tbl["ts_max"]) if tbl["ts_max"] else None
        
        _STATUS_CACHE = v
        _STATUS_CACHE_TIME = now
        return v



def _list_expiries(underlying: str):
    storage.init_db()
    exps = storage.list_expiries(underlying.upper())
    return {"expiries": [e.isoformat() for e in reversed(exps)]}


@router.get("/status")
async def db_status():
    return await asyncio.to_thread(_db_status)


@router.get("/expiries/{underlying}")
async def list_expiries(underlying: str):
    return await asyncio.to_thread(_list_expiries, underlying)

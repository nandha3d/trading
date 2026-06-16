from __future__ import annotations
import asyncio
from fastapi import APIRouter
from src.data import storage

router = APIRouter()


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

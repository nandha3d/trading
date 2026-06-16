from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes import backtest as bt, data as dt, options_chain as oc, payoff as pf, live_data as ld, flow as fl, oauth as oa

app = FastAPI(title="Options Backtest Platform", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(bt.router, prefix="/api")
app.include_router(dt.router, prefix="/api")
app.include_router(oc.router, prefix="/api")
app.include_router(pf.router, prefix="/api")
app.include_router(ld.router, prefix="/api")
app.include_router(fl.router, prefix="/api")
app.include_router(oa.router, prefix="/api")

dist = Path(__file__).parent.parent / "frontend" / "dist"
if dist.exists():
    app.mount("/", StaticFiles(directory=str(dist), html=True), name="static")

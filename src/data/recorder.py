"""Live 1-minute recorder: pya3 WebSocket ticks -> 1-min candles -> lake.

Builds your own forward options archive (free) so you stop depending on paid
history over time. Run during market hours (09:15-15:30 IST).

NOTE: pya3 websocket callback/subscribe API varies by version. The aggregation
logic is version-independent; only `start()` wiring may need adjustment once the
API is approved and creds are filled.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import polars as pl

from . import storage
from .aliceblue_client import AliceClient


@dataclass
class _Candle:
    o: float
    h: float
    l: float
    c: float
    v: int = 0
    oi: int = 0


@dataclass
class MinuteAggregator:
    """Accumulates ticks into per-instrument 1-min candles, flushes on minute roll."""

    meta: dict[int, dict] = field(default_factory=dict)   # token -> {underlying,expiry,strike,option_type}
    cur: dict[tuple[int, datetime], _Candle] = field(default_factory=dict)

    def register(self, token: int, **m) -> None:
        self.meta[token] = m

    def on_tick(self, token: int, ltp: float, ts: datetime, volume: int = 0, oi: int = 0) -> None:
        minute = ts.replace(second=0, microsecond=0)
        key = (token, minute)
        c = self.cur.get(key)
        if c is None:
            self.cur[key] = _Candle(ltp, ltp, ltp, ltp, volume, oi)
        else:
            c.h = max(c.h, ltp)
            c.l = min(c.l, ltp)
            c.c = ltp
            c.v = volume or c.v
            c.oi = oi or c.oi

    def drain_closed(self, now: datetime) -> int:
        """Flush candles whose minute has fully elapsed. Returns rows written."""
        cutoff = now.replace(second=0, microsecond=0)
        ready = [(k, c) for k, c in self.cur.items() if k[1] < cutoff]
        if not ready:
            return 0
        rows = []
        for (token, minute), c in ready:
            m = self.meta.get(token, {})
            rows.append(
                {
                    "underlying": m.get("underlying", "UNKNOWN"),
                    "expiry": m.get("expiry"),
                    "strike": m.get("strike", 0),
                    "option_type": m.get("option_type", "CE"),
                    "ts": minute,
                    "open": c.o, "high": c.h, "low": c.l, "close": c.c,
                    "volume": c.v, "oi": c.oi,
                }
            )
            del self.cur[(token, minute)]
        return storage.write_options(pl.DataFrame(rows))


def run(symbols: list[str]) -> None:
    """Skeleton: connect, subscribe relevant strikes, aggregate, flush.
    Strike-band selection + websocket callback wiring are filled when creds exist.
    """
    client = AliceClient()
    client.load_contracts("NSE", "NFO")
    agg = MinuteAggregator()
    # TODO(creds): resolve ATM +/- N strikes per symbol/expiry, subscribe over WS,
    # route each tick to agg.on_tick, and call agg.drain_closed() every few seconds.
    raise NotImplementedError("WS wiring pending API approval; aggregation ready.")

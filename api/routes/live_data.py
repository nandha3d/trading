from __future__ import annotations
import asyncio
import logging
import json
import time
import requests
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from urllib.parse import quote as urlquote
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, Optional

from config import settings

logger = logging.getLogger("LiveRoute")
logger.setLevel(logging.INFO)

router = APIRouter()

# ---------------------------------------------------------------------------
# Upstox live feed  (/api/ws/live)
# ---------------------------------------------------------------------------

_UPSTOX_LTP   = "https://api.upstox.com/v2/market-quote/ltp"
_UPSTOX_CHAIN = "https://api.upstox.com/v2/option/chain"
# Absolute path so it works regardless of CWD (NSSM service, tests, etc.)
_UPSTOX_SESS  = Path(__file__).resolve().parent.parent.parent / "data" / ".upstox_session.json"
logger.info("Upstox session path: %s (exists=%s)", _UPSTOX_SESS, _UPSTOX_SESS.exists())


def _upstox_token() -> str | None:
    if not _UPSTOX_SESS.exists():
        return None
    try:
        return json.loads(_UPSTOX_SESS.read_text())["access_token"]
    except Exception:
        return None


def _last_tuesday_of_month(ref: date) -> str:
    """Last Tuesday of ref's month; if past, use next month's."""
    import calendar
    year, month = ref.year, ref.month
    last = calendar.monthrange(year, month)[1]
    d = date(year, month, last)
    while d.weekday() != 1:        # walk back to Tuesday
        d -= timedelta(days=1)
    if d < ref:                    # already passed this month — use next month
        month += 1
        if month > 12:
            year, month = year + 1, 1
        last = calendar.monthrange(year, month)[1]
        d = date(year, month, last)
        while d.weekday() != 1:
            d -= timedelta(days=1)
    return d.isoformat()


def _next_expiry(underlying: str, ref: date) -> str:
    """Next available expiry from ref (inclusive).
    NIFTY = next Tuesday (weekly). BANKNIFTY = last Tuesday of month (monthly)."""
    if underlying == "BANKNIFTY":
        return _last_tuesday_of_month(ref)
    # NIFTY: next Tuesday
    d = ref
    for _ in range(8):
        if d.weekday() == 1:
            return d.isoformat()
        d += timedelta(days=1)
    return ref.isoformat()


def _atm(spot: float, step: int) -> int:
    return round(spot / step) * step


def _fetch_ltp(token: str) -> dict:
    keys = "NSE_INDEX|Nifty 50,NSE_INDEX|Nifty Bank"
    return requests.get(
        f"{_UPSTOX_LTP}?instrument_key={urlquote(keys)}",
        headers={"Authorization": f"Bearer {token}", "accept": "application/json"},
        timeout=5,
    ).json()


def _fetch_chain(token: str, inst_key: str, expiry: str) -> dict:
    return requests.get(
        f"{_UPSTOX_CHAIN}?instrument_key={urlquote(inst_key)}&expiry_date={expiry}",
        headers={"Authorization": f"Bearer {token}", "accept": "application/json"},
        timeout=8,
    ).json()


@router.websocket("/ws/live")
async def upstox_live_ws(websocket: WebSocket):
    await websocket.accept()

    token = _upstox_token()
    if not token:
        await websocket.send_json({
            "error": "no_session",
            "msg": "Run: python scripts/upstox_oauth.py",
        })
        await websocket.close()
        return

    state: dict = {"status": "connecting", "ts": "", "source": "upstox",
                   "indices": {}, "atm": {}}
    last_chain: dict[str, float] = {}   # underlying → loop-time of last chain fetch

    async def poll():
        loop = asyncio.get_event_loop()
        while True:
            now = loop.time()

            # --- spot LTP (every tick) ---
            try:
                body = await asyncio.to_thread(_fetch_ltp, token)
                if body.get("status") == "success":
                    data = body["data"]
                    ni  = next((v for k, v in data.items() if "Nifty 50"   in k), None)
                    bn  = next((v for k, v in data.items() if "Nifty Bank" in k), None)
                    if ni:
                        state["indices"].setdefault("NIFTY", {})["ltp"] = ni["last_price"]
                    if bn:
                        state["indices"].setdefault("BANKNIFTY", {})["ltp"] = bn["last_price"]
                    state["status"] = "ok"
                elif body.get("errors", [{}])[0].get("errorCode") == "UDAPI100050":
                    # token expired
                    state["status"] = "token_expired"
                    await websocket.send_json({**state,
                        "error": "token_expired",
                        "msg": "Re-run: python scripts/upstox_oauth.py"})
                    return
                else:
                    state["status"] = "api_error"
            except Exception as e:
                state["status"] = f"err: {e}"

            # --- option chain (every 10 s per underlying) ---
            today = date.today()
            for ul, inst_key, step in [
                ("NIFTY",     "NSE_INDEX|Nifty 50",  50),
                ("BANKNIFTY", "NSE_INDEX|Nifty Bank", 100),
            ]:
                spot = state["indices"].get(ul, {}).get("ltp")
                if spot and now - last_chain.get(ul, 0) >= 10:
                    expiry = _next_expiry(ul, today)
                    try:
                        cb = await asyncio.to_thread(_fetch_chain, token, inst_key, expiry)
                        if cb.get("status") == "success":
                            atm_strike = _atm(spot, step)
                            rows = cb.get("data", [])
                            row = next(
                                (r for r in rows
                                 if abs(float(r.get("strike_price", 0)) - atm_strike) < step * 0.5),
                                None,
                            )
                            if row:
                                ce_md = row.get("call_options", {}).get("market_data", {})
                                pe_md = row.get("put_options",  {}).get("market_data", {})
                                state["atm"][ul] = {
                                    "strike": atm_strike,
                                    "expiry": expiry,
                                    "ce_ltp": ce_md.get("ltp"),
                                    "pe_ltp": pe_md.get("ltp"),
                                    "ce_oi":  ce_md.get("oi"),
                                    "pe_oi":  pe_md.get("oi"),
                                }
                            last_chain[ul] = now
                    except Exception as e:
                        logger.warning("chain %s: %s", ul, e)

            state["ts"] = datetime.now(timezone.utc).strftime("%H:%M:%S")
            try:
                await websocket.send_json(state)
            except Exception:
                return

            await asyncio.sleep(1)

    task = asyncio.create_task(poll())
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Upstox live option chain source  (used by /api/live/stream)
# ---------------------------------------------------------------------------

class UpstoxChainSource:
    """Polls Upstox REST APIs; returns OptionsChainResponse-compatible dicts."""

    _INST = {"NIFTY": "NSE_INDEX|Nifty 50", "BANKNIFTY": "NSE_INDEX|Nifty Bank"}

    def __init__(self, underlying: str, expiry: str):
        self.underlying = underlying.upper()
        self.expiry = expiry
        self._token = _upstox_token()
        self._cache: dict = {}
        self._cache_ts: float = 0

    def tick(self):
        pass   # data fetched inside get_payload

    def get_payload(self) -> dict:
        now = time.time()
        if now - self._cache_ts < 2:
            return self._cache
        self._cache_ts = now
        self._cache = self._fetch()
        return self._cache

    def _fetch(self) -> dict:
        base = {"underlying": self.underlying, "expiry": self.expiry,
                "timestamp": "", "spot_price": None, "chain": [],
                "summary": None, "source": "upstox", "stale": False}

        if not self._token:
            return {**base, "status": "no_upstox_token",
                    "stale": True, "error": "Run: python scripts/upstox_oauth.py"}

        hdrs = {"Authorization": f"Bearer {self._token}", "accept": "application/json"}
        inst_key = self._INST.get(self.underlying, "NSE_INDEX|Nifty 50")

        # spot LTP
        spot: float | None = None
        try:
            r = requests.get(f"{_UPSTOX_LTP}?instrument_key={urlquote(inst_key)}",
                             headers=hdrs, timeout=5).json()
            if r.get("status") == "success":
                v = next(iter(r["data"].values()), {})
                spot = v.get("last_price")
        except Exception as e:
            logger.warning("Upstox LTP %s: %s", self.underlying, e)

        # option chain
        chain_rows: list[dict] = []
        total_ce_oi = total_pe_oi = 0
        try:
            r = requests.get(
                f"{_UPSTOX_CHAIN}?instrument_key={urlquote(inst_key)}&expiry_date={self.expiry}",
                headers=hdrs, timeout=8).json()
            if r.get("status") == "success":
                for row in sorted(r.get("data", []),
                                  key=lambda x: float(x.get("strike_price", 0))):
                    strike = int(float(row.get("strike_price", 0)))
                    ce_md = (row.get("call_options") or {}).get("market_data") or {}
                    pe_md = (row.get("put_options")  or {}).get("market_data") or {}
                    ce_gr = (row.get("call_options") or {}).get("option_greeks") or {}
                    pe_gr = (row.get("put_options")  or {}).get("option_greeks") or {}
                    ce_oi = ce_md.get("oi") or 0
                    pe_oi = pe_md.get("oi") or 0
                    total_ce_oi += ce_oi
                    total_pe_oi += pe_oi
                    chain_rows.append({
                        "strike": strike,
                        "ce": {"close": ce_md.get("ltp"), "volume": ce_md.get("volume"),
                               "oi": ce_md.get("oi"),
                               "oi_change": (ce_md.get("oi") or 0) - (ce_md.get("prev_oi") or 0),
                               "iv": ce_gr.get("iv"), "delta": ce_gr.get("delta"),
                               "theta": ce_gr.get("theta")} if ce_md else None,
                        "pe": {"close": pe_md.get("ltp"), "volume": pe_md.get("volume"),
                               "oi": pe_md.get("oi"),
                               "oi_change": (pe_md.get("oi") or 0) - (pe_md.get("prev_oi") or 0),
                               "iv": pe_gr.get("iv"), "delta": pe_gr.get("delta"),
                               "theta": pe_gr.get("theta")} if pe_md else None,
                    })
        except Exception as e:
            logger.warning("Upstox chain %s %s: %s", self.underlying, self.expiry, e)

        summary = None
        if chain_rows:
            pcr = total_pe_oi / total_ce_oi if total_ce_oi else 1.0
            summary = {"pcr": round(pcr, 4), "max_pain": self._max_pain(chain_rows),
                       "total_ce_oi": total_ce_oi, "total_pe_oi": total_pe_oi}

        return {**base,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "spot_price": spot,
                "chain": chain_rows,
                "summary": summary,
                "status": "ok" if chain_rows else "no_data"}

    @staticmethod
    def _max_pain(chain: list[dict]) -> int:
        strikes = [r["strike"] for r in chain]
        best, best_s = float("inf"), strikes[0] if strikes else 0
        for s in strikes:
            loss = sum(
                max(0, s - r["strike"]) * ((r.get("ce") or {}).get("oi") or 0) +
                max(0, r["strike"] - s) * ((r.get("pe") or {}).get("oi") or 0)
                for r in chain)
            if loss < best:
                best, best_s = loss, s
        return best_s


class _CachedSnapshot:
    """Last-fetched snapshot replayer used when the real feed can't start
    (no creds / login error). Never simulates — just serves disk cache."""

    def __init__(self, underlying: str, expiry: str):
        self.underlying = underlying.upper()
        self.expiry = expiry

    def get_payload(self) -> dict:
        from src.data.angelone_feed import SNAP_DIR
        import json
        p = SNAP_DIR / f"{self.underlying}_{self.expiry}.json"
        if p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                d["stale"] = True
                d["source"] = "angelone"
                d["status"] = "feed offline — last fetched " + str(d.get("timestamp", ""))[:19]
                return d
            except Exception as e:
                logger.warning(f"snapshot read failed: {e}")
        return {
            "underlying": self.underlying, "expiry": self.expiry,
            "timestamp": "", "spot_price": None, "chain": [], "summary": None,
            "pcr": 1.0, "max_pain": 0, "total_ce_oi": 0, "total_pe_oi": 0,
            "pcr_trend": [], "block_trades": [],
            "source": "angelone", "stale": True,
            "status": "no live feed and no cached data",
        }


def _acquire_source(underlying: str, expiry: str):
    """Angel One preferred (fully automatic); Upstox fallback; last snapshot if both fail."""
    # 1. Angel One (Auto TOTP login)
    if settings.angelone_ready:
        try:
            from src.data.angelone_feed import get_feed
            feed = get_feed(underlying, expiry)
            logger.info("Using Angel One feed for %s %s", underlying, expiry)
            return feed, True
        except Exception as e:
            logger.warning("Angel One unavailable (%s); trying Upstox", e)
            
    # 2. Upstox (REST, requires daily manual oauth)
    if _upstox_token():
        try:
            today_str = date.today().isoformat()
            live_expiry = expiry if expiry >= today_str else _next_expiry(underlying, date.today())
            src = UpstoxChainSource(underlying, live_expiry)
            logger.info("Using Upstox live chain for %s %s", underlying, live_expiry)
            return src, True
        except Exception as e:
            logger.warning("Upstox source init failed (%s); serving snapshot", e)
            
    # 3. Last cached snapshot
    return _CachedSnapshot(underlying, expiry), True

@router.websocket("/live/stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("New WebSocket client connected")
    
    current_session = None
    is_real = False
    stream_task: Optional[asyncio.Task] = None

    async def sender_loop():
        nonlocal current_session
        try:
            while True:
                if current_session:
                    if not is_real:
                        current_session.tick()
                    # get_payload may do HTTP — run off the event loop
                    payload = await asyncio.to_thread(current_session.get_payload)
                    await websocket.send_json(payload)
                await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("sender_loop error: %s", e)
            
    try:
        # Start the background sender task
        stream_task = asyncio.create_task(sender_loop())
        
        while True:
            # Wait for subscription messages from the client
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                action = msg.get("action")
                
                if action == "subscribe":
                    underlying = msg.get("underlying")
                    expiry = msg.get("expiry")

                    if underlying and expiry:
                        logger.info(f"Subscribing connection to {underlying} - {expiry}")
                        current_session, is_real = _acquire_source(underlying, expiry)

                        # Send immediate initial response
                        payload = await asyncio.to_thread(current_session.get_payload)
                        await websocket.send_json(payload)
                    else:
                        await websocket.send_json({"error": "Missing underlying or expiry in subscribe message"})
                else:
                    await websocket.send_json({"error": f"Unknown action '{action}'"})
            except json.JSONDecodeError:
                await websocket.send_json({"error": "Invalid JSON payload"})
                
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    finally:
        if stream_task:
            stream_task.cancel()
            try:
                await stream_task
            except asyncio.CancelledError:
                pass

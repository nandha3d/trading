"""Real-time Angel One options feed.

Logs into SmartAPI with .env credentials, resolves the option-chain tokens for
an underlying+expiry (ATM +/- window) via the scrip master, subscribes to the
SmartWebSocketV2 SnapQuote stream, and maintains a live chain. Emits the SAME
payload shape as live_manager.LiveSession so the WebSocket route and frontend
stay unchanged.

If login/resolve fails this raises, and the route is responsible for using the
simulated LiveSession instead.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime, time
from pathlib import Path
from typing import Dict, Optional

from config import settings
from . import angelone_scrip as scrip
from .live_manager import fetch_yahoo_spot
from .options_math import calculate_iv, calculate_greeks

logger = logging.getLogger("AngelOneFeed")
RISK_FREE = 0.065

STEP = {"NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50, "MIDCPNIFTY": 75}
LOT = {"NIFTY": 75, "BANKNIFTY": 35, "FINNIFTY": 65, "MIDCPNIFTY": 120}

# Last good live chain is mirrored to disk so a market-closed day / holiday /
# server restart can replay the last fetched data instead of going blank.
SNAP_DIR = Path("data/live_snapshots")


class AngelOneFeed:
    """One live feed per (underlying, expiry)."""

    def __init__(self, underlying: str, expiry: str, window: int = 15):
        if not settings.angelone_ready:
            raise RuntimeError("Angel One credentials not configured (.env)")
        self.underlying = underlying.upper()
        self.expiry = expiry
        self.window = window
        self.step = STEP.get(self.underlying, 50)
        self.lot_size = LOT.get(self.underlying, 75)

        self._lock = threading.Lock()
        self.spot_price: float = 0.0
        self.chain: Dict[int, dict] = {}        # strike -> live cells
        self.token_map: Dict[str, dict] = {}    # token -> {strike, opt_type}
        self._spot_token: str = ""
        self.pcr_trend: list[dict] = []
        self.status = "init"
        self.connected = False
        self._sws = None
        self._thread: Optional[threading.Thread] = None

    # ---- lifecycle ----
    def start(self) -> None:
        auth_token, feed_token, api_key = self._login()
        self._resolve_tokens()
        self._build_empty_chain()
        self._launch_ws(auth_token, feed_token, api_key)

    def _login(self) -> tuple[str, str, str]:
        try:
            from SmartApi import SmartConnect
            import pyotp
        except ImportError as e:
            raise RuntimeError(f"smartapi-python / pyotp not installed: {e}")
        sc = SmartConnect(api_key=settings.angelone_api_key)
        totp = pyotp.TOTP(settings.angelone_totp_secret).now()
        res = sc.generateSession(settings.angelone_client_code, settings.angelone_pin, totp)
        if not (res and res.get("status")):
            raise RuntimeError(f"Angel One login failed: {res.get('message') if res else 'no response'}")
        auth_token = res["data"]["jwtToken"]
        feed_token = sc.getfeedToken()
        logger.info(f"Angel One login OK for {settings.angelone_client_code}")
        return auth_token, feed_token, settings.angelone_api_key

    def _resolve_tokens(self) -> None:
        # seed spot to find ATM window
        spot = fetch_yahoo_spot(self.underlying) or 0.0
        if spot <= 0:
            all_toks = scrip.resolve_option_tokens(self.underlying, self.expiry)
            strikes = sorted({v["strike"] for v in all_toks.values()})
            if not strikes:
                raise RuntimeError("No option tokens for expiry")
            spot = strikes[len(strikes) // 2] * 1.0
        self.spot_price = spot
        atm = int(round(spot / self.step) * self.step)
        wanted = [atm + i * self.step for i in range(-self.window, self.window + 1)]
        self.token_map = scrip.resolve_option_tokens(self.underlying, self.expiry, strikes=wanted)
        if not self.token_map:
            raise RuntimeError(f"No tokens resolved for {self.underlying} {self.expiry}")
        self._spot_token, _ = scrip.spot_token(self.underlying)

    def _build_empty_chain(self) -> None:
        for meta in self.token_map.values():
            s = meta["strike"]
            self.chain.setdefault(s, {
                "strike": s,
                "ce": None, "pe": None,
                "ce_ltp": 0.0, "pe_ltp": 0.0,
                "ce_oi": 0, "pe_oi": 0,
                "ce_vol": 0, "pe_vol": 0,
                "ce_oi_open": 0, "pe_oi_open": 0,
            })

    def _launch_ws(self, auth_token: str, feed_token: str, api_key: str) -> None:
        from SmartApi.smartWebSocketV2 import SmartWebSocketV2
        sws = SmartWebSocketV2(auth_token, api_key, settings.angelone_client_code, feed_token)
        self._sws = sws

        token_list = [
            {"exchangeType": scrip.EXCH_NSE_CM, "tokens": [self._spot_token]},
            {"exchangeType": scrip.EXCH_NFO, "tokens": list(self.token_map.keys())},
        ]

        def on_open(_wsapp):
            self.connected = True
            self.status = "connected"
            logger.info("WS open; subscribing SnapQuote")
            sws.subscribe("opt-suite", 3, token_list)  # mode 3 = SnapQuote

        def on_data(_wsapp, message):
            try:
                self._on_tick(message)
            except Exception as e:
                logger.debug(f"tick parse error: {e}")

        def on_error(_wsapp, error):
            self.status = f"error: {error}"
            logger.error(f"WS error: {error}")

        def on_close(_wsapp):
            self.connected = False
            self.status = "disconnected"

        sws.on_open = on_open
        sws.on_data = on_data
        sws.on_error = on_error
        sws.on_close = on_close

        self._thread = threading.Thread(target=sws.connect, daemon=True)
        self._thread.start()

    # ---- tick handling ----
    def _on_tick(self, msg: dict) -> None:
        if not isinstance(msg, dict):
            return
        token = str(msg.get("token", "")).strip('"')
        ltp_raw = msg.get("last_traded_price")
        if ltp_raw is None:
            return
        ltp = float(ltp_raw) / 100.0  # Angel sends price x100

        with self._lock:
            if token == self._spot_token:
                self.spot_price = ltp
                return
            meta = self.token_map.get(token)
            if not meta:
                return
            s, ot = meta["strike"], meta["opt_type"]
            cell = self.chain.get(s)
            if cell is None:
                return
            oi = int(msg.get("open_interest", 0) or 0)
            vol = int(msg.get("volume_trade_for_the_day", 0) or 0)
            pfx = "ce" if ot == "CE" else "pe"
            cell[f"{pfx}_ltp"] = ltp
            if oi:
                if cell[f"{pfx}_oi_open"] == 0:
                    cell[f"{pfx}_oi_open"] = oi
                cell[f"{pfx}_oi"] = oi
            if vol:
                cell[f"{pfx}_vol"] = vol

    # ---- payload ----
    def _dte_years(self) -> float:
        exp = date.fromisoformat(self.expiry)
        exp_dt = datetime.combine(exp, time(15, 30))
        secs = max((exp_dt - datetime.now()).total_seconds(), 60.0)
        return secs / (365.0 * 86400)

    def get_payload(self) -> dict:
        t = self._dte_years()
        with self._lock:
            spot = self.spot_price
            chain_list = []
            total_ce_oi = total_pe_oi = 0
            has_ltp = False
            for s in sorted(self.chain.keys()):
                c = self.chain[s]
                if c["ce_ltp"] > 0 or c["pe_ltp"] > 0:
                    has_ltp = True
                ce = self._greeks_cell(spot, s, t, "CE", c["ce_ltp"], c["ce_oi"], c["ce_vol"], c["ce_oi_open"])
                pe = self._greeks_cell(spot, s, t, "PE", c["pe_ltp"], c["pe_oi"], c["pe_vol"], c["pe_oi_open"])
                total_ce_oi += c["ce_oi"]
                total_pe_oi += c["pe_oi"]
                chain_list.append({"strike": s, "ce": ce, "pe": pe})

            max_pain = self._max_pain()
            pcr = round(total_pe_oi / total_ce_oi, 3) if total_ce_oi > 0 else 1.0
            now = datetime.now().strftime("%H:%M:%S")

            live = has_ltp and spot > 0
            if live:
                self.pcr_trend.append({"time": now, "pcr": pcr, "max_pain": max_pain})
                if len(self.pcr_trend) > 50:
                    self.pcr_trend.pop(0)

            payload = {
                "underlying": self.underlying,
                "expiry": self.expiry,
                "timestamp": datetime.now().isoformat(),
                "spot_price": round(spot, 2),
                "pcr": pcr,
                "max_pain": max_pain,
                "total_ce_oi": total_ce_oi,
                "total_pe_oi": total_pe_oi,
                "chain": chain_list,
                "pcr_trend": self.pcr_trend,
                "block_trades": [],
                "source": "angelone",
                "status": self.status,
                "stale": False,
            }

        # Live ticks present -> persist as the "last fetched" snapshot.
        if live:
            self._save_snapshot(payload)
            return payload

        # No live ticks (market closed / holiday / pre-open / restart):
        # replay the last fetched data instead of an empty chain.
        cached = self._load_snapshot()
        if cached:
            cached["stale"] = True
            cached["source"] = "angelone"
            cached["status"] = "market closed — last fetched " + str(cached.get("timestamp", ""))[:19]
            return cached
        payload["status"] = "no data yet (" + self.status + ")"
        return payload

    # ---- snapshot persistence ----
    def _snap_path(self) -> Path:
        return SNAP_DIR / f"{self.underlying}_{self.expiry}.json"

    def _save_snapshot(self, payload: dict) -> None:
        try:
            SNAP_DIR.mkdir(parents=True, exist_ok=True)
            tmp = self._snap_path().with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(self._snap_path())
        except Exception as e:
            logger.debug(f"snapshot save failed: {e}")

    def _load_snapshot(self) -> Optional[dict]:
        try:
            p = self._snap_path()
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.debug(f"snapshot load failed: {e}")
        return None

    def _greeks_cell(self, spot, strike, t, ot, ltp, oi, vol, oi_open) -> dict:
        iv = 0.0
        delta = theta = 0.0
        if ltp > 0 and spot > 0 and t > 0:
            iv_calc = calculate_iv(ltp, spot, strike, t, RISK_FREE, ot)
            if iv_calc and iv_calc > 0:
                iv = iv_calc
                g = calculate_greeks(spot, strike, t, RISK_FREE, iv, ot)
                delta, theta = g["delta"], g["theta"]
        return {
            "close": round(ltp, 2),
            "volume": vol,
            "oi": oi,
            "iv": round(iv * 100, 2),
            "delta": delta,
            "theta": theta,
            "oi_change": (oi - oi_open) if oi_open else 0,
        }

    def _max_pain(self) -> int:
        strikes = sorted(self.chain.keys())
        if not strikes:
            return 0
        best, best_pain = strikes[0], float("inf")
        for target in strikes:
            pain = 0.0
            for s in strikes:
                c = self.chain[s]
                if target > s:
                    pain += (target - s) * c["ce_oi"]
                elif target < s:
                    pain += (s - target) * c["pe_oi"]
            if pain < best_pain:
                best_pain, best = pain, target
        return best

    def stop(self) -> None:
        try:
            if self._sws:
                self._sws.close_connection()
        except Exception:
            pass
        self.connected = False
        self.status = "stopped"


# ---- session cache ----
_feeds: Dict[str, AngelOneFeed] = {}
_feeds_lock = threading.Lock()


def get_feed(underlying: str, expiry: str) -> AngelOneFeed:
    """Return a started feed for (underlying, expiry). Raises if creds/login fail."""
    key = f"{underlying.upper()}_{expiry}"
    with _feeds_lock:
        f = _feeds.get(key)
        if f is None:
            f = AngelOneFeed(underlying, expiry)
            f.start()
            _feeds[key] = f
        return f

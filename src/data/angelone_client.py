"""Angel One (SmartAPI) thin wrapper.

Responsibilities:
  - Authenticate using API Key, Client Code, Password, and TOTP Seed
  - Connect to SmartWebSocketV2 to receive real-time options telemetry
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Any, Callable

logger = logging.getLogger("AngelOneClient")

try:
    from SmartApi import SmartConnect
    import pyotp
except ImportError:
    SmartConnect = None
    pyotp = None

class AngelOneClient:
    def __init__(self, config_path: str = "config/live_config.json") -> None:
        if SmartConnect is None or pyotp is None:
            raise RuntimeError("Required packages missing. Please install smartapi-python and pyotp.")
        
        # Load credentials
        p = Path(config_path)
        if not p.exists():
            raise FileNotFoundError(f"Config file not found at {config_path}")
        
        with open(p, "r") as f:
            cfg = json.load(f)
            
        ao_cfg = cfg.get("angelone", {})
        self.api_key = ao_cfg.get("api_key", "")
        self.client_code = ao_cfg.get("client_code", "")
        self.password = ao_cfg.get("password", "")
        self.totp_seed = ao_cfg.get("totp_seed", "")
        
        if not (self.api_key and self.client_code and self.password and self.totp_seed):
            raise ValueError("API Key, Client Code, Password, and TOTP Seed must be set in live_config.json")
            
        self.smart_connect = SmartConnect(api_key=self.api_key)
        self.auth_token: str = ""
        self.feed_token: str = ""
        
    def login(self) -> bool:
        """Authenticate and fetch auth token + feed token."""
        try:
            totp = pyotp.TOTP(self.totp_seed).now()
            res = self.smart_connect.generateSession(self.client_code, self.password, totp)
            if res and res.get("status"):
                self.auth_token = res["data"]["jwtToken"]
                self.feed_token = self.smart_connect.getfeedToken()
                logger.info(f"Logged in successfully as {self.client_code}")
                return True
            else:
                msg = res.get("message", "Unknown error")
                logger.error(f"Login failed: {msg}")
                return False
        except Exception as e:
            logger.error(f"Login exception: {e}")
            return False

    def subscribe_live_ticks(self, token_list: list[dict], on_tick: Callable[[Dict[str, Any]], None], on_error: Callable[[Any], None]) -> Any:
        """Connect to SmartWebSocketV2 and subscribe to streaming quote updates.
        token_list elements format: {"exchangeType": 1, "tokens": ["3045"]}
        exchangeType: 1 for NSE cash, 2 for NFO (Futures & Options)
        """
        try:
            from SmartApi.smartWebSocketV2 import SmartWebSocketV2
        except ImportError:
            raise RuntimeError("SmartWebSocketV2 could not be imported from SmartApi")

        sws = SmartWebSocketV2(
            jwt_token=self.auth_token,
            api_key=self.api_key,
            client_code=self.client_code,
            feed_token=self.feed_token
        )

        def on_message(ws, message):
            on_tick(message)

        def on_open(ws):
            logger.info("SmartWebSocketV2 connection opened. Subscribing to tokens...")
            # Subscribe to the requested tokens
            # Mode 3: SnapQuote (LTP, Best 5 bids/asks, Volume, Open Interest, etc.)
            sws.subscribe(correlation_id="options-suite", mode=3, token_list=token_list)

        def on_socket_error(ws, error):
            logger.error(f"SmartWebSocketV2 error: {error}")
            on_error(error)

        def on_close(ws, code, reason):
            logger.info(f"SmartWebSocketV2 closed: {code} - {reason}")

        sws.on_open = on_open
        sws.on_message = on_message
        sws.on_error = on_socket_error
        sws.on_close = on_close

        # Run connection on a background thread/task
        # Note: sws.connect() is blocking. The caller should launch this in a thread if needed.
        return sws

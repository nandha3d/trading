"""Zerodha Kite Connect market data provider adapter."""
from __future__ import annotations
from datetime import date, datetime
from typing import Any

from .base import MarketDataProvider


class ZerodhaProvider(MarketDataProvider):
    """Zerodha Kite Connect adapter."""

    def __init__(self):
        self._kite = None
        try:
            from kiteconnect import KiteConnect
            from config import settings
            api_key = getattr(settings, "zerodha_api_key", None)
            access_token = getattr(settings, "zerodha_access_token", None)
            if api_key and access_token:
                self._kite = KiteConnect(api_key=api_key)
                self._kite.set_access_token(access_token)
        except ImportError:
            pass
        except Exception:
            pass

    @property
    def name(self) -> str:
        return "Zerodha"

    @property
    def is_available(self) -> bool:
        return self._kite is not None

    def _ensure(self):
        if not self._kite:
            raise RuntimeError("Zerodha not configured. Install kiteconnect and set credentials.")

    def get_ltp(self, instruments: list[str]) -> dict[str, float]:
        self._ensure()
        try:
            keys = [f"NSE:{inst}" for inst in instruments]
            data = self._kite.ltp(keys)
            return {inst: data.get(f"NSE:{inst}", {}).get("last_price", 0.0) for inst in instruments}
        except Exception:
            return {inst: 0.0 for inst in instruments}

    def get_candles(self, instrument: str, interval: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        self._ensure()
        interval_map = {"1": "minute", "3": "3minute", "5": "5minute", "15": "15minute", "30": "30minute", "60": "60minute", "D": "day"}
        kite_interval = interval_map.get(interval, "5minute")
        try:
            data = self._kite.historical_data(instrument, start, end, kite_interval)
            return [{"ts": str(r["date"]), "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "volume": r["volume"]} for r in data]
        except Exception:
            return []

    def get_option_chain(self, underlying: str, expiry: date) -> list[dict[str, Any]]:
        self._ensure()
        return []

    def get_expiries(self, underlying: str) -> list[date]:
        self._ensure()
        return []

    def get_contract_master(self) -> list[dict[str, Any]]:
        self._ensure()
        try:
            return self._kite.instruments("NFO")
        except Exception:
            return []

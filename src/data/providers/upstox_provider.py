"""Upstox market data provider adapter."""
from __future__ import annotations
from datetime import date, datetime
from typing import Any

from .base import MarketDataProvider


class UpstoxProvider(MarketDataProvider):
    """Upstox API v2 adapter."""

    def __init__(self):
        self._access_token = None
        try:
            from config import settings
            self._access_token = getattr(settings, "upstox_access_token", None)
            self._api_key = getattr(settings, "upstox_api_key", None)
        except ImportError:
            pass

    @property
    def name(self) -> str:
        return "Upstox"

    @property
    def is_available(self) -> bool:
        return self._access_token is not None

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token}", "Accept": "application/json"}

    def get_ltp(self, instruments: list[str]) -> dict[str, float]:
        if not self.is_available:
            raise RuntimeError("Upstox not configured. Set upstox_access_token.")
        import requests
        result = {}
        for inst in instruments:
            try:
                r = requests.get(f"https://api.upstox.com/v2/market-quote/ltp?instrument_key=NSE_INDEX|{inst}", headers=self._headers())
                data = r.json().get("data", {})
                for k, v in data.items():
                    result[inst] = v.get("last_price", 0.0)
            except Exception:
                result[inst] = 0.0
        return result

    def get_candles(self, instrument: str, interval: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        if not self.is_available:
            raise RuntimeError("Upstox not configured.")
        return []

    def get_option_chain(self, underlying: str, expiry: date) -> list[dict[str, Any]]:
        if not self.is_available:
            raise RuntimeError("Upstox not configured.")
        import requests
        try:
            r = requests.get(
                f"https://api.upstox.com/v2/option/chain?instrument_key=NSE_INDEX|{underlying}&expiry_date={expiry.isoformat()}",
                headers=self._headers()
            )
            return r.json().get("data", [])
        except Exception:
            return []

    def get_expiries(self, underlying: str) -> list[date]:
        if not self.is_available:
            raise RuntimeError("Upstox not configured.")
        return []

    def get_contract_master(self) -> list[dict[str, Any]]:
        if not self.is_available:
            raise RuntimeError("Upstox not configured.")
        return []

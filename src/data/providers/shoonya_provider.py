"""Shoonya (Finvasia) market data provider adapter."""
from __future__ import annotations
from datetime import date, datetime
from typing import Any

from .base import MarketDataProvider


class ShoonyaProvider(MarketDataProvider):
    """Shoonya / Finvasia NorenRestApi adapter."""

    def __init__(self):
        self._api = None
        try:
            from NorenRestApiPy.NorenApi import NorenApi
            from config import settings
            user_id = getattr(settings, "shoonya_user_id", None)
            password = getattr(settings, "shoonya_password", None)
            vendor_code = getattr(settings, "shoonya_vendor_code", None)
            api_key = getattr(settings, "shoonya_api_key", None)
            imei = getattr(settings, "shoonya_imei", None)
            if user_id and password and api_key:
                self._api = NorenApi(host="https://api.shoonya.com/NorenWClientTP/",
                                     websocket="wss://api.shoonya.com/NorenWSTP/")
                self._credentials = {
                    "userid": user_id, "password": password,
                    "vendor_code": vendor_code, "api_secret": api_key, "imei": imei or "abc1234"
                }
        except ImportError:
            pass
        except Exception:
            pass

    @property
    def name(self) -> str:
        return "Shoonya"

    @property
    def is_available(self) -> bool:
        return self._api is not None

    def _ensure(self):
        if not self._api:
            raise RuntimeError("Shoonya not configured. Install NorenRestApiPy and set credentials.")

    def get_ltp(self, instruments: list[str]) -> dict[str, float]:
        self._ensure()
        return {inst: 0.0 for inst in instruments}

    def get_candles(self, instrument: str, interval: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        self._ensure()
        return []

    def get_option_chain(self, underlying: str, expiry: date) -> list[dict[str, Any]]:
        self._ensure()
        return []

    def get_expiries(self, underlying: str) -> list[date]:
        self._ensure()
        return []

    def get_contract_master(self) -> list[dict[str, Any]]:
        self._ensure()
        return []

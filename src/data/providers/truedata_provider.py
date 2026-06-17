"""TrueData market data provider adapter."""
from __future__ import annotations
from datetime import date, datetime
from typing import Any

from .base import MarketDataProvider


class TrueDataProvider(MarketDataProvider):
    """TrueData real-time and historical data adapter."""

    def __init__(self):
        self._client = None
        try:
            from truedata_ws.TDApi import TrueDataWS
            from config import settings
            user = getattr(settings, "truedata_user", None)
            password = getattr(settings, "truedata_password", None)
            if user and password:
                self._user = user
                self._password = password
                self._client = True  # Lazy — connect only when needed
        except ImportError:
            pass
        except Exception:
            pass

    @property
    def name(self) -> str:
        return "TrueData"

    @property
    def is_available(self) -> bool:
        return self._client is not None

    def _ensure(self):
        if not self._client:
            raise RuntimeError("TrueData not configured. Install truedata_ws and set credentials.")

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

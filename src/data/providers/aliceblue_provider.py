"""AliceBlue market data provider adapter."""
from __future__ import annotations
from datetime import date, datetime
from typing import Any

from .base import MarketDataProvider


class AliceBlueProvider(MarketDataProvider):
    """AliceBlue / ANT API adapter."""

    def __init__(self):
        self._client = None
        try:
            from pya3 import Aliceblue
            from config import settings
            user_id = getattr(settings, "aliceblue_user_id", None)
            api_key = getattr(settings, "aliceblue_api_key", None)
            if user_id and api_key:
                self._client = Aliceblue(user_id=user_id, api_key=api_key)
        except ImportError:
            pass
        except Exception:
            pass

    @property
    def name(self) -> str:
        return "AliceBlue"

    @property
    def is_available(self) -> bool:
        return self._client is not None

    def _ensure(self):
        if not self._client:
            raise RuntimeError("AliceBlue not configured. Install pya3 and set credentials.")

    def get_ltp(self, instruments: list[str]) -> dict[str, float]:
        self._ensure()
        result = {}
        for inst in instruments:
            try:
                data = self._client.get_scrip_info({"exchange": "NSE", "token": inst})
                result[inst] = float(data.get("Ltp", 0))
            except Exception:
                result[inst] = 0.0
        return result

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

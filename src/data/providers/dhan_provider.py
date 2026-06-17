"""Dhan market data provider adapter."""
from __future__ import annotations
from datetime import date, datetime
from typing import Any

from .base import MarketDataProvider


class DhanProvider(MarketDataProvider):
    """Dhan HQ API adapter."""

    def __init__(self):
        self._client = None
        try:
            from dhanhq import dhanhq
            from config import settings
            client_id = getattr(settings, "dhan_client_id", None)
            access_token = getattr(settings, "dhan_access_token", None)
            if client_id and access_token:
                self._client = dhanhq(client_id, access_token)
        except ImportError:
            pass
        except Exception:
            pass

    @property
    def name(self) -> str:
        return "Dhan"

    @property
    def is_available(self) -> bool:
        return self._client is not None

    def _ensure(self):
        if not self._client:
            raise RuntimeError("Dhan not configured. Install dhanhq and set credentials.")

    def get_ltp(self, instruments: list[str]) -> dict[str, float]:
        self._ensure()
        return {inst: 0.0 for inst in instruments}

    def get_candles(self, instrument: str, interval: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        self._ensure()
        return []

    def get_option_chain(self, underlying: str, expiry: date) -> list[dict[str, Any]]:
        self._ensure()
        try:
            data = self._client.option_chain(underlying, expiry.isoformat())
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def get_expiries(self, underlying: str) -> list[date]:
        self._ensure()
        return []

    def get_contract_master(self) -> list[dict[str, Any]]:
        self._ensure()
        return []

"""Fyers market data provider adapter."""
from __future__ import annotations
from datetime import date, datetime
from typing import Any

from .base import MarketDataProvider


class FyersProvider(MarketDataProvider):
    """Fyers API v3 adapter."""

    def __init__(self):
        self._client = None
        try:
            from fyers_apiv3 import fyersModel
            from config import settings
            client_id = getattr(settings, "fyers_client_id", None)
            access_token = getattr(settings, "fyers_access_token", None)
            if client_id and access_token:
                self._client = fyersModel.FyersModel(client_id=client_id, token=access_token)
        except ImportError:
            pass
        except Exception:
            pass

    @property
    def name(self) -> str:
        return "Fyers"

    @property
    def is_available(self) -> bool:
        return self._client is not None

    def _ensure(self):
        if not self._client:
            raise RuntimeError("Fyers not configured. Install fyers_apiv3 and set credentials.")

    def get_ltp(self, instruments: list[str]) -> dict[str, float]:
        self._ensure()
        try:
            symbols = ",".join([f"NSE:{inst}-INDEX" for inst in instruments])
            data = self._client.quotes({"symbols": symbols})
            result = {}
            for item in data.get("d", []):
                sym = item.get("n", "").replace("NSE:", "").replace("-INDEX", "")
                result[sym] = item.get("v", {}).get("lp", 0.0)
            return result
        except Exception:
            return {inst: 0.0 for inst in instruments}

    def get_candles(self, instrument: str, interval: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        self._ensure()
        try:
            data = {
                "symbol": f"NSE:{instrument}-INDEX",
                "resolution": interval,
                "date_format": "1",
                "range_from": start.strftime("%Y-%m-%d"),
                "range_to": end.strftime("%Y-%m-%d"),
                "cont_flag": "1",
            }
            result = self._client.history(data)
            candles = result.get("candles", [])
            return [{"ts": c[0], "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]} for c in candles]
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
        return []

"""AngelOne (SmartAPI) market data provider adapter."""
from __future__ import annotations
from datetime import date, datetime
from typing import Any

from .base import MarketDataProvider


class AngelOneProvider(MarketDataProvider):
    """AngelOne SmartAPI adapter for market data."""

    def __init__(self):
        self._client = None
        try:
            from SmartApi import SmartConnect
            from config import settings
            api_key = getattr(settings, "angelone_api_key", None)
            client_code = getattr(settings, "angelone_client_code", None)
            password = getattr(settings, "angelone_password", None)
            totp_secret = getattr(settings, "angelone_totp_secret", None)
            if api_key and client_code:
                self._client = SmartConnect(api_key=api_key)
                self._client_code = client_code
                self._password = password
                self._totp_secret = totp_secret
        except ImportError:
            pass
        except Exception:
            pass

    @property
    def name(self) -> str:
        return "AngelOne"

    @property
    def is_available(self) -> bool:
        return self._client is not None

    def _ensure_session(self):
        if not self._client:
            raise RuntimeError("AngelOne client not initialized. Install SmartApi and configure credentials.")

    def get_ltp(self, instruments: list[str]) -> dict[str, float]:
        self._ensure_session()
        result = {}
        for inst in instruments:
            try:
                data = self._client.ltpData("NSE", inst, "")
                if data and data.get("data"):
                    result[inst] = data["data"].get("ltp", 0.0)
            except Exception:
                result[inst] = 0.0
        return result

    def get_candles(self, instrument: str, interval: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        self._ensure_session()
        interval_map = {"1": "ONE_MINUTE", "3": "THREE_MINUTE", "5": "FIVE_MINUTE",
                        "15": "FIFTEEN_MINUTE", "30": "THIRTY_MINUTE", "60": "ONE_HOUR", "D": "ONE_DAY"}
        api_interval = interval_map.get(interval, "FIVE_MINUTE")
        try:
            params = {
                "exchange": "NSE",
                "symboltoken": instrument,
                "interval": api_interval,
                "fromdate": start.strftime("%Y-%m-%d %H:%M"),
                "todate": end.strftime("%Y-%m-%d %H:%M"),
            }
            data = self._client.getCandleData(params)
            if data and data.get("data"):
                return [
                    {"ts": row[0], "open": row[1], "high": row[2], "low": row[3], "close": row[4], "volume": row[5]}
                    for row in data["data"]
                ]
        except Exception:
            pass
        return []

    def get_option_chain(self, underlying: str, expiry: date) -> list[dict[str, Any]]:
        self._ensure_session()
        # AngelOne does not have a direct option chain API; scrip master + LTP calls required
        return []

    def get_expiries(self, underlying: str) -> list[date]:
        self._ensure_session()
        return []

    def get_contract_master(self) -> list[dict[str, Any]]:
        self._ensure_session()
        return []

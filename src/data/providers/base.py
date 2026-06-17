"""Abstract market data provider interface.

All broker/data adapters implement this contract, allowing the rest of the
system to swap providers via the factory without changing any consumer code.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Any


class MarketDataProvider(ABC):
    """Base interface for market data providers."""

    @abstractmethod
    def get_ltp(self, instruments: list[str]) -> dict[str, float]:
        """Get Last Traded Price for a list of instrument symbols.
        Returns {symbol: ltp} dict."""
        ...

    @abstractmethod
    def get_candles(
        self,
        instrument: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """Get OHLCV candles for an instrument.
        Returns list of dicts with keys: ts, open, high, low, close, volume."""
        ...

    @abstractmethod
    def get_option_chain(
        self, underlying: str, expiry: date
    ) -> list[dict[str, Any]]:
        """Get full option chain for underlying+expiry.
        Returns list of dicts per strike with CE/PE data."""
        ...

    @abstractmethod
    def get_expiries(self, underlying: str) -> list[date]:
        """Get available expiry dates for an underlying."""
        ...

    @abstractmethod
    def get_contract_master(self) -> list[dict[str, Any]]:
        """Download and return the full contract master / instrument list."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name."""
        ...

    @property
    def is_available(self) -> bool:
        """Check if provider credentials and dependencies are available."""
        return True

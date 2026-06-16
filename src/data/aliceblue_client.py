"""Alice Blue (pya3) thin wrapper.

Responsibilities:
  - authenticate (session id)
  - download/cache contract masters (NSE index spot + NFO options)
  - resolve option instruments
  - fetch 1-min historical candles -> normalized polars DataFrame

NOTE: pya3 method signatures below match pya3 as of 2024-2025. Verify against
the installed pya3 version once API is approved and creds are filled. Anything
uncertain is isolated in this file so the rest of the system stays stable.
"""
from __future__ import annotations

from datetime import date, datetime

import polars as pl

from config import settings

try:
    from pya3 import Aliceblue  # type: ignore
except Exception:  # pragma: no cover - pya3 optional until creds exist
    Aliceblue = None  # type: ignore


class AliceClient:
    def __init__(self) -> None:
        if Aliceblue is None:
            raise RuntimeError("pya3 not installed. pip install -r requirements.txt")
        if not settings.alice_ready:
            raise RuntimeError("ALICE_USER_ID / ALICE_API_KEY missing in .env")
        self.alice = Aliceblue(user_id=settings.alice_user_id, api_key=settings.alice_api_key)
        self.session = self.alice.get_session_id()

    def load_contracts(self, *exchanges: str) -> None:
        """Download contract masters. Call once per session before resolving."""
        for ex in exchanges or ("NSE", "NFO"):
            self.alice.get_contract_master(ex)

    def index_instrument(self, name: str):
        """Spot/index instrument, e.g. name='NIFTY 50' or 'NIFTY BANK'."""
        return self.alice.get_instrument_by_symbol("INDICES", name)

    def option_instrument(self, symbol: str, expiry: date, strike: int, is_ce: bool):
        """Resolve one option contract. symbol e.g. 'NIFTY', 'BANKNIFTY', 'RELIANCE'."""
        return self.alice.get_instrument_for_fno(
            exch="NFO",
            symbol=symbol,
            expiry_date=expiry,
            is_fut=False,
            strike=strike,
            is_CE=is_ce,
        )

    def fetch_1m(
        self, instrument, start: datetime, end: datetime, indices: bool = False
    ) -> pl.DataFrame:
        """Fetch 1-min candles for an instrument. Returns ts/ohlc/volume.
        pya3.get_historical -> pandas DataFrame with a 'datetime' column.
        """
        pdf = self.alice.get_historical(instrument, start, end, "1", indices)
        if pdf is None or len(pdf) == 0:
            return pl.DataFrame()
        df = pl.from_pandas(pdf)
        # pya3 columns: datetime, open, high, low, close, volume (names can vary)
        rename = {c: c.lower() for c in df.columns}
        df = df.rename(rename)
        ts_col = "datetime" if "datetime" in df.columns else df.columns[0]
        return df.select(
            pl.col(ts_col).cast(pl.Datetime("us")).alias("ts"),
            pl.col("open").cast(pl.Float64),
            pl.col("high").cast(pl.Float64),
            pl.col("low").cast(pl.Float64),
            pl.col("close").cast(pl.Float64),
            pl.col("volume").cast(pl.Int64),
        )

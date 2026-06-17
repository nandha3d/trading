"""Canonical column schemas for the Parquet data lake.

All timestamps are IST, naive (Asia/Kolkata wall clock) to match NSE session.
One row = one 1-minute candle for one instrument.
"""
from __future__ import annotations

import pyarrow as pa

# 1-min options candle (CE/PE per strike per expiry)
OPTIONS_SCHEMA = pa.schema(
    [
        ("underlying", pa.string()),     # NIFTY, BANKNIFTY, RELIANCE, ...
        ("expiry", pa.date32()),         # contract expiry, YYYY-MM-DD
        ("strike", pa.int32()),          # strike price
        ("option_type", pa.string()),    # "CE" | "PE"
        ("ts", pa.timestamp("s")),       # candle open time, IST, 1-min
        ("open", pa.float32()),
        ("high", pa.float32()),
        ("low", pa.float32()),
        ("close", pa.float32()),
        ("volume", pa.int32()),
        ("oi", pa.int32()),              # open interest (0 if source lacks it)
    ]
)

# 1-min spot / index candle (underlying price — needed for strike selection)
SPOT_SCHEMA = pa.schema(
    [
        ("underlying", pa.string()),
        ("ts", pa.timestamp("s")),
        ("open", pa.float32()),
        ("high", pa.float32()),
        ("low", pa.float32()),
        ("close", pa.float32()),
        ("volume", pa.int32()),
    ]
)

OPTIONS_COLS = [f.name for f in OPTIONS_SCHEMA]
SPOT_COLS = [f.name for f in SPOT_SCHEMA]

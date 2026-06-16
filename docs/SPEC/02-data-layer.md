# 02 — Data Layer

Status: `IMPLEMENTED` (storage) · `PLANNED` (candle aggregation, warmup)

## 1. Responsibilities

The data layer is the **single source of market truth**. It must guarantee that any value
the engine reads is (a) real, (b) timestamped correctly, (c) free of duplicates, and
(d) never silently null. Garbage here corrupts every downstream number.

## 2. Storage Engine

- **DuckDB**, single file: `data/market.duckdb`.
- Columnar → fast range scans over millions of option rows.
- Single cached connection, thread-locked; reads via short-lived cursors.
- Idempotent reload: `clear_*` then insert → no accidental duplication.

## 3. Schema

### `spot_1m` — underlying 1-minute OHLCV
| Column | Type | Null? | Notes |
|--------|------|-------|-------|
| underlying | VARCHAR | NOT NULL | "NIFTY" / "BANKNIFTY" / "FINNIFTY" |
| ts | TIMESTAMP | NOT NULL | IST, floored to minute |
| open | DOUBLE | | |
| high | DOUBLE | | |
| low | DOUBLE | | |
| close | DOUBLE | | |
| volume | BIGINT | | spot index volume (may be 0 for index) |

Primary key (logical): `(underlying, ts)`.

### `options_1m` — option chain 1-minute OHLC + OI
| Column | Type | Null? | Notes |
|--------|------|-------|-------|
| underlying | VARCHAR | NOT NULL | |
| expiry | DATE | NOT NULL | |
| strike | INTEGER | NOT NULL | |
| option_type | VARCHAR | NOT NULL | "CE" / "PE" only (enforced) |
| ts | TIMESTAMP | NOT NULL | IST, floored to minute |
| open/high/low/close | DOUBLE | | premium |
| volume | BIGINT | | |
| oi | BIGINT | | open interest |

Primary key (logical): `(underlying, expiry, strike, option_type, ts)`.

## 4. Integrity Rules (enforced at write)

1. **NOT NULL keys** — any row missing a key field is rejected and counted, never stored.
2. **option_type whitelist** — only `CE`/`PE`; others rejected.
3. **Dedupe** — `dedupe_options()` keeps the highest-volume/oi row per logical key (in-place DELETE preserves constraints).
4. **Reject logging** — rejected counts surfaced at ingest (`[reject] table: dropped N rows`).
5. **Verify** — `verify()` reports row counts, ts coverage `[min,max]`, null-key count, dup-key count per table. Run after every ingest.

## 5. Ingestion Sources

| Source | Use | Notes |
|--------|-----|-------|
| Alice Blue `pya3` | Live/recent chains | Broker API; approval-gated. |
| Kaggle datasets | Historical bulk | Bootstrap multi-year history. |
| CSV import | Manual / vendor | Validated through the same write path. |

Ingestion pipeline: `raw → normalise columns → validate keys/types → dedupe → insert → verify`.
**No raw row reaches a table without passing validation.**

## 6. Candle Aggregation (`candles.py`) — `PLANNED`

The engine never uses raw 1-minute bars for indicators; it uses **resampled interval candles**.

### Resampling rule
For interval `M` minutes, group bars by `floor(ts, M minutes)`:

| Output | Aggregation |
|--------|-------------|
| open | first bar's open in the bucket |
| high | max high in the bucket |
| low | min low in the bucket |
| close | last bar's close in the bucket |
| volume | sum of volume in the bucket |
| ts | bucket start (label = bar open time) |

### Closed-bar guarantee
Only **fully elapsed** buckets are emitted. The partial final bucket of a session (e.g. a
5-min bar starting 15:28 when data ends 15:30) is **dropped** unless its full interval has
data. This is the core anti-look-ahead / anti-repaint guarantee.

### Supported intervals
`1, 3, 5, 15, 30, 60` minutes. (Session = 09:15–15:30 IST = 375 min.)

### Session boundaries
- Bucketing resets per trading day (no cross-day candles unless interval = day).
- VWAP and other session indicators reset at 09:15.

## 7. Warmup Handling

Indicators need prior bars before yielding valid values. A decision at 09:20 on day D needs
history from before day D.

### Warmup lookback formula
```
bars_needed   = max_indicator_period × safety_factor   (safety_factor = 3)
minutes_needed = bars_needed × interval_min
days_needed    = ceil(minutes_needed / 375) + 1        (+1 for partial-session buffer)
```
Example: RSI(14) on 5-min → 14×3 = 42 bars → 210 min → `ceil(210/375)+1 = 2` lookback days.

### Fetch-with-warmup
```
fetch_with_warmup(underlying, day, interval, max_period):
  start = day − days_needed (trading days)
  spot  = read_spot(underlying, start_00:00, day_15:30)
  bars  = resample(spot, interval)            # continuous across days
  return bars                                  # engine slices to `day` after compute
```
Indicators are computed on the **continuous** multi-day series so smoothing carries proper
state into day D, then results are sliced to day D's bars for evaluation. This avoids the
"indicator resets every morning" bug that makes EMA/RSI wrong for the first hour.

## 8. Missing-Data Policy

| Situation | Action |
|-----------|--------|
| No spot for the day | Skip day, `skip_reason="no_spot_data"`. |
| Warmup window short (new listing) | Skip day, `skip_reason="insufficient_warmup"`. |
| Option strike absent at entry minute | Skip trade, `skip_reason="no_option_quote"`. |
| Gap inside session (missing minutes) | Forward-fill **prices only** within the day for MTM; never forward-fill across days; never fabricate OHLC for indicator bars (gap bar omitted). |
| Zero/negative premium | Treat as invalid quote; skip leg resolution. |

**Never** substitute a synthetic or interpolated value into an indicator input.

## 9. Time Semantics

- All timestamps timezone-naive **IST**, floored to the minute.
- Trading days = weekdays present in data (holidays naturally absent).
- Expiry comparison uses `DATE`; DTE = `(expiry − day).days`.

## 10. Performance Notes

- Range reads are pushed to DuckDB (WHERE on indexed keys), not filtered in Python.
- Per-day streaming: the engine processes one day at a time; the full chain is never resident.
- Resampling is vectorised in Polars (`group_by_dynamic`), not Python loops.

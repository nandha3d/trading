# 01 — Architecture

Status: `PLANNED`

## 1. Layered Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  PRESENTATION  (React + TypeScript, Vite)                         │
│  Strategy Builder · Condition Builder · Indicator Manager         │
│  Payoff Builder · Options Chain · Results & Analytics             │
└───────────────────────────────┬─────────────────────────────────┘
                                 │ HTTPS / JSON  (/api/*)
┌───────────────────────────────▼─────────────────────────────────┐
│  API  (FastAPI, async)                                            │
│  Request validation (Pydantic) · DTO ↔ domain mapping            │
│  Route handlers · error envelope · OpenAPI schema                 │
└───────────────────────────────┬─────────────────────────────────┘
                                 │  (asyncio.to_thread for blocking)
┌───────────────────────────────▼─────────────────────────────────┐
│  DOMAIN / ENGINE  (pure Python, Polars)                          │
│  ┌──────────┐ ┌────────────┐ ┌───────────┐ ┌─────────────────┐  │
│  │ Candles  │ │ TA Library │ │ Condition │ │ Execution Engine │  │
│  │ resample │ │ (ta.py)    │ │ Evaluator │ │ (intraday walk)  │  │
│  └──────────┘ └────────────┘ └───────────┘ └─────────────────┘  │
│  ┌──────────┐ ┌────────────┐ ┌───────────┐ ┌─────────────────┐  │
│  │ Risk Mgr │ │ Cost Model │ │ Metrics   │ │ Strike Selector  │  │
│  └──────────┘ └────────────┘ └───────────┘ └─────────────────┘  │
└───────────────────────────────┬─────────────────────────────────┘
                                 │  storage read API (Polars frames)
┌───────────────────────────────▼─────────────────────────────────┐
│  DATA  (DuckDB, columnar, single file market.duckdb)             │
│  options_1m · spot_1m   (NOT NULL keys, integrity-checked)       │
│  Ingestion: Alice Blue pya3 / Kaggle / CSV → validate → insert   │
└──────────────────────────────────────────────────────────────────┘
```

## 2. Module Map (Python core)

| Module | Responsibility | Pure? | Reads DB? |
|--------|----------------|-------|-----------|
| `src/data/storage.py` | DuckDB connection, typed reads/writes, integrity | No | Yes |
| `src/data/schema.py` | Column definitions, dtypes | Yes | No |
| `src/data/options_math.py` | BSM price, IV solver, Greeks | Yes | No |
| `src/backtest/candles.py` | Resample `spot_1m` → interval OHLC, warmup fetch | No | Yes |
| `src/backtest/ta.py` | Indicator library (TradingView parity) | Yes | No |
| `src/backtest/conditions.py` | Operand resolve, condition/tree eval, cross detect | Yes | No |
| `src/backtest/strategy.py` | Domain models: Leg, Strategy, Indicator, ConditionTree | Yes | No |
| `src/backtest/strikes.py` | ATM / premium / delta strike resolution | No | Yes |
| `src/backtest/execution.py` | Intraday minute walk, fills, MTM | No | Yes |
| `src/backtest/risk.py` | SL/TP/trailing/portfolio exit state machine | Yes | No |
| `src/backtest/costs.py` | Statutory cost model | Yes | No |
| `src/backtest/metrics.py` | Performance stats, drawdown, Monte Carlo | Yes | No |
| `src/backtest/engine.py` | Orchestrator: per-day pipeline, range driver | No | Yes |
| `src/backtest/greeks.py` | Delta/theta helpers for strike selection | Yes | No |

**Purity rule:** `ta.py`, `conditions.py`, `risk.py`, `costs.py`, `metrics.py` MUST be pure
(no I/O, no clock, no RNG except seeded). This makes them unit-testable against fixtures and
guarantees determinism.

## 3. Per-Day Execution Pipeline

```
run_day(strategy, day, expiry):
  1. LOAD      spot_1m[day − warmup … day]           → candles.fetch_with_warmup
  2. RESAMPLE  → interval OHLC (closed bars only)     → candles.resample
  3. INDICATORS precompute every IndicatorSpec        → ta.compute(*)
                 → dict[name → Series]  (vectorised, whole series at once)
  4. PREFILTER weekday / PCR / IVR / VIX regime       → returns skip_reason or OK
  5. WALK candles i = 0..N:
       if FLAT:
         if eval(entry_tree, i): OPEN legs @ candle-close minute
       elif IN_POSITION:
         update MTM from option 1-min prices
         risk = risk_mgr.step(mtm, ts)        # per-leg SL/TP, portfolio SL/TP/trail
         if risk.exit:        CLOSE per reason
         elif eval(exit_tree, i): CLOSE "SIGNAL_EXIT"
       at force_exit_time: CLOSE "TIME"
  6. COST      cost_model.apply(legs)                 → per-leg charges
  7. EMIT      Trade(legs, gross, cost, net, reasons, signal_snapshot)
```

Key point: **indicators are vectorised once** over the full warmup+day series (step 3),
then the walk (step 5) only **indexes** precomputed arrays. No per-candle recomputation →
fast and repaint-free.

## 4. Data Flow Contracts

### Storage → Engine
- `read_spot(underlying, start, end)` → Polars frame `[ts, open, high, low, close, volume]`, sorted by `ts`.
- `read_options(underlying, start, end, expiry, strikes?, option_type?)` → `[ts, expiry, strike, option_type, open, high, low, close, volume, oi]`.
- All timestamps are timezone-naive IST, floored to the minute.

### Engine → API
- `BacktestResult { trades: list[Trade], stats: Stats, skipped: list[Skip] }`.
- `Trade` carries: day, legs (entry/exit/qty/reason/action), gross, cost, net, entry_spot, exit_time, signal snapshot.

### API → Frontend
- See [09-api-spec.md](09-api-spec.md) for the full JSON contract.

## 5. Concurrency Model

- FastAPI handlers are `async`; CPU-bound backtest runs in `asyncio.to_thread` so the event
  loop stays responsive.
- DuckDB uses a single cached connection guarded by a lock; reads use short-lived cursors.
- Parameter sweeps / multiple cases run sequentially in v1 (deterministic ordering);
  v2 may parallelise across a process pool with per-process DB cursors.

## 6. Error Handling

| Layer | Strategy |
|-------|----------|
| Data | Missing/partial data → engine emits `skip_reason`, never crashes the run. |
| Engine | Per-day exceptions are caught, logged with the day, and surfaced as a skip; the run continues. |
| API | Domain `ValueError` → HTTP 400 with message; unexpected → 500 with safe envelope. |
| Frontend | Typed error from `_json<T>`; shown inline, never a silent blank. |

## 7. Configuration

- `config/settings.py`: `data_dir`, `db_path`, default risk-free rate, default lot/strike specs.
- `CONTRACT_SPECS` (in `strategy.py`): per-underlying `lot_size`, `strike_step`.
- No secrets in code; broker credentials (ingestion only) via environment.

## 8. Extensibility Seams

- **New indicator:** add a function to `ta.py` + a branch in the indicator factory + a fixture in [11](11-testing-validation.md). No engine change.
- **New operator:** add to the operator enum + `eval_condition`. No UI change beyond the dropdown.
- **New underlying:** add a `CONTRACT_SPECS` entry + ingest data. No code change.
- **New cost component:** add to `costs.py` rate table; covered by the contract-note test.

## 9. Technology Choices & Rationale

| Choice | Why |
|--------|-----|
| **Polars** over Pandas | Faster vectorised TA, explicit null handling, no index foot-guns. |
| **DuckDB** | Columnar, embedded, SQL, handles multi-GB option chains without a server. |
| **FastAPI + Pydantic** | Schema-validated DTOs, free OpenAPI, async. |
| **React + Vite + Tailwind** | Fast iteration, component reuse, dark institutional UI. |
| **Recharts** | Declarative payoff/equity/OI charts. |
| **Pure-function core** | Determinism + unit-testability against reference fixtures. |

# 12 — Roadmap

Status: `PLANNED`

> Phased build order from the current state to the full enterprise spec. Each phase is
> independently shippable and ends with a validation gate. Phases are ordered so accuracy
> foundations land before features that depend on them.

## Current State (baseline)

| Area | Status |
|------|--------|
| DuckDB storage + integrity | `IMPLEMENTED` |
| Per-leg SL/TP/trail (premium/underlying units) | `IMPLEMENTED` |
| Portfolio SL/target/trail | `IMPLEMENTED` |
| Entry filters (weekday, PCR, IVR, VIX regime) | `IMPLEMENTED` |
| Crude indicator entry (daily synthetic spot) | `IMPLEMENTED` (to be replaced) |
| Cost model (statutory, side-aware) | `IMPLEMENTED` |
| Metrics, Monte Carlo, monthly grid | `IMPLEMENTED` |
| Templates, payoff builder, options chain w/ greeks | `IMPLEMENTED` |
| Frontend: builder, results, drawer | `IMPLEMENTED` |

The crude indicator path is the main accuracy debt this roadmap repays.

---

## Phase 1 — Accurate Indicator Foundation `[accuracy-critical]`

**Goal:** TradingView-parity indicators on real candles. Replace synthetic-spot daily logic.

1. `ta.py` — SMA, EMA (seeded), RSI/ATR/ADX (Wilder), Bollinger (ddof=0), MACD, Supertrend, VWAP, Stochastic.
2. `tests/fixtures/ta/` + parity tests (≤ 0.01).
3. `candles.py` — resample `spot_1m` → interval OHLC (closed bars), warmup fetch.
4. Candle/warmup unit tests.

**Gate:** all indicator parity tests pass; candle resample verified against hand-computed bars.

---

## Phase 2 — Condition Engine `[accuracy-critical]`

**Goal:** Quantman-style entry/exit rule trees with correct cross detection.

1. `conditions.py` — Operand resolve, operators, cross-above/below, AND/OR groups.
2. Condition unit tests (cross-once, null-false, offset, precedence).
3. `strategy.py` — `IndicatorSpec` list + `entry_tree`/`exit_tree` on the domain model.

**Gate:** condition unit suite green; no-look-ahead canary test passes.

---

## Phase 3 — Candle-Driven Execution `[accuracy-critical]`

**Goal:** Engine evaluates conditions per closed candle; replaces "enter every day at time".

1. `execution.py` — intraday walk with FLAT/IN_POSITION state machine.
2. Integrate precomputed indicators + trees into `engine.run_day`.
3. Strike selection unchanged; add `signal_snapshot` to trade records.
4. Skip reasons for no-signal days.

**Gate:** integration test (known strategy, fixed window) matches expected report; reproducibility hash stable.

---

## Phase 4 — API + Frontend Wiring

**Goal:** Expose indicators + condition trees end to end.

1. `api/models.py` — `IndicatorSpec`, `OperandSpec`, `ConditionSpec`, `ConditionGroupSpec`; extend `BacktestRequest`.
2. `api/routes/backtest.py` — validate refs/operators; map to domain.
3. `types.ts` — mirror models.
4. `IndicatorManager.tsx` + `ConditionBuilder.tsx`; mount in `StrategyBuilder`.
5. `tsc --noEmit` clean; request serialises to [09](09-api-spec.md) shape.

**Gate:** end-to-end run of an EMA-cross strategy from UI → report with signal snapshots.

---

## Phase 5 — Fill & Cost Realism

**Goal:** Tighten execution realism and cost auditing.

1. OHLC-aware intrabar SL fills (stop level if `low ≤ stop ≤ high`).
2. Slippage reporting split from statutory charges in the UI.
3. Cost golden test vs real contract note (≤ ₹0.50).
4. Period-dated `RATE_TABLE` for historically-correct charges.

**Gate:** cost golden passes; intrabar-fill unit tests pass.

---

## Phase 6 — Analytics Depth

**Goal:** Institutional reporting.

1. Sortino, Calmar, max-DD duration, underwater plot.
2. Regime/DTE/weekday/exit-reason distribution tables.
3. Exit-reason distribution chart in `ResultsPanel`.
4. Block-bootstrap Monte Carlo option for serially-correlated strategies.

**Gate:** metric parity tests (backend vs frontend) green.

---

## Phase 7 — Scale & Compare

**Goal:** Research throughput.

1. Multiple cases / parameter sweeps (Quantman "Multiple Case") run side by side.
2. Process-pool parallelism with per-process DB cursors (keep determinism).
3. Comparison report (equity curves overlaid, stat table per case).
4. Indicator preview chart (`/api/indicators/preview`).

**Gate:** sweep of N cases reproducible; parallel results identical to sequential.

---

## Phase 8 — Hardening & Productionisation

1. Position sizing modes (fixed capital, risk-based) + margin model.
2. Run persistence (save/load runs, share links).
3. Full CI gate set ([11 §11](11-testing-validation.md)).
4. Validation-coverage dashboard; flag unvalidated indicators in UI.

**Gate:** all CI gates enforced on main; validation dashboard at 100% for exposed indicators.

---

## Dependency Order (critical path)

```
Phase 1 (ta + candles)  ──►  Phase 2 (conditions)  ──►  Phase 3 (execution)
                                                            │
                                                            ▼
                                              Phase 4 (API + UI)
                                                            │
                         ┌──────────────────┬──────────────┴───────────┐
                         ▼                  ▼                          ▼
                  Phase 5 (fills/cost)  Phase 6 (analytics)     Phase 7 (scale)
                                                            │
                                                            ▼
                                              Phase 8 (hardening)
```

Phases 1–3 are the accuracy backbone and must land in order. Phases 5–7 can proceed in
parallel once Phase 4 exposes the engine. Phase 8 closes out productionisation.

## Definition of Done (v1)

A user loads an EMA/RSI strategy on 5-min NIFTY candles, runs it over multiple years, and
receives a report whose indicators match TradingView (≤ 0.01), whose costs match a contract
note (≤ ₹0.50), whose equity curve is reproducible (stable hash), and where every trade is
explained by an entry/exit reason plus an entry-signal snapshot.

# 11 — Testing & Validation

Status: `PLANNED`

> Accuracy is a claim only if it is tested. This document defines the fixtures, golden tests,
> and CI gates that make "TradingView parity" and "contract-note exact" enforceable rather
> than aspirational. No indicator or cost change merges without its test passing.

## 1. Test Pyramid

```
        ┌───────────────────────────┐
        │  E2E (1)                   │  full backtest on fixed data → golden report hash
        ├───────────────────────────┤
        │  Integration (few)        │  engine + storage + costs on a sample window
        ├───────────────────────────┤
        │  Golden / Reference (many)│  indicators vs TradingView, costs vs contract note
        ├───────────────────────────┤
        │  Unit (most)              │  pure functions: ta, conditions, risk, metrics
        └───────────────────────────┘
```

## 2. Indicator Reference Fixtures (`tests/fixtures/ta/`)

For each indicator, a fixed input bar series + expected output exported from TradingView.

```
tests/fixtures/ta/
  nifty_5m_sample.csv          # 200 bars OHLCV, fixed
  ema9_expected.csv            # TradingView EMA(9) on close
  ema21_expected.csv
  rsi14_expected.csv
  atr14_expected.csv
  bb20_2_expected.csv          # basis/upper/lower
  macd_12_26_9_expected.csv    # macd/signal/hist
  supertrend_10_3_expected.csv # line + dir
  stoch_14_3_expected.csv      # k + d
```

### Assertion
```python
def test_ema9_parity():
    bars = load("nifty_5m_sample.csv")
    got  = ta.ema(bars["close"], 9)
    exp  = load("ema9_expected.csv")["ema9"]
    assert max_abs_diff(got, exp, ignore_warmup=True) <= 0.01
```
`ignore_warmup`: compare only where the reference has a value (skip leading nulls). Tolerance
**0.01** absolute. A failing parity test blocks merge and prevents the `VALIDATED` status.

## 3. Cost Golden Test (`tests/fixtures/costs/`)

A real (anonymised) broker contract note for a known multi-leg trade.

```
contract_note_straddle.json:
  legs, entry/exit prices, qty, broker-reported charges breakdown, total
```
```python
def test_cost_matches_contract_note():
    note = load("contract_note_straddle.json")
    for leg in note.legs:
        model = costs.leg_cost(leg.entry, leg.exit, leg.qty, leg.action, PARAMS)
        assert abs(model - leg.broker_cost) <= 0.50
```

## 4. Condition Engine Unit Tests

| Test | Scenario |
|------|----------|
| cross_above_fires_once | value steps from below to above → True exactly on the crossing bar, False after. |
| cross_needs_prev | at i=0 always False. |
| null_operand_false | warmup null → condition False, no exception. |
| and_or_semantics | AND requires all; OR requires any; empty group False. |
| offset_resolution | `close[offset=3]` reads bar i-3. |
| dangling_ref_rejected | unknown indicator ref → validation error at API. |

## 5. Risk Engine Unit Tests (synthetic MTM paths)

| Test | Path | Expect |
|------|------|--------|
| target_hits | MTM rises to +target | exit TARGET at first breach bar |
| stop_hits | MTM falls to −SL | exit STOPLOSS |
| trail_locks | rise to +50% then fall | exit TRAIL at peak−trail |
| precedence | stop & target same bar | STOPLOSS wins |
| leg_sl_isolated | one leg breaches | only that leg closes; others continue |

## 6. No-Look-Ahead Test

Inject a "future leak" canary: a synthetic indicator whose value at bar i equals close at
i+1. The engine must **not** be able to use it (resolution is index ≤ i). A test asserts that
shifting input data forward by one bar changes results in the expected causal direction only.

## 7. Determinism / Reproducibility Gate

```python
def test_reproducible_equity_curve():
    h = [sha256(run(config).equity_curve) for _ in range(20)]
    assert len(set(h)) == 1            # identical across runs
```
Monte Carlo uses a fixed seed; this test also covers RNG determinism.

## 8. Integration Test (engine + storage + costs)

Run a known strategy (e.g. short straddle, ATM, 09:20→15:15, SL 100% / TP 50%) over a fixed
1-month window of seeded test data in a temp DuckDB; assert the trade count, win rate, and
net P&L match a checked-in expected report (within rounding).

## 9. E2E Golden Report

Full pipeline on a fixed dataset + fixed config → serialise the response → hash → compare to a
committed golden hash. Any change to engine/cost/metric math that alters output must update
the golden in the same PR (forces a conscious review of accuracy-affecting changes).

## 10. Frontend Parity Tests

- **Cost parity**: a sample trade through the TS cost port equals the Python `leg_cost`.
- **Metric parity**: MDD, profit factor, Monte Carlo (seeded) computed in TS equal backend.
- Run via Vitest with fixtures shared from `tests/fixtures/`.

## 11. CI Gates (block merge)

1. `pytest` (unit + golden + integration) green.
2. Indicator parity ≤ 0.01 on all fixtures.
3. Cost golden ≤ ₹0.50.
4. Reproducibility hash stable.
5. `tsc --noEmit` clean.
6. Frontend parity tests green.
7. No `synthetic spot` import in execution paths (static grep gate).

## 12. Validation Status Tracking

Each indicator/cost component carries a status (`IMPLEMENTED` → `VALIDATED`). The UI may only
surface `VALIDATED` indicators as production-ready; others are flagged "beta — unvalidated".
A dashboard in `docs/` lists current validation coverage.

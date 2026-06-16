# 00 — Overview

Status: `PLANNED`

## 1. Vision

A backtesting platform that an options desk, prop firm, or serious systematic trader can
use as the single source of truth for strategy validation. It must close the gap between
*"the backtest said +40%"* and *"live traded -5%"* by eliminating the structural lies in
typical retail tools.

The four lies this platform refuses to tell:

1. **Synthetic spot.** Deriving spot from `CE − PE + strike` introduces 10–50 point error
   from cost-of-carry and bid/ask. We use the **real underlying OHLC** for all signal and
   strike-selection logic.
2. **Look-ahead.** Resampling to daily and "entering at the open knowing the close" inflates
   returns. We evaluate signals **only on closed candles** in chronological order.
3. **Free trading.** Ignoring STT, GST, exchange, SEBI, stamp, and slippage turns losing
   strategies into winners. We model the **full Indian statutory stack**, side-aware.
4. **Survivorship / repaint.** We snapshot the exact option chain available at the decision
   minute and never use a value that would not have existed yet.

## 2. Scope

### In scope
- Indian index options: NIFTY, BANKNIFTY, FINNIFTY (extensible via contract specs).
- Intraday and positional (multi-day-to-expiry) strategies.
- Multi-leg structures (straddle, strangle, condor, butterfly, ratio, calendar, custom N-leg).
- Indicator-driven entry/exit (SMA, EMA, RSI, Supertrend, Bollinger, MACD, ATR, ADX, VWAP, Stochastic).
- Condition trees (AND/OR groups, cross-above/below, level comparisons).
- Per-leg and portfolio-level risk (SL, TP, trailing SL, re-entry).
- Statutory-exact cost modelling.
- Institutional analytics (Sharpe, Sortino, Calmar, profit factor, recovery factor, Monte Carlo MDD, regime/streak analysis).

### Out of scope (v1)
- Equity/futures cash backtesting (architecture allows later extension).
- Live order routing / execution (backtest only; broker integration is a separate system).
- American-style options, currency/commodity options.
- Tick-level (sub-minute) simulation — minimum granularity is 1-minute candles.

## 3. Glossary

| Term | Definition |
|------|------------|
| **Candle / Bar** | OHLCV aggregate over a fixed interval (1/3/5/15/30/60 min). |
| **Closed candle** | A bar whose interval has fully elapsed; the only bar a decision may read. |
| **Warmup** | Prior bars required before an indicator yields a valid value. |
| **Leg** | One option position (action + type + strike + qty). |
| **Strategy** | A set of legs with shared entry/exit logic and risk rules. |
| **Case** | A named variant of a strategy run in the same backtest (Quantman "Multiple Case"). |
| **DTE** | Days to expiry. |
| **ATM** | At-the-money strike (nearest to spot). |
| **MTM** | Mark-to-market: current notional P&L of an open position. |
| **PCR** | Put-Call Ratio = total PE OI / total CE OI. |
| **IVR** | Implied Volatility Rank — our synthetic VIX proxy from ATM straddle IV. |
| **Slippage** | Adverse fill vs reference price, modelled as % of premium. |
| **Repaint** | Using a future/intrabar value that would not have existed at decision time. |
| **Skip reason** | Machine-readable tag for why a candidate day produced no trade. |

## 4. Personas

| Persona | Need |
|---------|------|
| **Systematic trader** | Validate indicator strategies with confidence costs/fills are realistic. |
| **Options desk quant** | Stress-test multi-leg structures across regimes; export trades for audit. |
| **Risk manager** | See worst-case drawdown (Monte Carlo), recovery factor, streak risk. |
| **Strategy researcher** | Rapidly compare cases (parameter sweeps) side by side. |

## 5. Accuracy Targets (binding)

| Domain | Target | Validation |
|--------|--------|------------|
| Indicators | ≤ 0.01 abs error vs TradingView | Fixture suite ([11](11-testing-validation.md)) |
| Spot source | Real `spot_1m` only | Static check: no parity-spot import in engine |
| Charges | ≤ ₹0.50 vs broker contract note | Golden contract-note test |
| Determinism | Identical equity-curve hash across 100 runs | CI reproducibility gate |
| No look-ahead | Decision *i* reads only ≤ *i* | Code review + offset-injection test |

## 6. Non-Functional Requirements

- **Performance:** 1 year of 5-min NIFTY, single strategy, ≤ 5 s wall time on a laptop.
- **Memory:** stream per-day; never load full multi-year option chain into RAM at once.
- **Storage:** columnar (DuckDB) with NOT NULL key constraints; idempotent reload.
- **Observability:** structured run log with per-day decision trace (optional verbose mode).
- **Portability:** Windows + Linux; pure-Python core (Polars/DuckDB), no OS-specific deps.

## 7. Success Definition

The platform is "done for v1" when a user can: load a Quantman-style indicator strategy,
run it over a multi-year window, and receive a report whose indicators match TradingView,
whose costs match a real contract note, and whose equity curve is bit-for-bit reproducible —
with every trade explainable by an entry/exit reason and a cost breakdown.

# Enterprise Options Backtesting Platform — Technical Specification

> Industry-standard, institutional-grade backtesting engine for Indian index options
> (NIFTY / BANKNIFTY / FINNIFTY). Built for **accuracy first**: TradingView/Quantman
> parity on indicators, tick-faithful intraday execution, and statutory-exact cost
> modelling.

## Purpose

This specification defines a backtesting system that produces results an institutional
trader can trust for capital allocation. Every number — P&L, drawdown, Sharpe, win rate
— must be reproducible, auditable, and free from the silent inaccuracies that plague
retail backtesters (synthetic spot, look-ahead bias, repainting indicators, wrong
smoothing constants, ignored charges).

## Design Principles

| Principle | Meaning |
|-----------|---------|
| **No look-ahead** | A decision at candle *i* uses only data available at the close of candle *i*. |
| **No repaint** | Indicators computed on closed candles only; intrabar values never used. |
| **Reference parity** | Indicator math matches TradingView/Quantman to within 0.01 on validation fixtures. |
| **Statutory exactness** | Charges modelled per NSE/SEBI rate cards, side-aware (STT on sell). |
| **Deterministic** | Same input → byte-identical output. Seeded RNG for Monte Carlo. |
| **Auditable** | Every trade carries entry/exit reason, signal snapshot, and cost breakdown. |
| **Fail loud** | Missing data, bad ticks, or unmet warmup → explicit skip reason, never silent zero. |

## Specification Index

| # | Document | Scope |
|---|----------|-------|
| 00 | [Overview](00-overview.md) | Vision, scope, glossary, accuracy targets |
| 01 | [Architecture](01-architecture.md) | System layers, module map, data flow |
| 02 | [Data Layer](02-data-layer.md) | Sourcing, storage, integrity, candle aggregation, warmup |
| 03 | [Indicator Library](03-indicators.md) | Exact formulas, smoothing, reference parity |
| 04 | [Condition Engine](04-condition-engine.md) | Operands, operators, cross detection, condition trees |
| 05 | [Execution Engine](05-execution-engine.md) | Order simulation, fills, slippage, intraday walk |
| 06 | [Cost Model](06-cost-model.md) | Brokerage, STT, exchange, GST, SEBI, stamp duty |
| 07 | [Risk Management](07-risk-management.md) | SL/TP/trailing, portfolio exits, position sizing |
| 08 | [Metrics & Analytics](08-metrics-analytics.md) | Performance metrics, drawdown, Monte Carlo |
| 09 | [API Specification](09-api-spec.md) | REST contract, request/response schemas |
| 10 | [Frontend Specification](10-frontend-spec.md) | UI components, condition builder, reports |
| 11 | [Testing & Validation](11-testing-validation.md) | Accuracy fixtures, regression, CI gates |
| 12 | [Roadmap](12-roadmap.md) | Phased build order, milestones, acceptance |

## Accuracy Targets (Acceptance Bar)

- Indicators: max abs error ≤ **0.01** vs TradingView on the standard NIFTY 5-min fixture.
- Spot: **real** `spot_1m` OHLC only — synthetic put-call-parity spot is **prohibited** in execution paths.
- Charges: match a Zerodha/AngelOne contract note to within **₹0.50** per round-trip leg.
- Reproducibility: 100 consecutive runs of the same config → identical equity curve hash.

## Status Legend (used throughout)

`PLANNED` · `IN PROGRESS` · `IMPLEMENTED` · `VALIDATED` (passes reference fixtures)

# 10 — Frontend Specification

Status: `IN PROGRESS`

> React + TypeScript + Vite + Tailwind, dark institutional theme. Three tabs: Backtest,
> Payoff Builder, Options Chain. This document covers the components needed for the
> indicator/condition workflow and the analytics report.

## 1. Component Tree

```
App
├── Header (tabs, DB status)
├── Backtest tab
│   ├── StrategyBuilder (left sidebar)
│   │   ├── TemplateSelector
│   │   ├── Leg editor
│   │   ├── IndicatorManager            ← NEW
│   │   ├── ConditionBuilder (entry)    ← NEW
│   │   ├── ConditionBuilder (exit)     ← NEW
│   │   ├── EntryConditions (filters)
│   │   └── ExitConditions (risk)
│   └── ResultsPanel (main)
│       ├── Stats cards
│       ├── Equity curve
│       ├── Monthly returns grid
│       ├── Monte Carlo panel
│       ├── Exit-reason distribution    ← NEW
│       ├── Skipped breakdown
│       ├── Trade log (clickable rows)
│       └── TradeDrawer
├── Payoff Builder tab → PayoffBuilder
└── Options Chain tab → OptionsChain
```

## 2. IndicatorManager (`PLANNED`)

Mirrors the Quantman "Add Indicator" dialog.

```
┌ INDICATORS ────────────────────────[+ Add]┐
│ ema9   EMA(9)  close          [edit][del] │
│ ema21  EMA(21) close          [edit][del] │
│ rsi14  RSI(14) close          [edit][del] │
└────────────────────────────────────────────┘

Add/Edit modal:
  Type    [EMA v]   (SMA/EMA/RSI/ATR/ADX/BBANDS/MACD/SUPERTREND/VWAP/STOCH)
  Name    [ema9]    (unique; referenced in conditions)
  Period  [9]
  Field   [Close v] (close/open/high/low/hl2/hlc3/ohlc4)
  -- type-specific params reveal: BBANDS std, MACD fast/slow/signal,
     SUPERTREND mult, STOCH d-period --
  [Save]
```

Rules:
- `name` must be unique and non-empty; used as the condition reference key.
- Deleting an indicator referenced by a condition warns and blocks until the condition is fixed.
- Multi-output indicators (BBANDS/MACD/STOCH/SUPERTREND) expose bands in operand dropdowns as `name.band`.

## 3. ConditionBuilder (`PLANNED`)

Visual rule rows for entry and exit trees.

```
ENTRY WHEN   [AND v]
┌──────────────────────────────────────────────────────┐
│ [ema9 v]  [crosses above v]  [ema21 v]          [x]  │
│ [rsi14 v] [ >  v]            [const: 50]         [x]  │
│ [+ Add Condition]                                     │
└──────────────────────────────────────────────────────┘
EXIT WHEN    [OR v]
┌──────────────────────────────────────────────────────┐
│ [ema9 v]  [crosses below v]  [ema21 v]          [x]  │
└──────────────────────────────────────────────────────┘
```

Operand dropdown contents:
```
Price:      Close, Open, High, Low, HL2, HLC3
Indicators: <all defined names> + bands (bb.upper, macd.signal, ...)
Constant:   numeric input
Offset:     "n bars ago" stepper (default 0)
```
Operator dropdown: `> , < , >= , <= , == , crosses above , crosses below`.

Validation (client + server):
- No condition may reference an undefined indicator.
- Cross operators require both operands resolvable.
- Empty entry tree → warn "no entry signal; will use time entry or skip".

## 4. StrategyBuilder Additions

- Candle config row: **Interval** [5 min] · **Source** [Spot].
- Mount `IndicatorManager` above the condition builders.
- Mount entry/exit `ConditionBuilder`s between legs and risk panels.
- On Run, serialise to the [09](09-api-spec.md) request shape (indicators + entry_tree + exit_tree).

## 5. ResultsPanel Additions

- **Exit-reason distribution**: small bar/segmented chart of TARGET/STOPLOSS/TRAIL/TIME/SIGNAL counts.
- **Signal snapshot in TradeDrawer**: show indicator values at entry (from `signal_snapshot`)
  so a user can see *why* the trade fired.
- Keep existing: stats cards, equity curve, monthly grid, Monte Carlo, skipped breakdown,
  charge recompute, CSV export.

## 6. Indicator Preview Chart (`PLANNED`)

Optional: a small candlestick + indicator overlay using `/api/indicators/preview`, so users
visually confirm an indicator looks right before backtesting (builds trust in accuracy).

## 7. Type Definitions (frontend `types.ts`)

```ts
interface IndicatorSpec {
  name: string; type: "SMA"|"EMA"|"RSI"|"ATR"|"ADX"|"BBANDS"|"MACD"|"SUPERTREND"|"VWAP"|"STOCH";
  period: number; field: "close"|"open"|"high"|"low"|"hl2"|"hlc3"|"ohlc4";
  mult?: number; std?: number; fast?: number; slow?: number; signal?: number; d?: number;
}
type OperandKind = "PRICE"|"INDICATOR"|"CONST";
interface OperandSpec { kind: OperandKind; ref?: string; const?: number; offset?: number; }
type Operator = "GT"|"LT"|"GTE"|"LTE"|"EQ"|"CROSS_ABOVE"|"CROSS_BELOW";
interface ConditionSpec { lhs: OperandSpec; op: Operator; rhs: OperandSpec; }
interface ConditionGroupSpec { join: "AND"|"OR"; conditions: ConditionSpec[]; }
```

## 8. UX Principles

- **Show, don't assume**: every computed number (cost, MDD, Sharpe) is recomputable in the UI
  and matches the backend (parity-tested).
- **Explainable trades**: clicking a trade reveals legs, costs, and the entry signal snapshot.
- **Fail visibly**: API errors render inline (typed `_json<T>`), never a blank panel.
- **No magic**: indicator/condition config maps 1:1 to the request payload; what you build is
  what runs.

## 9. Accessibility & Theming

- Dark theme, sufficient contrast for numbers (green/red P&L, amber ITM).
- Keyboard-navigable dropdowns; focus states on inputs.
- Monospace for prices/strikes; tabular alignment in the trade log and chain.

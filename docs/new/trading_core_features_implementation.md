# Trading Software Core Features Implementation Specification

**Scope:** Market Dashboard, Strategy Builder, Backtesting & Analytics, and Risk Management  
**Excluded from this document:** Financial AI Agent / AI Copilot  
**Target market:** Indian index/options trading, mainly NIFTY and BANKNIFTY  
**Current stack observed in the project:** FastAPI backend, React + TypeScript frontend, DuckDB + Parquet data lake, Python backtest engine

---

## 1. Purpose

The purpose of this document is to define the implementation plan for the core trading software features before adding any AI agent layer.

The platform should help the user:

1. View live and historical market data.
2. Build option strategies using a no-code strategy builder.
3. Run realistic backtests with charges, slippage and risk controls.
4. Analyse performance with detailed metrics.
5. Prevent unsafe or over-risky strategy usage through risk management rules.

---

## 2. Existing Project Baseline

The uploaded project already contains many useful building blocks.

### 2.1 Backend

Current backend is built using FastAPI.

Existing useful routes:

| Current Route | Purpose | Status |
|---|---|---|
| `GET /api/status` | Data coverage and health | Existing |
| `GET /api/expiries/{underlying}` | Available expiries | Existing |
| `GET /api/options-chain/dates/{underlying}/{expiry}` | Dates where chain data exists | Existing |
| `GET /api/options-chain/data` | Option chain snapshot with greeks and summary | Existing |
| `POST /api/backtest` | Run backtest | Existing |
| `POST /api/backtest/grid` | Run parameter grid/sweep | Existing |
| `POST /api/strategy/payoff` | Payoff curve and greeks | Existing |
| `POST /api/strategies/save` | Save strategy | Existing |
| `GET /api/strategies/list` | List saved strategies | Existing |
| `DELETE /api/strategies/{strategy_id}` | Delete saved strategy | Existing |
| `GET /api/flow/live` | Live OI/flow summary | Existing |
| `GET /api/oi-analysis` | OI analysis | Existing |
| `GET /api/chart/candles` | Candle data for chart | Existing |
| `WebSocket /api/ws/live` | Upstox live index/ATM data | Existing |
| `WebSocket /api/live/stream` | Live option chain stream | Existing |

### 2.2 Frontend

Existing useful React components:

| Component | Purpose | Status |
|---|---|---|
| `Dashboard.tsx` | Data/dashboard summary | Existing |
| `StrategyBuilder.tsx` | Strategy builder | Existing |
| `SignalBuilder.tsx` | Indicator and condition builder | Existing |
| `EntryConditions.tsx` | Entry filters | Existing |
| `ExitConditions.tsx` | Exit filters | Existing |
| `ResultsPanel.tsx` | Backtest result analytics | Existing |
| `GridSweep.tsx` | Parameter sweep | Existing |
| `OptionsChain.tsx` | Option chain and payoff builder | Existing |
| `LiveTab.tsx` | Live index/ATM view | Existing |
| `FlowMatrix.tsx` | OI/flow analytics | Existing |
| `LWChart.tsx` | Lightweight chart component | Existing |
| `InstitutionalAnalytics.tsx` | Advanced analytics/live telemetry | Existing |

### 2.3 Data Layer

Existing useful data modules:

| Module | Purpose | Status |
|---|---|---|
| `src/data/storage.py` | Parquet lake and DuckDB read/write | Existing |
| `src/data/schema.py` | Canonical schemas | Existing |
| `src/data/upstox_*` scripts | Upstox OAuth/backfill | Existing |
| `src/data/angelone_client.py` | Angel One integration | Existing |
| `src/data/aliceblue_client.py` | Alice Blue integration | Existing |
| `src/data/kaggle_loader.py` | Free historical data loader | Existing |
| `src/backtest/engine.py` | Backtest engine | Existing |
| `src/backtest/costs.py` | Trading cost model | Existing |
| `src/backtest/metrics.py` | Metrics | Existing |
| `src/backtest/greeks.py` | Options greeks | Existing |
| `src/analysis/oi_analysis.py` | OI analysis | Existing |

---

## 3. Recommended Product Modules

The core product should be split into four modules.

```text
Trading Software
│
├── 1. Market Dashboard
├── 2. Strategy Builder
├── 3. Backtesting & Analytics
└── 4. Risk Management
```

---

# MODULE 1 — Market Dashboard

## 4. Objective

The Market Dashboard should give users a complete view of the current market condition before they build or run a strategy.

It should answer:

1. What is the current market direction?
2. Is the market trending, sideways or volatile?
3. What are the important option chain levels?
4. Where is OI buildup happening?
5. Is IV high or low?
6. Is this a good condition for option buying, option selling or no trade?

---

## 5. Market Dashboard Features

### 5.1 Live Index Cards

Display cards for:

- NIFTY 50
- BANKNIFTY
- FINNIFTY, optional later
- India VIX

Each card should show:

| Field | Description |
|---|---|
| LTP | Current last traded price |
| Change | Point change from previous close |
| Change % | Percentage movement |
| Open | Day open |
| High | Day high |
| Low | Day low |
| Previous close | Previous close |
| Trend label | Bullish, Bearish, Sideways |
| Last updated time | Data freshness |

### 5.2 Market Regime Detection

System should classify the current market into one of the below regimes:

| Regime | Logic Example |
|---|---|
| Trending Bullish | Price above VWAP, EMA fast > EMA slow, higher high structure |
| Trending Bearish | Price below VWAP, EMA fast < EMA slow, lower low structure |
| Sideways | Price inside narrow range, ADX low, VWAP flat |
| Volatile | ATR or VIX high, wide candles, large intraday range |
| Low Volatility | ATR low, IV low, price compression |

Recommended backend function:

```python
class MarketRegime(str, Enum):
    BULLISH_TREND = "BULLISH_TREND"
    BEARISH_TREND = "BEARISH_TREND"
    SIDEWAYS = "SIDEWAYS"
    VOLATILE = "VOLATILE"
    LOW_VOLATILITY = "LOW_VOLATILITY"
```

### 5.3 Live Candlestick Chart

Use the existing `LWChart.tsx` or TradingView Lightweight Charts.

Display:

- Candlesticks
- Volume
- VWAP
- EMA 9 / EMA 21
- Previous day high/low
- Current day high/low
- Important support and resistance
- Entry/exit markers when used from backtest

Recommended chart intervals:

- 1 minute
- 3 minutes
- 5 minutes
- 15 minutes
- 30 minutes
- 1 hour
- Daily

### 5.4 Option Chain Dashboard

The option chain should show:

| Field | CE Side | PE Side |
|---|---|---|
| LTP | Yes | Yes |
| Change | Yes | Yes |
| Volume | Yes | Yes |
| OI | Yes | Yes |
| OI Change | Yes | Yes |
| IV | Yes | Yes |
| Delta | Yes | Yes |
| Gamma | Yes | Yes |
| Theta | Yes | Yes |
| Vega | Yes | Yes |
| Bid / Ask | Yes | Yes |
| Spread | Yes | Yes |

Also show summary cards:

- Spot price
- ATM strike
- PCR
- Max Pain
- Total CE OI
- Total PE OI
- Highest CE OI strike
- Highest PE OI strike
- Highest CE OI change strike
- Highest PE OI change strike
- IV skew

### 5.5 OI Buildup Classification

For each strike and option type, classify:

| Price Change | OI Change | Classification |
|---|---|---|
| Up | Up | Long Buildup |
| Down | Up | Short Buildup |
| Up | Down | Short Covering |
| Down | Down | Long Unwinding |

Recommended backend output:

```json
{
  "strike": 23500,
  "option_type": "CE",
  "price_change": 12.5,
  "oi_change": 125000,
  "classification": "SHORT_BUILDUP",
  "bias": "BEARISH"
}
```

### 5.6 Support and Resistance Engine

Auto-detect levels from:

- Previous day high
- Previous day low
- Current day high
- Current day low
- Opening range high/low
- VWAP
- Highest CE OI strike
- Highest PE OI strike
- Highest OI change strikes
- Round number levels
- Pivot points

Recommended output:

```json
{
  "underlying": "NIFTY",
  "levels": [
    {
      "level": 23500,
      "type": "RESISTANCE",
      "source": "HIGHEST_CE_OI",
      "strength": 8
    },
    {
      "level": 23300,
      "type": "SUPPORT",
      "source": "HIGHEST_PE_OI",
      "strength": 7
    }
  ]
}
```

### 5.7 Market Alerts

Add configurable alerts:

- Spot crosses VWAP
- Spot breaks previous day high/low
- PCR crosses threshold
- IV crosses threshold
- CE/PE OI spike
- ATM straddle premium expands/contracts
- Max Pain shift
- Sudden volume spike
- Spread too wide

---

## 6. Market Dashboard Backend API Design

### 6.1 Get Market Snapshot

```http
GET /api/market/snapshot?underlying=NIFTY
```

Response:

```json
{
  "underlying": "NIFTY",
  "timestamp": "2026-06-17T10:10:00+05:30",
  "source": "upstox",
  "spot": {
    "ltp": 23520.5,
    "open": 23450.0,
    "high": 23580.0,
    "low": 23390.0,
    "prev_close": 23410.0,
    "change": 110.5,
    "change_pct": 0.47
  },
  "regime": "BULLISH_TREND",
  "freshness_seconds": 1
}
```

### 6.2 Get Candles

```http
GET /api/market/candles?underlying=NIFTY&interval=5m&from=2026-06-01&to=2026-06-17&source=lake
```

Response:

```json
{
  "underlying": "NIFTY",
  "interval": "5m",
  "candles": [
    {
      "ts": "2026-06-17T09:15:00+05:30",
      "open": 23450,
      "high": 23480,
      "low": 23420,
      "close": 23470,
      "volume": 100000
    }
  ]
}
```

### 6.3 Get Option Chain

You can continue using the existing route:

```http
GET /api/options-chain/data?underlying=NIFTY&expiry=2026-06-30&ts=latest
```

Recommended future route:

```http
GET /api/options/chain?underlying=NIFTY&expiry=2026-06-30&source=live
```

### 6.4 Get OI Buildup

```http
GET /api/options/oi-buildup?underlying=NIFTY&expiry=2026-06-30
```

Response:

```json
{
  "underlying": "NIFTY",
  "expiry": "2026-06-30",
  "rows": [
    {
      "strike": 23500,
      "option_type": "CE",
      "ltp": 120.5,
      "price_change": -8.0,
      "oi": 1234500,
      "oi_change": 220000,
      "classification": "SHORT_BUILDUP",
      "bias": "BEARISH"
    }
  ]
}
```

### 6.5 Get Support / Resistance Levels

```http
GET /api/market/levels?underlying=NIFTY&expiry=2026-06-30
```

### 6.6 Live Market WebSocket

Current route can be retained:

```text
WebSocket /api/ws/live
```

Recommended unified route:

```text
WebSocket /api/market/stream
```

Client subscribe message:

```json
{
  "action": "subscribe",
  "underlyings": ["NIFTY", "BANKNIFTY"],
  "include_option_chain": true,
  "include_oi": true
}
```

---

## 7. Market Dashboard Frontend Implementation

### 7.1 New/Updated Components

| Component | Action |
|---|---|
| `Dashboard.tsx` | Upgrade with market snapshot cards |
| `LiveTab.tsx` | Keep for live WebSocket index data |
| `OptionsChain.tsx` | Keep and enhance with OI classification |
| `FlowMatrix.tsx` | Keep and connect with OI buildup summary |
| `MarketRegimeCard.tsx` | New |
| `SupportResistancePanel.tsx` | New |
| `MarketAlertsPanel.tsx` | New |

### 7.2 Dashboard Layout

```text
Market Dashboard
│
├── Top Index Cards
│   ├── NIFTY
│   ├── BANKNIFTY
│   └── INDIA VIX
│
├── Chart Area
│   ├── Candlestick chart
│   ├── Indicators
│   └── Support/resistance lines
│
├── Option Chain Summary
│   ├── PCR
│   ├── Max Pain
│   ├── IV
│   └── Highest OI levels
│
├── OI Buildup Matrix
│
└── Alerts / Warnings
```

---

# MODULE 2 — Strategy Builder

## 8. Objective

The Strategy Builder should allow users to create rule-based option strategies without coding.

It should support:

1. Multi-leg option strategies.
2. Indicator-based entries and exits.
3. Time-based entries and exits.
4. Risk-based exits.
5. Strategy templates.
6. Strategy validation before backtest.
7. Strategy save, edit, clone and delete.

---

## 9. Strategy Builder Features

### 9.1 Strategy Templates

Include ready-made templates:

| Template | Strategy Type |
|---|---|
| ATM Short Straddle | Option selling |
| OTM Short Strangle | Option selling |
| Iron Condor | Hedged option selling |
| Bull Call Spread | Directional bullish |
| Bear Put Spread | Directional bearish |
| Long Straddle | Volatility buying |
| Long Strangle | Volatility buying |
| Covered Call, optional | Equity + option |
| Protective Put, optional | Equity + option |

Each template should define:

- Legs
- Entry time
- Exit time
- Strike selection
- Stop loss
- Target
- Risk level
- Minimum capital estimate
- Suitable market regime

Example:

```json
{
  "template_id": "iron_condor_nifty_weekly",
  "name": "NIFTY Weekly Iron Condor",
  "risk_level": "MEDIUM",
  "suitable_regime": ["SIDEWAYS", "LOW_VOLATILITY"],
  "legs": [
    { "action": "SELL", "opt_type": "CE", "selection": "OTM", "value": 300, "lots": 1 },
    { "action": "SELL", "opt_type": "PE", "selection": "OTM", "value": 300, "lots": 1 },
    { "action": "BUY", "opt_type": "CE", "selection": "OTM", "value": 600, "lots": 1 },
    { "action": "BUY", "opt_type": "PE", "selection": "OTM", "value": 600, "lots": 1 }
  ],
  "entry_time": "09:30",
  "exit_time": "15:15",
  "overall_sl_pct": 50,
  "overall_target_pct": 35
}
```

### 9.2 Multi-Leg Option Builder

Each strategy leg should support:

| Field | Values |
|---|---|
| Action | BUY / SELL |
| Option type | CE / PE |
| Strike selection | ATM, ITM, OTM, Premium, Delta, Manual Strike |
| Strike offset | Example: ATM + 100 |
| Premium target | Example: option near ₹100 premium |
| Delta target | Example: 0.30 delta |
| Expiry | Current weekly, next weekly, monthly, custom |
| Lots | Number of lots |
| Leg SL | Percentage, points, premium amount |
| Leg target | Percentage, points, premium amount |
| Leg trailing SL | Optional |

### 9.3 Entry Conditions

Support condition types:

| Condition Type | Example |
|---|---|
| Time based | Enter at 09:25 |
| Price based | Spot > previous day high |
| Indicator based | EMA 9 crosses above EMA 21 |
| Volatility based | IV Rank < 60 |
| OI based | PCR > 1.1 |
| Market regime | Only trade in sideways market |
| Weekday based | Trade Monday to Thursday only |
| Expiry based | Trade only on 0 DTE / 1 DTE |

### 9.4 Exit Conditions

Support:

| Exit Type | Example |
|---|---|
| Time exit | Exit at 15:15 |
| Overall stop loss | Exit when strategy loss reaches 50% |
| Overall target | Exit when strategy profit reaches 40% |
| Leg stop loss | Exit one leg when premium doubles |
| Trailing SL | Trail after profit reaches threshold |
| Indicator exit | Exit when EMA cross reverses |
| Market regime exit | Exit if sideways becomes trending |
| VIX spike exit | Exit if India VIX jumps sharply |

### 9.5 Condition Builder

The frontend already has `SignalBuilder.tsx`. Extend it to support nested groups.

Example:

```json
{
  "logic": "AND",
  "conditions": [
    {
      "lhs": { "kind": "indicator", "ref": "ema9" },
      "op": "cross_above",
      "rhs": { "kind": "indicator", "ref": "ema21" }
    },
    {
      "lhs": { "kind": "indicator", "ref": "rsi14" },
      "op": ">",
      "rhs": { "kind": "const", "value": 55 }
    }
  ]
}
```

### 9.6 Strategy Validation

Before running a backtest, validate:

| Validation | Error Example |
|---|---|
| At least one leg required | `Strategy must have at least one leg` |
| BUY/SELL must be valid | `Invalid leg action` |
| Expiry must exist | `No expiry found for selected date` |
| Indicator references must exist | `Unknown indicator: ema99` |
| SL and target must be non-negative | `Stop loss cannot be negative` |
| Exit time must be after entry time | `Exit time must be greater than entry time` |
| Required data must exist | `No 1-minute option data available for date range` |

---

## 10. Strategy Builder Backend API Design

### 10.1 List Strategy Templates

```http
GET /api/strategies/templates
```

Response:

```json
{
  "templates": [
    {
      "id": "short_straddle",
      "name": "ATM Short Straddle",
      "description": "Sell ATM CE and PE with fixed SL and time exit",
      "risk_level": "HIGH",
      "suitable_regime": ["SIDEWAYS"]
    }
  ]
}
```

### 10.2 Validate Strategy

```http
POST /api/strategies/validate
```

Request:

```json
{
  "name": "My NIFTY Strategy",
  "underlying": "NIFTY",
  "legs": [],
  "entry_tree": {},
  "exit_tree": {},
  "risk_rules": {}
}
```

Response:

```json
{
  "valid": false,
  "errors": [
    {
      "field": "legs",
      "message": "At least one leg is required"
    }
  ],
  "warnings": [
    {
      "field": "risk",
      "message": "No overall stop loss configured"
    }
  ]
}
```

### 10.3 Save Strategy

Current route exists:

```http
POST /api/strategies/save
```

Recommended future route:

```http
POST /api/strategies
```

### 10.4 List Saved Strategies

Current route exists:

```http
GET /api/strategies/list
```

Recommended future route:

```http
GET /api/strategies
```

### 10.5 Update Strategy

```http
PUT /api/strategies/{strategy_id}
```

### 10.6 Clone Strategy

```http
POST /api/strategies/{strategy_id}/clone
```

### 10.7 Delete Strategy

Current route exists:

```http
DELETE /api/strategies/{strategy_id}
```

---

## 11. Strategy Builder Frontend Implementation

### 11.1 Components

| Component | Action |
|---|---|
| `StrategyBuilder.tsx` | Upgrade existing builder |
| `SignalBuilder.tsx` | Extend to nested rules and validation |
| `EntryConditions.tsx` | Keep and enhance |
| `ExitConditions.tsx` | Keep and enhance |
| `StrategyTemplates.tsx` | New or enhance existing template list |
| `LegBuilder.tsx` | New reusable leg editor |
| `StrategyValidationPanel.tsx` | New |
| `SavedStrategiesPanel.tsx` | New or enhance existing saved strategy UI |

### 11.2 User Flow

```text
User opens Strategy Builder
        ↓
Selects underlying and date range
        ↓
Chooses template or starts blank
        ↓
Adds option legs
        ↓
Adds entry/exit conditions
        ↓
Adds risk rules
        ↓
Clicks Validate
        ↓
If valid, clicks Run Backtest
        ↓
Views result in Analytics module
        ↓
Saves or clones strategy
```

---

# MODULE 3 — Backtesting & Analytics

## 12. Objective

The backtesting module should simulate strategies realistically and show whether the strategy is stable, profitable and safe.

It should not only show final P&L. It should show:

1. Profitability
2. Risk
3. Consistency
4. Drawdown
5. Trade quality
6. Strategy weakness
7. Market condition dependency

---

## 13. Backtesting Engine Requirements

### 13.1 Data Requirements

Backtesting should use:

| Data Type | Required For |
|---|---|
| Spot 1-minute candles | Indicators and market regime |
| Option 1-minute candles | Entry/exit price simulation |
| Option chain snapshots | Strike selection, OI, IV, greeks |
| Bhavcopy/EOD data | Validation and fallback |
| India VIX | Volatility filter |
| Contract master | Expiry, strike, token mapping |
| Charges table | Brokerage and statutory charges |

### 13.2 Execution Rules

Backtest should follow realistic execution rules:

1. Conditions should be checked only on closed candles.
2. Entry should use the next available tradable price after signal.
3. Stop loss should support intrabar OHLC checking.
4. Exit should support time-based, SL, target and signal-based exits.
5. Missing candle handling should be explicit.
6. Slippage should be configurable.
7. Brokerage and statutory charges should be deducted.
8. Every trade should have an exit reason.

### 13.3 Fill Logic

Recommended order fill priority inside a candle:

1. If stop loss and target both hit in the same candle, use conservative assumption.
2. For option selling, assume stop loss hit first when both SL and target are inside the candle.
3. For option buying, assume stop loss hit first unless user selects optimistic mode.
4. Store fill assumption in trade output.

Example:

```json
{
  "fill_model": "CONSERVATIVE",
  "same_candle_sl_target_rule": "SL_FIRST"
}
```

### 13.4 Strike Selection

Support:

| Selection | Example |
|---|---|
| ATM | Nearest strike to spot |
| ITM/OTM by points | ATM + 100 |
| ITM/OTM by steps | ATM + 2 strikes |
| Premium based | Nearest option premium to ₹100 |
| Delta based | Nearest delta 0.30 |
| Manual | User selects strike |

### 13.5 Backtest Accuracy Rules

Must avoid look-ahead bias:

- Do not use future candle values to enter current candle.
- Do not use end-of-day data for intraday decisions.
- Do not use complete-day high/low to decide early entries.
- Indicators should be calculated using only data available until that timestamp.
- Weekly/monthly expiry mapping should be based on the selected trade date.

---

## 14. Backtesting API Design

### 14.1 Run Backtest

Current route exists:

```http
POST /api/backtest
```

Recommended future route:

```http
POST /api/backtests
```

Request:

```json
{
  "name": "NIFTY EMA Short Straddle",
  "underlying": "NIFTY",
  "start": "2025-01-01",
  "end": "2025-12-31",
  "expiry_offset": 0,
  "entry_time": "09:25",
  "exit_time": "15:15",
  "candle_interval": 5,
  "candle_source": "SPOT",
  "legs": [
    {
      "action": "SELL",
      "opt_type": "CE",
      "selection": "ATM",
      "value": 0,
      "lots": 1,
      "sl_pct": 100,
      "tp_pct": 50
    },
    {
      "action": "SELL",
      "opt_type": "PE",
      "selection": "ATM",
      "value": 0,
      "lots": 1,
      "sl_pct": 100,
      "tp_pct": 50
    }
  ],
  "indicators": [
    {
      "name": "ema9",
      "type": "EMA",
      "period": 9,
      "field": "close"
    },
    {
      "name": "ema21",
      "type": "EMA",
      "period": 21,
      "field": "close"
    }
  ],
  "entry_tree": {
    "logic": "AND",
    "conditions": [
      {
        "lhs": { "kind": "indicator", "ref": "ema9" },
        "op": "cross_above",
        "rhs": { "kind": "indicator", "ref": "ema21" }
      }
    ]
  },
  "exit_conditions": {
    "overall_sl_pct": 50,
    "overall_target_pct": 30,
    "force_exit_time": "15:15",
    "trailing_sl_pct": 0
  },
  "costs": {
    "brokerage_flat": 20,
    "brokerage_mode": "FLAT",
    "slippage_pct": 0.03,
    "use_taxes": true
  }
}
```

### 14.2 Backtest Response

```json
{
  "run_id": "bt_20260617_001",
  "status": "COMPLETED",
  "stats": {
    "trades": 142,
    "win_rate": 0.62,
    "net_pnl": 182340.5,
    "gross_pnl": 205000.0,
    "total_cost": 22659.5,
    "expectancy": 1284.1,
    "avg_win": 3120.0,
    "avg_loss": -2010.5,
    "max_drawdown": -21450.0,
    "profit_factor": 1.9,
    "sharpe": 1.82,
    "sortino": 2.1,
    "calmar": 1.4,
    "max_win_streak": 9,
    "max_loss_streak": 4
  },
  "trades": [],
  "equity_curve": [],
  "skipped": []
}
```

### 14.3 Parameter Sweep

Current route exists:

```http
POST /api/backtest/grid
```

Recommended future route:

```http
POST /api/backtests/sweep
```

Request:

```json
{
  "base_strategy": {},
  "sweep": {
    "overall_sl_pct": [25, 50, 75, 100],
    "overall_target_pct": [20, 30, 40, 50],
    "entry_time": ["09:20", "09:30", "09:45"]
  },
  "ranking_metric": "profit_factor"
}
```

Response:

```json
{
  "results": [
    {
      "case_id": "case_001",
      "params": {
        "overall_sl_pct": 50,
        "overall_target_pct": 30,
        "entry_time": "09:30"
      },
      "net_pnl": 120000,
      "max_drawdown": -18000,
      "profit_factor": 1.8,
      "win_rate": 0.61,
      "score": 82
    }
  ]
}
```

### 14.4 Get Backtest Analytics

```http
GET /api/backtests/{run_id}/analytics
```

Response:

```json
{
  "monthly_pnl": [],
  "weekday_pnl": [],
  "dte_pnl": [],
  "exit_reason_distribution": [],
  "drawdown_periods": [],
  "regime_performance": [],
  "monte_carlo": {}
}
```

### 14.5 Export Backtest Result

```http
GET /api/backtests/{run_id}/export?format=csv
GET /api/backtests/{run_id}/export?format=xlsx
GET /api/backtests/{run_id}/export?format=json
```

---

## 15. Analytics Features

### 15.1 Core Metrics

Show these metrics in the result panel:

| Metric | Description |
|---|---|
| Net P&L | Final profit after charges |
| Gross P&L | Profit before charges |
| Total charges | Brokerage, STT, exchange charges, GST, SEBI fee, stamp duty |
| Number of trades | Total completed trades |
| Win rate | Winning trades / total trades |
| Average win | Average profit on winning trades |
| Average loss | Average loss on losing trades |
| Profit factor | Gross profit / gross loss |
| Expectancy | Average expected profit/loss per trade |
| Max drawdown | Worst equity fall from peak |
| Max drawdown duration | Time spent under previous peak |
| Sharpe ratio | Risk-adjusted return |
| Sortino ratio | Downside-risk-adjusted return |
| Calmar ratio | Return vs max drawdown |
| Recovery factor | Net profit / max drawdown |

### 15.2 Charts

Add charts:

- Equity curve
- Drawdown curve
- Monthly P&L heatmap
- Weekday performance bar chart
- DTE performance chart
- Exit reason pie/bar chart
- Trade distribution histogram
- P&L by market regime
- Cumulative charges chart

### 15.3 Trade-Level Details

For every trade show:

| Field | Purpose |
|---|---|
| Trade date | Date of trade |
| Entry timestamp | Entry time |
| Exit timestamp | Exit time |
| Entry spot | Spot at entry |
| Exit spot | Spot at exit |
| Legs | All leg details |
| Gross P&L | Before charges |
| Charges | Cost breakdown |
| Net P&L | After charges |
| Exit reason | SL, target, time exit, signal exit |
| Entry signal snapshot | Indicator values at entry |
| Market regime | Regime during entry |
| Notes | Any skipped/missing data warning |

### 15.4 Monte Carlo Simulation

Add Monte Carlo to estimate strategy stability.

Output:

```json
{
  "iterations": 5000,
  "confidence": 0.95,
  "worst_case_drawdown_95": -65000,
  "median_pnl": 145000,
  "loss_probability": 0.18
}
```

### 15.5 Overfitting Warning

Show warning when:

- Too many parameters are used.
- Sample size is too small.
- Profit comes from very few large trades.
- Strategy performs only in one month/one expiry.
- Small slippage increase destroys profit.
- Walk-forward performance is much worse than in-sample performance.

Example warning:

```json
{
  "severity": "HIGH",
  "code": "OVERFITTING_RISK",
  "message": "Strategy has 14 conditions but only 35 trades. Result may be overfitted."
}
```

---

# MODULE 4 — Risk Management

## 16. Objective

Risk Management should protect users from unsafe strategies, unrealistic backtests and excessive trading losses.

The platform should provide:

1. Strategy-level risk checks.
2. Backtest-level risk analytics.
3. Live/paper-trading risk controls.
4. Broker/order safety checks, if live execution is added later.
5. Compliance-ready audit trails.

---

## 17. Risk Management Features

### 17.1 Strategy Risk Score

Calculate a score from 1 to 10.

| Score | Meaning |
|---|---|
| 1–3 | Low risk |
| 4–6 | Medium risk |
| 7–8 | High risk |
| 9–10 | Very high risk |

Risk score inputs:

- Max drawdown
- Win rate
- Profit factor
- Loss streak
- Capital required
- Naked option selling
- Expiry-day exposure
- Slippage sensitivity
- Trade frequency
- Overnight exposure
- Margin utilisation

### 17.2 Pre-Backtest Risk Validation

Before running a backtest, validate:

| Check | Rule |
|---|---|
| Naked sell check | Warn if SELL option has no hedge |
| Stop loss check | Warn if no SL is configured |
| Capital check | Estimate minimum capital |
| Expiry risk check | Warn for 0 DTE naked option selling |
| Slippage check | Force slippage assumption for illiquid options |
| Data availability | Warn if data coverage is incomplete |

### 17.3 Post-Backtest Risk Review

After backtest, show:

| Risk Metric | Description |
|---|---|
| Max drawdown | Worst loss from peak |
| Drawdown duration | Number of days under water |
| Worst day loss | Biggest single-day loss |
| Worst trade loss | Biggest trade loss |
| Max loss streak | Consecutive losses |
| Tail risk | Worst 5% trade outcomes |
| Slippage sensitivity | Impact of increased slippage |
| Charges sensitivity | Impact of realistic charges |
| Regime risk | Which market condition causes loss |

### 17.4 Live/Paper Trading Risk Controls

When paper/live trading is added, include:

| Control | Purpose |
|---|---|
| Daily max loss | Stop all trades after daily loss limit |
| Strategy max loss | Stop individual strategy |
| Max open positions | Prevent over-exposure |
| Max lots per trade | Prevent large accidental orders |
| Max orders per minute | Prevent runaway algo |
| Price band validation | Avoid wrong-price orders |
| Duplicate order check | Avoid repeated order placement |
| Kill switch | Stop all strategies immediately |
| Market close square-off | Force exit before configured time |
| Broker disconnect handling | Stop trading if broker feed/order API disconnects |

### 17.5 Audit Trail

Store every important action:

- User login
- Strategy create/update/delete
- Backtest run
- Risk warning shown
- Risk warning accepted by user
- Paper trade signal
- Live order request, if added later
- Broker order response, if added later
- Manual override
- Kill switch activation

Recommended table:

```sql
CREATE TABLE audit_events (
    event_id TEXT PRIMARY KEY,
    user_id TEXT,
    event_type TEXT,
    entity_type TEXT,
    entity_id TEXT,
    payload_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 18. Risk Management API Design

### 18.1 Risk Precheck

```http
POST /api/risk/precheck
```

Request:

```json
{
  "strategy": {},
  "capital": 200000,
  "mode": "BACKTEST"
}
```

Response:

```json
{
  "risk_score": 7,
  "risk_level": "HIGH",
  "allowed": true,
  "warnings": [
    {
      "code": "NAKED_OPTION_SELL",
      "severity": "HIGH",
      "message": "This strategy sells options without hedge legs."
    },
    {
      "code": "NO_DAILY_MAX_LOSS",
      "severity": "MEDIUM",
      "message": "Daily max loss is not configured."
    }
  ],
  "required_confirmations": [
    "I understand this strategy has naked option selling risk."
  ]
}
```

### 18.2 Margin Estimate

```http
POST /api/risk/margin-estimate
```

Request:

```json
{
  "underlying": "NIFTY",
  "expiry": "2026-06-30",
  "legs": []
}
```

Response:

```json
{
  "estimated_margin": 145000,
  "hedge_benefit": 52000,
  "margin_source": "internal_estimate",
  "note": "Use broker margin API before live order placement."
}
```

### 18.3 Slippage Sensitivity

```http
POST /api/risk/slippage-sensitivity
```

Request:

```json
{
  "backtest_request": {},
  "slippage_values": [0, 0.01, 0.03, 0.05, 0.10]
}
```

Response:

```json
{
  "rows": [
    {
      "slippage_pct": 0.03,
      "net_pnl": 120000,
      "max_drawdown": -30000,
      "profit_factor": 1.6
    }
  ]
}
```

### 18.4 Kill Switch

For paper/live trading phase only:

```http
POST /api/risk/kill-switch
```

Request:

```json
{
  "scope": "ALL",
  "reason": "Manual emergency stop"
}
```

Response:

```json
{
  "status": "STOPPED",
  "stopped_strategies": 3,
  "timestamp": "2026-06-17T11:30:00+05:30"
}
```

---

## 19. Data Connection APIs and Links

This section lists useful official API/data links for implementation. For production usage, prefer official broker APIs, exchange-approved market-data vendors, or licensed exchange data products. Avoid depending on unofficial scraping for production trading systems.

### 19.1 Current Project Data Sources

| Source | Current Project Usage | Link |
|---|---|---|
| Upstox | Live LTP, option chain, OAuth, historical candles/backfill | https://upstox.com/developer/api-documentation/open-api/ |
| Upstox Market Feed V3 | Real-time WebSocket market feed | https://upstox.com/developer/api-documentation/v3/get-market-data-feed/ |
| Upstox Historical Candle V3 | Historical OHLC candles | https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/ |
| Angel One SmartAPI | Live market data, orders, portfolio, WebSocket | https://smartapi.angelbroking.com/docs |
| Alice Blue pya3 | Existing Alice Blue Python wrapper in project | https://github.com/jerokpradeep/pya3 |
| Alice Blue API Docs | WebSocket, contract master, historical data, option chain | https://ant.aliceblueonline.com/productdocumentation/Reference%20Libraries/ |
| NSE Historical Reports | Official exchange reports/bhavcopy/history | https://www.nseindia.com/all-reports |
| NSE Daily Market Reports | Capital market daily/monthly archives | https://www.nseindia.com/resources/historical-reports-capital-market-daily-monthly-archives |
| BSE Bhavcopy | Official BSE historical bhavcopy page | https://www.bseindia.com/markets/MarketInfo/BhavCopy |
| Kaggle | Historical research/backfill datasets, not production-grade official market feed | https://www.kaggle.com/ |

### 19.2 Additional Broker APIs to Consider

| Broker/API | Useful For | Link |
|---|---|---|
| Zerodha Kite Connect | Orders, portfolio, live market data WebSocket | https://kite.trade/docs/connect/v3/ |
| Zerodha API Product Page | Kite Connect overview | https://zerodha.com/products/api/ |
| DhanHQ v2 | Orders, portfolio, live data, option chain | https://dhanhq.co/docs/v2/ |
| DhanHQ Option Chain | Option chain with OI, greeks, volume, bid/ask | https://dhanhq.co/docs/v2/option-chain/ |
| FYERS API | Trading APIs, data APIs, OAuth | https://myapi.fyers.in/ |
| FYERS Data WebSocket Guide | Real-time data WebSocket | https://support.fyers.in/portal/en/kb/articles/how-can-i-use-the-data-websocket-in-api-v3-to-access-real-time-data |
| Shoonya API | Trading, market data, option chain, WebSocket | https://shoonya.com/api-documentation |
| Shoonya Python SDK | REST + WebSocket Python wrapper | https://github.com/Shoonya-Dev/ShoonyaApi-py |
| Kotak Neo Trade API | Orders, portfolio, live quotes | https://www.kotakneo.com/platform/kotak-neo-trade-api/ |
| Kotak Neo Python SDK | Official Python SDK | https://github.com/Kotak-Neo/Kotak-neo-api-v2 |

### 19.3 Dedicated Market Data Vendors

| Vendor | Useful For | Link |
|---|---|---|
| NSE Paid Real-Time Data | Licensed real-time exchange data | https://www.nseindia.com/static/market-data/real-time-data-subscription |
| NSE Paid EOD/Historical Data | Licensed historical exchange data | https://www.nseindia.com/static/market-data/eod-historical-data-subscription |
| TrueData | Real-time NSE/BSE/MCX market data APIs, historical tick data, option analytics | https://www.truedata.in/ |
| TrueData Python Package | Official Python package for TrueData market data APIs | https://pypi.org/project/truedata-ws/ |
| Global Datafeeds | NSE/BSE/MCX data vendor | https://globaldatafeeds.in/global-datafeeds-nsebse-mcx-authorized-data-vendor/ |

### 19.4 Charting Libraries

| Library | Use | Link |
|---|---|---|
| TradingView Lightweight Charts | Lightweight financial charting | https://tradingview.github.io/lightweight-charts/ |
| TradingView Advanced Charts | Advanced charting with your own datafeed | https://www.tradingview.com/charting-library-docs/ |
| Apache ECharts | Heatmaps, analytics charts, candlestick charts | https://echarts.apache.org/ |

### 19.5 Regulatory / Compliance Reference

| Source | Use | Link |
|---|---|---|
| SEBI Algo Trading Circular, Feb 04 2025 | Retail algo safety, broker controls, algo order tagging and audit trail | https://www.sebi.gov.in/legal/circulars/feb-2025/safer-participation-of-retail-investors-in-algorithmic-trading_91614.html |
| NSE Data Policy | Market data usage and sharing policy | https://www.nseindia.com/static/market-data/nse-data-policy |
| NSE Terms of Use | Website/mobile usage terms | https://www.nseindia.com/static/nse-terms-of-use |

---

## 20. Data Provider Adapter Design

Implement a common provider interface so that you can switch between Upstox, Angel One, Dhan, Zerodha, Alice Blue, FYERS, Shoonya or a paid data vendor.

### 20.1 Interface

```python
from abc import ABC, abstractmethod

class MarketDataProvider(ABC):
    name: str

    @abstractmethod
    def get_ltp(self, instruments: list[str]) -> dict:
        pass

    @abstractmethod
    def get_candles(self, instrument: str, interval: str, start: str, end: str) -> list[dict]:
        pass

    @abstractmethod
    def get_option_chain(self, underlying: str, expiry: str) -> dict:
        pass

    @abstractmethod
    def get_expiries(self, underlying: str) -> list[str]:
        pass

    @abstractmethod
    def get_contract_master(self) -> list[dict]:
        pass
```

### 20.2 Recommended Folder Structure

```text
src/data/providers/
│
├── base.py
├── upstox_provider.py
├── angelone_provider.py
├── aliceblue_provider.py
├── zerodha_provider.py
├── dhan_provider.py
├── fyers_provider.py
├── shoonya_provider.py
├── truedata_provider.py
└── provider_factory.py
```

### 20.3 Provider Factory

```python
def get_provider(name: str) -> MarketDataProvider:
    if name == "upstox":
        return UpstoxProvider()
    if name == "angelone":
        return AngelOneProvider()
    if name == "aliceblue":
        return AliceBlueProvider()
    if name == "dhan":
        return DhanProvider()
    raise ValueError(f"Unsupported provider: {name}")
```

### 20.4 Environment Variables

Extend `.env.example`:

```env
# Active provider
MARKET_DATA_PROVIDER=upstox
ORDER_PROVIDER=paper

# Zerodha
ZERODHA_API_KEY=
ZERODHA_API_SECRET=
ZERODHA_ACCESS_TOKEN=

# Dhan
DHAN_CLIENT_ID=
DHAN_ACCESS_TOKEN=

# FYERS
FYERS_CLIENT_ID=
FYERS_SECRET_KEY=
FYERS_REDIRECT_URI=
FYERS_ACCESS_TOKEN=

# Shoonya
SHOONYA_USER_ID=
SHOONYA_PASSWORD=
SHOONYA_API_KEY=
SHOONYA_VENDOR_CODE=
SHOONYA_IMEI=
SHOONYA_TOTP_SECRET=

# TrueData
TRUEDATA_USERNAME=
TRUEDATA_PASSWORD=
TRUEDATA_PORT=
```

---

## 21. Database / Storage Design

Use DuckDB + Parquet for large historical data and SQLite/Postgres for app metadata.

### 21.1 Market Data Lake

```text
data/lake/
│
├── spot/
│   └── underlying=NIFTY/
│       └── year=2026/month=06/part-*.parquet
│
├── options/
│   └── underlying=NIFTY/expiry=2026-06-30/
│       └── year=2026/month=06/part-*.parquet
│
├── option_chain/
│   └── underlying=NIFTY/expiry=2026-06-30/
│       └── date=2026-06-17/part-*.parquet
│
└── vix/
    └── year=2026/month=06/part-*.parquet
```

### 21.2 App Metadata Tables

```sql
CREATE TABLE strategies (
    strategy_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    strategy_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE backtest_runs (
    run_id TEXT PRIMARY KEY,
    strategy_id TEXT,
    request_json TEXT NOT NULL,
    stats_json TEXT,
    status TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE risk_reviews (
    review_id TEXT PRIMARY KEY,
    entity_type TEXT,
    entity_id TEXT,
    risk_score INTEGER,
    risk_level TEXT,
    warnings_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 22. Implementation Roadmap

### Phase 1 — Market Dashboard Completion

| Task | Backend | Frontend |
|---|---|---|
| Unified market snapshot API | Add `/api/market/snapshot` | Upgrade dashboard cards |
| Candle API standardisation | Add `/api/market/candles` wrapper | Improve `LWChart.tsx` |
| OI buildup API | Add `/api/options/oi-buildup` | Add OI buildup matrix |
| Support/resistance API | Add `/api/market/levels` | Add levels panel |
| Alert rules | Add alert engine | Add alert panel |

### Phase 2 — Strategy Builder Upgrade

| Task | Backend | Frontend |
|---|---|---|
| Template API | Add `/api/strategies/templates` | Add template selector |
| Validation API | Add `/api/strategies/validate` | Add validation panel |
| Strategy CRUD | Add REST-style CRUD | Upgrade saved strategies UI |
| Nested conditions | Extend condition parser | Upgrade `SignalBuilder.tsx` |
| Leg builder | Validate strike selection | Add reusable `LegBuilder.tsx` |

### Phase 3 — Backtesting & Analytics Upgrade

| Task | Backend | Frontend |
|---|---|---|
| Backtest persistence | Save run in DB | Add run history |
| Analytics endpoint | Add `/api/backtests/{id}/analytics` | Upgrade `ResultsPanel.tsx` |
| Export endpoint | Add CSV/XLSX export | Add export button |
| Slippage sensitivity | Add batch runner | Add sensitivity chart |
| Overfitting checks | Add analytics warnings | Display warnings |

### Phase 4 — Risk Management Layer

| Task | Backend | Frontend |
|---|---|---|
| Risk precheck | Add `/api/risk/precheck` | Risk warning panel |
| Margin estimate | Add `/api/risk/margin-estimate` | Capital requirement card |
| Risk score | Add scoring function | Risk score badge |
| Audit trail | Add audit table/service | Show action history later |
| Kill switch | Add for paper/live phase | Add emergency control later |

---

## 23. Testing Plan

### 23.1 Backend Unit Tests

Test areas:

- Data provider adapter response mapping
- Candle resampling
- Indicator calculation
- Condition engine
- Strike selection
- Backtest execution
- Cost model
- Risk score
- Strategy validation

### 23.2 Frontend Tests

Test areas:

- Strategy form validation
- Leg add/remove/edit
- Template loading
- Condition builder output JSON
- Results panel rendering
- Dashboard WebSocket reconnect handling
- Empty/error/loading states

### 23.3 Integration Tests

Test flows:

1. Load market dashboard.
2. Fetch live option chain.
3. Create strategy from template.
4. Validate strategy.
5. Run backtest.
6. View analytics.
7. Save strategy.
8. Reopen saved strategy.
9. Run parameter sweep.
10. Export result.

### 23.4 Accuracy Tests

Required checks:

- Indicators should match TradingView or known reference output.
- Cost model should match broker contract note within acceptable tolerance.
- Same backtest should produce same result every time.
- Backtest should not use future candle data.
- Missing data should be reported clearly.

---

## 24. Definition of Done

The core trading software implementation can be considered complete when:

1. User can view live NIFTY/BANKNIFTY dashboard.
2. User can view option chain with OI, PCR, Max Pain and greeks.
3. User can identify OI buildup and support/resistance levels.
4. User can build multi-leg option strategies without coding.
5. User can use templates and modify them.
6. User can validate strategy before running.
7. User can run realistic backtests with charges and slippage.
8. User can view equity curve, drawdown, monthly P&L, trade list and key metrics.
9. User can run parameter sweeps.
10. User can see risk score and warnings.
11. User can save, clone and delete strategies.
12. All API failures show user-friendly errors.
13. All important actions are logged.
14. External API credentials are stored only in environment variables.
15. The system does not expose secrets in frontend or logs.

---

## 25. Recommended Implementation Priority

Build in this order:

1. Complete and stabilise data provider adapters.
2. Complete market dashboard and option chain accuracy.
3. Complete no-code strategy builder validation.
4. Improve backtest accuracy and persistence.
5. Add analytics depth.
6. Add risk score and precheck.
7. Add export and reporting.
8. Add paper trading later.
9. Add live broker execution only after strong audit, risk and compliance controls.

---

## 26. Important Notes

1. Do not rely on unofficial NSE/BSE scraping for production trading.
2. Use licensed market data or official broker APIs for production.
3. Keep backtesting separate from live execution.
4. Use paper trading before live trading.
5. Do not allow automatic live trading without user confirmation and risk checks.
6. Maintain audit logs for all strategy and order-related actions.
7. Store all credentials in `.env` or secret manager, never in code.
8. Rate-limit external API calls.
9. Cache option chain and contract master data.
10. Always show data source and last updated time in the UI.


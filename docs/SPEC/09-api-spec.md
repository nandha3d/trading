# 09 — API Specification

Status: `IN PROGRESS`

> FastAPI, JSON over HTTP, all routes under `/api`. Requests validated by Pydantic; errors
> return `{ "detail": "<message>" }` with the right status. This document is the contract
> between frontend and backend — both sides are generated from / checked against it.

## 1. Conventions

- Base path: `/api`
- Content-Type: `application/json`
- Dates: `YYYY-MM-DD`. Times: `HH:MM` (24h IST).
- Errors: `400` (validation/domain), `404` (unknown resource), `500` (unexpected).
- Money: rupees as numbers (rounded to 2 dp in responses).

## 2. Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/status` | DB coverage / health |
| GET | `/api/expiries/{underlying}` | list available expiries |
| GET | `/api/options-chain/dates/{underlying}/{expiry}` | trade dates with data |
| GET | `/api/options-chain/data` | chain snapshot + greeks + summary |
| POST | `/api/backtest` | run a backtest |
| POST | `/api/strategy/payoff` | payoff curve + greeks |
| POST | `/api/indicators/preview` | (`PLANNED`) compute indicator series for charting |

## 3. POST `/api/backtest`

### Request
```jsonc
{
  "underlying": "NIFTY",
  "start": "2023-01-02",
  "end": "2023-12-29",
  "expiry_offset": 0,
  "entry_time": "09:20",         // fallback time entry if no entry_tree
  "exit_time": "15:15",

  "candle_interval": 5,          // minutes: 1|3|5|15|30|60
  "candle_source": "SPOT",       // SPOT | OPTION

  "legs": [
    { "action":"SELL","opt_type":"CE","selection":"ATM","value":0,"lots":1,
      "sl_pct":100,"sl_unit":"PERCENT","tp_pct":50,"tp_unit":"PERCENT" }
  ],

  "indicators": [
    { "name":"ema9","type":"EMA","period":9,"field":"close" },
    { "name":"ema21","type":"EMA","period":21,"field":"close" },
    { "name":"rsi14","type":"RSI","period":14,"field":"close" }
  ],

  "entry_tree": {
    "join":"AND",
    "conditions":[
      { "lhs":{"kind":"INDICATOR","ref":"ema9"}, "op":"CROSS_ABOVE",
        "rhs":{"kind":"INDICATOR","ref":"ema21"} },
      { "lhs":{"kind":"INDICATOR","ref":"rsi14"}, "op":"GT",
        "rhs":{"kind":"CONST","const":50} }
    ]
  },
  "exit_tree": {
    "join":"OR",
    "conditions":[
      { "lhs":{"kind":"INDICATOR","ref":"ema9"}, "op":"CROSS_BELOW",
        "rhs":{"kind":"INDICATOR","ref":"ema21"} }
    ]
  },

  "exit_conditions": {
    "overall_sl_pct":100, "overall_target_pct":50, "trailing_sl_pct":0,
    "force_exit_time":"15:20", "re_entry_after_sl":false
  },
  "entry_conditions": {
    "weekdays":[0,1,2,3,4],
    "min_pcr":0,"max_pcr":0,"min_iv_rank":0,"max_iv_rank":0,
    "use_vix_gate":false, "vix_regimes":["normal","elevated"]
  },

  "costs": {
    "brokerage_flat":20, "brokerage_mode":"FLAT",
    "slippage_pct":0, "use_taxes":true
  }
}
```

### Validation rules
- `candle_interval` ∈ {1,3,5,15,30,60}.
- Every `entry_tree`/`exit_tree` indicator `ref` must match a declared `indicators[].name`
  (or `name.band` for multi-output) → else 400 `unknown indicator ref`.
- `op` ∈ operator enum → else 400.
- `legs` non-empty.
- `start ≤ end`.

### Response
```jsonc
{
  "stats": {
    "trades":142,"win_rate":0.71,"net_pnl":182340.5,
    "expectancy":1284.1,"avg_win":3120.0,"avg_loss":-2010.5,
    "max_drawdown":-21450.0,"sharpe":1.82,
    "profit_factor":1.9,"recovery_factor":8.5,
    "max_win_streak":9,"max_loss_streak":4,
    "annualisation":"per_trade"            // states Sharpe basis
  },
  "trades":[
    {
      "day":"2023-03-09","entry_ts":"2023-03-09T09:25:00","exit_ts":"...T11:40:00",
      "entry_spot":17580.2,
      "gross":4200.0,"cost":131.5,"net":4068.5,
      "exit_reason":"TARGET","skip_reason":"",
      "legs":[
        {"action":"SELL","opt_type":"CE","strike":17600,"qty":75,
         "entry":150.2,"exit":90.1,"exit_reason":"TARGET"}
      ],
      "signal_snapshot":{"ema9":17585.1,"ema21":17560.4,"rsi14":58.3}
    }
  ],
  "equity_curve":[0,4068.5],
  "skipped_days":63,
  "skipped":[
    {"day":"2023-03-10","skip_reason":"ema_no_cross"}
  ]
}
```

## 4. POST `/api/strategy/payoff`

### Request
```jsonc
{ "underlying":"NIFTY","spot":22000,"expiry":"2024-05-30","current_date":"2024-05-20",
  "r":0.065,
  "legs":[ {"action":"SELL","opt_type":"CE","strike":22100,"lots":1,
            "entry_price":150,"underlying":"NIFTY"} ] }
```
### Response
```jsonc
{ "curve":[{"spot":19360,"expiry_pnl":-100,"today_pnl":-50}],
  "breakevens":[21850,22250],
  "max_profit":11250,"max_loss":-999999,"net_premium":11250,
  "net_greeks":{"delta":-12.3,"gamma":0.004,"theta":520.0,"vega":-340.0} }
```

## 5. GET `/api/options-chain/data`

Query: `underlying`, `expiry`, `ts`. Returns per-strike CE/PE with `close, volume, oi, iv,
delta, theta, oi_change` plus a `summary { pcr, max_pain, total_ce_oi, total_pe_oi }`.

## 6. GET `/api/indicators/preview` (`PLANNED`)

Compute one or more indicators over a date range for charting/validation in the UI without
running a full backtest.
```jsonc
// request
{ "underlying":"NIFTY","start":"2024-05-01","end":"2024-05-02",
  "candle_interval":5, "indicators":[{"name":"ema9","type":"EMA","period":9,"field":"close"}] }
// response
{ "bars":[{"ts":"2024-05-01T09:20:00","open":1,"high":2,"low":1,"close":2}],
  "series":{"ema9":[null,17585.1]} }
```

## 7. Error Envelope

```jsonc
{ "detail": "unknown indicator ref: ema99" }     // 400
{ "detail": "no data for NIFTY in range" }        // 404/400
{ "detail": "backtest error: <safe message>" }    // 500
```
No stack traces leak to the client. Server logs carry full context.

## 8. Versioning & Compatibility

- New optional fields are additive (defaulted) so old clients keep working.
- Breaking changes bump a path prefix (`/api/v2/...`) — not silent field repurposing.
- The Pydantic models in `api/models.py` are the source of truth; this doc mirrors them and
  is checked in CI (schema-diff test) to prevent drift.

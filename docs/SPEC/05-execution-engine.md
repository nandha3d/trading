# 05 — Execution Engine (`execution.py` + `engine.py`)

Status: `IN PROGRESS` (per-leg + portfolio exits exist) · `PLANNED` (candle-driven entry/exit, fills realism)

> Simulates how orders would actually have filled. Accuracy here means: real fill prices,
> realistic slippage, correct side accounting, and strict chronological processing with no
> look-ahead.

## 1. State Machine (per day)

```
        ┌────────┐  entry_tree True (or time entry)   ┌──────────────┐
        │  FLAT  │ ─────────────────────────────────► │ IN_POSITION  │
        └────────┘                                     └──────┬───────┘
            ▲                                                 │
            │   exit (signal / risk / time / force)           │
            └─────────────────────────────────────────────────┘
       re_entry_after_exit ? back to FLAT (same session) : DONE
```

## 2. Order Lifecycle

```
OPEN:
  resolve strike per leg (ATM offset / nearest-premium / nearest-delta)  → strikes.py
  fill entry @ reference price ± slippage (side-aware)
  record entry_price, qty = lots × lot_size, entry_ts, entry_spot
HOLD:
  each candle close → update MTM from option 1-min close (forward-filled within day)
  apply risk rules + exit tree
CLOSE:
  fill exit @ reference price ± slippage (opposite side)
  exit_reason ∈ {SIGNAL_EXIT, STOPLOSS, TARGET, TRAIL, TIME, FORCE, LEG_SL, LEG_TP}
```

## 3. Fill Model

### Reference price
- Entry/exit reference = the option's **1-minute close** at the decision minute (the minute
  the interval bar closes, or the configured entry minute for time entries).
- v1 uses close-to-close fills. v2 may add OHLC-aware fills (e.g. SL triggered intrabar at
  the stop level if `low ≤ stop ≤ high`).

### Slippage (side-aware)
```
buy  fill = ref × (1 + slippage_pct/100)
sell fill = ref × (1 - slippage_pct/100)
```
Slippage always **worsens** the fill. Applied on both entry and exit. Default 0; configurable
per backtest. Models market-order impact + bid/ask without needing quote depth.

### Liquidity guard
- If reference premium ≤ 0 or strike absent at the minute → leg cannot fill → trade skipped
  (`skip_reason="no_option_quote"`). Never fill at a fabricated price.

## 4. Side Accounting (the sign bug retail tools make)

For a leg with entry price `E`, exit price `X`, quantity `Q`:

```
SELL leg P&L = (E − X) × Q          # sold high, buy back low = profit
BUY  leg P&L = (X − E) × Q          # bought low, sell high = profit
```

Charges are computed on the actual buy value and sell value (see [06](06-cost-model.md)),
**not** assuming entry=buy. For a SELL leg, entry is the sell side and exit is the buy side.

## 5. Intraday Walk (candle-driven)

```
walk(candles, indicators, option_prices):
  state = FLAT; trade = None
  for i, bar in enumerate(candles):
     t_minute = bar.close_minute
     if state == FLAT:
        if pre_filters_ok and eval_group(entry_tree, .., i):
           trade = open_legs(t_minute)         # fills at this minute
           state = IN_POSITION
     else:  # IN_POSITION
        mtm = mark_to_market(trade, option_prices, t_minute)
        r = risk.step(trade, mtm, t_minute)    # 07
        if r.exit:
           close_legs(trade, t_minute, r.reason); state = settle_or_reenter()
        elif eval_group(exit_tree, .., i):
           close_legs(trade, t_minute, "SIGNAL_EXIT"); state = settle_or_reenter()
     if t_minute >= force_exit_time and state == IN_POSITION:
        close_legs(trade, t_minute, "FORCE"); state = DONE
  if state == IN_POSITION: close_legs(trade, exit_time, "TIME")
```

### Precedence on a single bar
1. Force-exit time (hard stop).
2. Risk exit (portfolio SL/target/trail, per-leg SL/TP).
3. Signal exit (exit tree).

Capital-preservation rules outrank discretionary signals.

## 6. Mark-to-Market

```
MTM(trade, t) = Σ_legs  side_sign(leg) × (entry[leg] − price(leg, t)) × qty[leg]
                where side_sign(SELL)=+1, side_sign(BUY)=−1
                price(leg, t) = forward-filled 1-min close up to minute t (within day)
```
MTM drives portfolio SL/target/trail. Forward-fill only within the day; a missing minute
holds the last known price (never reaches across days, never interpolates future).

## 7. Strike Selection (`strikes.py`)

| Mode | Logic |
|------|-------|
| **ATM + offset** | `atm = round(spot/step)×step`; strike = `atm + offset×step`. |
| **Nearest premium** | At entry minute, pick the strike whose premium is closest to target. |
| **Nearest delta** | Compute BSM delta per strike from IV; pick closest to target abs(delta). |

Spot for ATM is the **real** `spot_1m` close at entry minute (never synthetic). Premium/delta
modes read the live chain snapshot at the entry minute only (no look-ahead across the day).

## 8. Multi-Expiry (calendars)

Legs may carry independent `expiry_offset` (e.g. sell current week, buy next week). Each leg
resolves its own expiry from the expiry list; MTM and fills use that leg's expiry series.

## 9. Re-Entry

- `re_entry_after_exit` (signal/SL): after a close, return to FLAT and allow the entry tree to
  fire again in the same session, up to `max_reentries` (default 1).
- Each re-entry is a distinct sub-trade with its own legs and reasons; reported individually.

## 10. Trade Record (emitted)

```
Trade {
  day, entry_ts, exit_ts, entry_spot,
  legs: [ {action, opt_type, strike, qty, entry, exit, exit_reason} ],
  gross, cost, net,
  exit_reason (combined),
  signal_snapshot: { indicator name → value at entry bar },   # audit
  skip_reason ("" if traded)
}
```
`signal_snapshot` lets the report explain *why* each trade fired — essential for audit and
debugging strategy logic.

## 11. Determinism

- Candles, indicators, and option prices are fixed inputs; the walk is a pure loop.
- No RNG in execution. Slippage is deterministic (fixed %).
- Same config + same data → identical trades. Verified by the reproducibility gate ([11](11-testing-validation.md)).

# 06 — Cost Model (`costs.py`)

Status: `IMPLEMENTED` (core) · `PLANNED` (contract-note validation)

> Indian options trading carries a stack of statutory charges. Ignoring them is the single
> biggest reason backtests overstate returns. This model matches a real broker contract note
> to within ₹0.50 per round-trip leg.

## 1. Charge Components (NSE options, per leg round-trip)

| Charge | Rate (as of 2024-25) | Applied on |
|--------|----------------------|------------|
| **Brokerage** | flat ₹20/order (or %) | per order (entry + exit = 2 orders) |
| **STT** | 0.10% (0.0010) | **sell-side premium only** (on exit if bought, on entry if sold) |
| **Exchange txn** | 0.03503% (0.0003503) NSE | buy + sell premium turnover |
| **SEBI** | 0.0001% (0.000001) | buy + sell turnover |
| **Stamp duty** | 0.003% (0.00003) | **buy-side only** |
| **GST** | 18% (0.18) | on (brokerage + exchange txn + SEBI) |
| **IPFT** | 0.0005% (NSE, optional) | turnover (small; include for exactness) |

> Rates change with budgets/circulars. Keep them in a single `RATE_TABLE` dict with an
> effective-date key so historical backtests can use period-correct rates (v2).

## 2. Side-Aware Turnover

For a leg with entry price `E`, exit price `X`, quantity `Q`:

```
if action == SELL:        # opened by selling, closed by buying
    sell_value = E × Q    # entry is the sell
    buy_value  = X × Q    # exit is the buy
else:  # BUY              # opened by buying, closed by selling
    buy_value  = E × Q
    sell_value = X × Q
```

This is the crux: **STT applies to the sell side**, **stamp duty to the buy side**. Assuming
entry is always the buy (a common bug) misplaces STT and stamp duty, skewing net P&L.

## 3. Formula

```python
def leg_cost(entry, exit, qty, action, p) -> float:
    sell_val, buy_val = side_values(entry, exit, qty, action)
    brokerage = 2 * p.brokerage_flat                 # 2 orders; or %·turnover if % mode
    if not p.use_taxes:
        return brokerage
    stt      = sell_val * 0.0010
    exch     = (buy_val + sell_val) * 0.0003503
    sebi     = (buy_val + sell_val) * 0.000001
    ipft     = (buy_val + sell_val) * 0.000005       # optional
    stamp    = buy_val  * 0.00003
    gst      = (brokerage + exch + sebi + ipft) * 0.18
    return brokerage + stt + exch + sebi + ipft + stamp + gst
```

## 4. Slippage (separate from charges)

Slippage is modelled in execution ([05 §3](05-execution-engine.md)) as a price adjustment,
not a fee. It reduces gross P&L before charges:

```
slippage_cost = Σ_legs  entry_price × (slippage_pct/100) × qty   (per fill side)
```
Reported separately from statutory charges so the user sees both. Combined "cost" =
statutory + slippage.

## 5. Trade-Level Aggregation

```
trade.gross = Σ leg side-aware P&L                        # before any cost
trade.cost  = Σ leg_cost(...) + slippage_cost
trade.net   = trade.gross − trade.cost
```

## 6. Brokerage Modes

| Mode | Definition |
|------|------------|
| **Flat** | ₹20 per order (Zerodha/Angel style), 2 orders per leg round-trip. |
| **Percent** | `pct × turnover`, capped at ₹20/order (typical discount-broker cap). |
| **Zero** | research mode (gross-of-brokerage); taxes still optional. |

## 7. Configuration (per backtest)

```
CostParams {
  brokerage_flat: float = 20.0
  brokerage_mode: "FLAT" | "PERCENT" | "ZERO" = "FLAT"
  brokerage_pct:  float = 0.03          # if PERCENT
  slippage_pct:   float = 0.0
  use_taxes:      bool  = true          # toggle full statutory stack
}
```

## 8. Worked Example (NIFTY short straddle, 1 lot = 75)

Sell CE @ ₹150, buy back @ ₹90; Sell PE @ ₹140, buy back @ ₹100. Lot 75.

```
CE leg: sell_val=150×75=11250, buy_val=90×75=6750
PE leg: sell_val=140×75=10500, buy_val=100×75=7500
brokerage = 4 orders × ₹20 = ₹80
STT       = (11250+10500)×0.0010 = ₹21.75
exch      = (11250+6750+10500+7500)×0.0003503 = ₹12.61
sebi      = 36000×0.000001 = ₹0.04
stamp     = (6750+7500)×0.00003 = ₹0.43
gst       = (80+12.61+0.04)×0.18 = ₹16.67
total cost ≈ ₹131.50
gross = (150−90)×75 + (140−100)×75 = 4500+3000 = ₹7500
net   = 7500 − 131.50 = ₹7368.50
```

## 9. Validation Requirement

A golden test reproduces a real Zerodha/Angel contract note for a known multi-leg trade and
asserts `abs(model_cost − note_cost) ≤ ₹0.50` per leg. Any rate change must update both the
`RATE_TABLE` and the golden fixture in the same commit ([11](11-testing-validation.md)).

## 10. Frontend Parity

The frontend recompute (in `ResultsPanel`) MUST mirror this exact formula, including
side-aware turnover, so the "Recalculate with charges" panel matches backend numbers. The
TypeScript implementation is a direct port of §3 and is covered by a parity test comparing a
sample trade's frontend vs backend cost.

# 08 — Metrics & Analytics (`metrics.py`)

Status: `IMPLEMENTED` (core stats, MDD, Monte Carlo) · `PLANNED` (Sortino, Calmar, regime tables)

> Every metric is computed on **net** P&L (after costs) unless explicitly labelled gross.
> Definitions follow institutional conventions so numbers are comparable to fund reporting.

## 1. Core Performance Metrics

| Metric | Definition |
|--------|------------|
| **Total Net P&L** | Σ trade.net |
| **Trades** | count of executed trades (skips excluded) |
| **Win Rate** | wins / trades, win = net > 0 |
| **Average Win** | mean(net) over winners |
| **Average Loss** | mean(net) over losers (negative) |
| **Expectancy** | total_net / trades (₹/trade) |
| **Profit Factor** | gross_profit / abs(gross_loss); ∞ if no losses |
| **Payoff Ratio** | abs(avg_win / avg_loss) |

## 2. Risk-Adjusted Returns

### Sharpe (annualised)
```
r       = per-trade net returns (or daily aggregated)
mean    = mean(r)
sd      = stdev(r, ddof=1)
Sharpe  = (mean / sd) × sqrt(periods_per_year)
```
`periods_per_year`: 252 if daily aggregation, or trades/year if per-trade. Document which is
used in the report so it is not misread.

### Sortino (`PLANNED`)
```
downside_dev = sqrt(mean(min(r,0)^2))
Sortino      = (mean / downside_dev) × sqrt(periods_per_year)
```
Penalises only downside volatility — more honest for asymmetric option strategies.

### Calmar (`PLANNED`)
```
Calmar = annualised_return / abs(max_drawdown_pct)
```

## 3. Drawdown

```
equity[i]   = Σ net[0..i]                 (cumulative, starts at 0)
peak[i]     = max(equity[0..i])
drawdown[i] = equity[i] − peak[i]         (≤ 0)
MaxDrawdown = min(drawdown)               (most negative)
```
Also report: **max drawdown duration** (longest bars/days underwater) and **recovery factor**.

### Recovery Factor
```
RecoveryFactor = total_net / abs(MaxDrawdown)
```
How many times the strategy earned back its worst drawdown. > 3 is healthy.

### Return-to-MDD (per year)
Per calendar year: `year_net / abs(year_mdd)` — surfaced in the monthly-returns grid.

## 4. Streaks & Drawdown Trades

```
MaxWinStreak   = longest run of consecutive winners
MaxLossStreak  = longest run of consecutive losers
MaxTradesInDD  = most consecutive trades while equity < prior peak
```
These quantify psychological/operational survivability, not just final return.

## 5. Monte Carlo Drawdown Simulation

Trade order is partly luck. Monte Carlo estimates how bad drawdown *could* have been by
reshuffling the trade sequence.

```
monte_carlo_mdd(nets, iters=10000, confidence=95, seed=42):
  for k in range(iters):
      shuffled = fisher_yates(nets, rng)      # seeded RNG → reproducible
      mdd_k = max_drawdown(shuffled)
      collect mdd_k
  sort ascending
  return mdd[floor((1 − confidence/100) × iters)]   # e.g. 5th percentile worst
```
- **Seeded RNG** (default seed 42) → identical result every run (determinism requirement).
- Output: "projected MDD at 95% confidence" — the drawdown you should plan capital around,
  typically worse than the historical single-path MDD.
- Assumes trade independence (no autocorrelation modelling) — documented limitation; a
  block-bootstrap variant is `PLANNED` for serially-correlated strategies.

## 6. Period Returns Grid

- **Monthly**: net P&L per (year, month) → heatmap grid.
- **Yearly**: total, MDD, Return-to-MDD per year.
- Computed from executed trades grouped by `day` → year/month buckets.

## 7. Distribution & Regime Analysis (`PLANNED`)

| View | Purpose |
|------|---------|
| P&L histogram | shape of returns (fat tails, skew). |
| By weekday | which days carry the edge. |
| By DTE bucket | 0DTE vs weekly vs monthly performance. |
| By IV-regime | performance in low/normal/elevated/extreme vol. |
| By exit-reason | TARGET/STOPLOSS/TRAIL/TIME distribution. |

## 8. Skipped-Day Analytics

The report shows count and breakdown of skipped days by reason (no signal, filter rejected,
no data). A strategy skipping 80% of days is selective by design or broken by filter — the
breakdown distinguishes the two.

## 9. Equity Curve & Underwater Plot

- **Equity curve**: cumulative net over trade index / date.
- **Underwater plot** (`PLANNED`): drawdown[i] over time — visualises pain periods.

## 10. Metric Integrity Rules

- All metrics on net unless labelled gross.
- Empty / single-trade series → metrics return defined zeros/∞, never NaN/crash.
- Monte Carlo is seeded; same input → same projected MDD.
- Sharpe/Sortino annualisation factor stated in the report payload, not hidden.
- Frontend recomputes some metrics live (after charge re-calc / weekday filter); those
  recomputations MUST match these definitions exactly (parity-tested).

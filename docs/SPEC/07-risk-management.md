# 07 — Risk Management (`risk.py`)

Status: `IMPLEMENTED` (per-leg + portfolio SL/TP/trail) · `PLANNED` (state-machine refactor, re-entry)

> Risk rules decide when to exit independent of strategy signals. They are the difference
> between a survivable strategy and ruin. All thresholds support multiple units (premium
> points, % of premium, underlying move) so they match how desks actually set stops.

## 1. Risk Hierarchy

```
Portfolio level   (whole position)
  ├── Overall Target   — book profit when combined MTM ≥ target
  ├── Overall SL       — cut when combined MTM ≤ −stop
  └── Trailing SL      — lock profit: exit when MTM drops X from peak
Leg level         (each leg independently)
  ├── Leg SL           — exit one leg if its loss exceeds threshold
  ├── Leg TP           — book one leg at profit threshold
  └── Leg Trailing     — per-leg trail (trigger + step)
Time level
  ├── Force exit time  — hard flat by HH:MM
  └── Session end      — flat at exit_time if still open
```

## 2. Threshold Units (AlgoTest/Quantman parity)

| Unit | Meaning | Conversion to premium points |
|------|---------|------------------------------|
| `POINTS` | absolute premium points | value |
| `PERCENT` | % of entry premium | value/100 × entry_premium |
| `UNDERLYING_PTS` | underlying move in points | value × abs(entry_delta) |
| `UNDERLYING_PCT` | underlying move % | value/100 × entry_spot × abs(entry_delta) |

Underlying-based units convert via the leg's **entry delta** (premium move ≈ |delta| ×
underlying move). This lets a user say "exit if NIFTY moves 1%" and have it applied per leg.

## 3. Portfolio Exits

Evaluated on combined MTM each candle bar:

```
base = abs(net_entry_premium)          # credit (sell) or debit (buy), absolute
peak = max(peak, mtm)                  # running peak of combined MTM
TARGET:    mtm >= base × target_pct/100        → exit "TARGET"
STOPLOSS:  mtm <= −base × sl_pct/100           → exit "STOPLOSS"
TRAILING:  peak > 0 and (peak − mtm) >= base × trail_pct/100 → exit "TRAIL"
```

Trailing only activates after the position has been in profit (`peak > 0`). The trail is
measured as a drop **from the peak**, in the same % base — so a 30% trail on a position that
peaked exits when MTM falls 30%-of-base below the peak.

## 4. Per-Leg Exits

Evaluated per leg each minute using "favourable points":

```
fav = (entry − mark) if SELL else (mark − entry)     # premium points in our favour
LEG_TP: fav >= rule_points(tp)        → close leg "LEG_TP"
LEG_SL: fav <= −rule_points(sl)       → close leg "LEG_SL"
LEG_TRAIL:
   if fav >= trail_trigger_points:
       peak_fav = max(peak_fav, fav)
       if fav <= peak_fav − trail_step_points: → close leg "TRAIL"
```

A closed leg stops marking; the remaining legs continue. The trade closes fully when all legs
are closed or a portfolio/time rule fires.

## 5. Exit Precedence (single bar)

```
1. Force-exit time          (hard)
2. Portfolio STOPLOSS       (capital preservation)
3. Portfolio TARGET / TRAIL
4. Per-leg SL / TP / trail
5. Signal exit (exit tree)
```
If multiple fire on the same bar, the highest-precedence reason is recorded. Stops always
beat targets and signals.

## 6. State Machine (`PLANNED` refactor)

```python
class RiskState:
    peak_pnl: float = 0
    peak_fav: list[float]        # per leg
    leg_open: list[bool]
    entry_premium: float

def step(state, trade, mtm, leg_marks, t) -> ExitSignal:
    # returns ExitSignal(exit: bool, reason: str, legs: list[int] | "ALL")
```
Pure function: given state + current marks → decision. No I/O. Unit-tested with synthetic
MTM paths (e.g. "rises to +50% then reverses → TRAIL fires at the right bar").

## 7. Position Sizing (`PLANNED`)

| Mode | Definition |
|------|------------|
| **Fixed lots** | constant lots per leg (v1 default). |
| **Fixed capital** | lots = floor(capital / margin_per_lot); needs margin model. |
| **Risk-based** | lots sized so max-loss (SL distance × qty) = risk_per_trade. |
| **Kelly-capped** | fraction of edge, capped (research mode). |

v1 ships Fixed lots; sizing modes are additive and do not change the exit logic.

## 8. Re-Entry & Re-Execution

- `re_entry_after_sl`: after a stop, return to FLAT and allow re-entry (signal or time) up to
  `max_reentries`. Models "stopped out then re-enters on next signal".
- `re_execute_after_target`: optionally re-enter after booking target (martingale-style;
  off by default, flagged as aggressive).

## 9. Edge Cases

| Case | Handling |
|------|----------|
| Net premium 0 (delta-neutral debit=credit) | base = 1.0 to avoid div-by-zero; %-rules effectively disabled, points-rules still work. |
| Gap through stop | v1 fills at next available 1-min close (close-to-close); v2 OHLC fills at stop level if breached intrabar. |
| All legs leg-SL'd same bar | trade closes fully, reason "LEG_SL" (or "MIXED" if heterogeneous). |
| Trail + target same bar | target wins (locks more profit) unless trail level is higher. |

## 10. Reporting

Every exit carries a machine-readable reason. The report aggregates exit-reason distribution
(how often TARGET vs STOPLOSS vs TRAIL vs TIME) — a key diagnostic: a strategy exiting mostly
on TIME isn't using its edges; mostly on STOPLOSS is mis-tuned.

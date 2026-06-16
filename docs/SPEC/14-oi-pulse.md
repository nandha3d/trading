# 14 — OI Pulse Suite (Connecting Dots + OI Analysis)

Clone of the OI Pulse toolset (nifty20.com/oi-pulse-review). Two flagship
screens plus supporting OI tools, built on the existing Angel One live feed,
`options_1m`/`spot_1m` DuckDB tables, and the indicator library.

---

## 1. Core engine — OI interpretation (shared by every screen)

Standard 4-quadrant classification from price/LTP change vs OI change:

| Price / LTP | OI change | Interpretation | Bias |
|-------------|-----------|----------------|------|
| ↑ | ↑ | **Long Buildup**   | Bullish |
| ↓ | ↑ | **Short Buildup**  | Bearish |
| ↑ | ↓ | **Short Covering** | Bullish |
| ↓ | ↓ | **Long Unwinding** | Bearish |

- "Extreme" variant when the move is large (OI change > `k ×` rolling-avg OI
  change, default `k = 2`).
- One function: `classify_oi(price_chg, oi_chg, strength=None) -> Interpretation`.
- Call side and Put side interpreted independently from their own LTP + OI.

`src/analysis/oi_interpret.py` — pure functions, no IO:
- `classify_oi(price_chg, oi_chg)` → enum (`LONG_BUILDUP`, `SHORT_BUILDUP`,
  `SHORT_COVERING`, `LONG_UNWINDING`, `NEUTRAL`).
- `interpret_strength(oi_chg, avg_oi_chg, k=2.0)` → `"normal" | "extreme"`.
- `bias_of(interp)` → `+1 / -1 / 0`.
- `dhl_break(price, day_high, day_low)` → `"D.H.B" | "D.L.B" | None` with the
  broken level (matches the "Call D. H/L Break" column).

---

## 2. Resampling — 1m → N-min buckets

`src/analysis/resample.py`:
- `resample_spot(df_1m, minutes)` → bucketed OHLCV (Polars group_by_dynamic).
- `resample_options(df_1m, minutes)` → per (strike, option_type) bucketed OHLC,
  `volume` summed, `oi` = last in bucket, `oi_chg` = bucket-over-bucket diff.
- Intervals: 1 / 3 / 5 / 15 / 60 min. Anchored to 09:15 IST session open.

---

## 3. Screen A — Connecting Dots

Per-interval confluence table (screenshot 1). Newest row on top.

Columns (each a green ▲ bull / red ▼ bear chip):
- **Trend** — composite of the others → `Bearish / Bullish / Extreme Bullish`
  (and `Extreme Bearish`). Band by count of bullish sub-signals.
- **Price** — bucket close vs prev close.
- **OI Interpretation** — `classify_oi` on aggregate futures/spot OI bias.
- **VIX** — India VIX direction (falling VIX = bullish for index).
- **VWAP** — spot vs intraday VWAP.
- **Supertrend** — Supertrend direction (ATR-based, stateful).
- **RSI** — RSI > 50 bullish.

Composite bands (6 sub-signals): `≥5 bull → Extreme Bullish`, `4 → Bullish`,
`3 → Neutral`, `2 → Bearish`, `≤1 → Extreme Bearish` (tunable).

Backend `src/analysis/connecting_dots.py`:
- `build_dots(underlying, day, interval, mode)` → list of interval rows.
- Live mode: from the live feed buffer. Historical: from DuckDB.

API: `GET /api/dots?underlying&date&interval&mode=live|historical`.

Frontend `ConnectingDots.tsx`: controls (Mode toggle, Name, Date, Interval,
Go), table of chips, Extreme rows tinted green/red.

---

## 4. Screen B — OI Analysis

Per-strike, per-bucket Call/Put table (screenshot 2).

Columns: `Time, Call OI, Total OI Chng, Call D.H/L Break, Call LTP,
Call LTP Chng, Call Chng in OI, Call OI Interpretation, Strike,
Put OI Interpretation, Put Chng in OI, Put LTP Chng, Put LTP …` (mirror).

Backend `src/analysis/oi_analysis.py`:
- `build_oi_analysis(underlying, day, expiry, strike, interval, mode)`.
- Buckets options by strike + interval, runs `classify_oi` per side, computes
  D.H/L break vs running day high/low.

API: `GET /api/oi-analysis?underlying&date&expiry&strike&interval&mode`.

Frontend `OiAnalysis.tsx`: colored interpretation badges —
Long Buildup (green), Short Buildup (red), Short Covering (blue),
Long Unwinding (amber). Pagination, rows-per-page.

---

## 5. Supporting OI tools (reuse engine)

- **OI Spurt / Big OI Movement** — strikes with OI change ≫ rolling avg.
- **Trending OI** — net writing direction across chain → sentiment %.
- **Active Strikes OI** — top OI-change strikes ranked, bull/bear %.
- **OI Statistics** — totals + PCR (largely done in live feed).
- **VIX & Index chart** — overlay (needs VIX data, see gaps).

---

## 6. Indicator gaps to fill (Phase 0)

`indicators.py` currently has only EMA / RSI / Bollinger. Add:
- **Supertrend** (ATR-based, stateful) — needed by Connecting Dots.
- **ATR** (Wilder smoothing) — Supertrend dependency.
- **VWAP** (intraday, volume-weighted, session-anchored).

## 7. Data gaps

- **India VIX**: no source wired yet. Add VIX token to the Angel One scrip
  resolver + a `vix_1m` table (or reuse `spot_1m` with `underlying='INDIAVIX'`);
  historical backfill needed.
- **Live N-min bucketing buffer** for live mode (rolling in-memory).

---

## 8. Build order

1. **Phase 0** — `oi_interpret.py` + `resample.py` + Supertrend/ATR/VWAP in
   `indicators.py`. Foundation; blocks everything.
2. **Connecting Dots** — highest visual payoff, reuses indicators.
3. **OI Analysis** — reuses classifier + bucketing.
4. **Supporting OI tools** — cheap once engine exists.
5. **VIX wiring + Multiple Window + Risk Calculator** (extras).

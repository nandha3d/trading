# 03 — Indicator Library (`ta.py`)

Status: `PLANNED`

> This is the most accuracy-critical document. Subtle smoothing differences (Wilder vs
> pandas-ewm, ddof=0 vs 1, EMA seed) cause silent multi-percent backtest error. Every
> formula below is specified to match **TradingView / Quantman** and is validated by the
> fixtures in [11-testing-validation.md](11-testing-validation.md).

## 1. Contract

- Input: a `pl.Series` of one price field (close/open/high/low/hl2/hlc3) plus, for some
  indicators, the full OHLC frame.
- Output: a `pl.Series` (or named dict of Series for multi-output) **aligned 1:1** to the
  input bars. Warmup positions are `null`/`NaN`, never a fabricated value.
- Pure function: no I/O, no global state. Same input → same output.
- Computed over the **continuous warmup+day** series (see [02 §7](02-data-layer.md)).

## 2. Price Fields

| Field | Definition |
|-------|------------|
| close / open / high / low | raw |
| hl2 | (high + low) / 2 |
| hlc3 (typical) | (high + low + close) / 3 |
| ohlc4 | (open + high + low + close) / 4 |

## 3. Moving Averages

### 3.1 SMA — Simple Moving Average
```
SMA[i] = mean(x[i-period+1 .. i])          for i >= period-1, else null
```
Polars: `x.rolling_mean(window_size=period)`.

### 3.2 EMA — Exponential Moving Average (TradingView parity)
```
α = 2 / (period + 1)
seed: EMA[period-1] = SMA(x[0..period-1])         ← seeded with SMA, NOT x[0]
EMA[i] = α·x[i] + (1-α)·EMA[i-1]                   for i >= period
EMA[i] = null                                       for i < period-1
```
**Critical:** TradingView seeds EMA with the SMA of the first `period` values. Using `x[0]`
as the seed (naive ewm) diverges for ~3×period bars. Implement the seed explicitly; do not
rely on `ewm_mean(span=...)` default seeding without verifying against the fixture.

### 3.3 WMA — Weighted Moving Average (optional)
```
WMA[i] = Σ (w_k · x[i-period+1+k]) / Σ w_k ,  w_k = k+1  (k=0..period-1)
```

## 4. Wilder-Smoothed Family

Wilder smoothing (RMA) uses `α = 1/period`, seeded with the SMA of the first `period` values.
This is **different** from EMA's `α = 2/(period+1)`. RSI, ATR, ADX all use RMA.

```
RMA[i] = (RMA[i-1]·(period-1) + x[i]) / period
seed:  RMA[period-1] = SMA(x[0..period-1])
```

### 4.1 RSI — Relative Strength Index
```
Δ[i]   = x[i] - x[i-1]
gain[i]= max(Δ[i], 0)        loss[i] = max(-Δ[i], 0)
avgGain = RMA(gain, period)  avgLoss = RMA(loss, period)
RS[i]   = avgGain[i] / avgLoss[i]
RSI[i]  = 100 - 100/(1 + RS[i])
edge:   avgLoss == 0 → RSI = 100 ;  avgGain == 0 → RSI = 0
```
**Do not** use `ewm(com=period-1)` blindly — verify the seed matches RMA above.

### 4.2 ATR — Average True Range
```
TR[i]  = max( high[i]-low[i],
              |high[i]-close[i-1]|,
              |low[i]-close[i-1]| )
ATR    = RMA(TR, period)        seed = SMA(TR[1..period])
```

### 4.3 ADX / DMI
```
+DM[i] = (high[i]-high[i-1]) if (high[i]-high[i-1]) > (low[i-1]-low[i]) and >0 else 0
-DM[i] = (low[i-1]-low[i])   if (low[i-1]-low[i]) > (high[i]-high[i-1]) and >0 else 0
+DI = 100 · RMA(+DM,period)/ATR
-DI = 100 · RMA(-DM,period)/ATR
DX  = 100 · |+DI - -DI| / (+DI + -DI)
ADX = RMA(DX, period)
```

## 5. Volatility Bands

### 5.1 Bollinger Bands
```
basis = SMA(x, period)
dev   = num_std · stdev(x[i-period+1..i], ddof=0)      ← population std (ddof=0)
upper = basis + dev          lower = basis - dev
```
Output dict: `{ "<name>.basis", "<name>.upper", "<name>.lower" }`.
**ddof=0** (population) matches TradingView; ddof=1 (sample) is a common silent bug.

### 5.2 Keltner Channels (optional)
```
basis = EMA(close, period)
band  = mult · ATR(period)
upper = basis + band   lower = basis - band
```

## 6. MACD
```
macd   = EMA(close, fast) - EMA(close, slow)        (fast=12, slow=26)
signal = EMA(macd, signal_period)                    (signal=9)
hist   = macd - signal
```
Output dict: `{ "<name>.macd", "<name>.signal", "<name>.hist" }`.
EMA here uses the same seeded definition as §3.2 (including seeding the signal EMA on the macd series).

## 7. Supertrend (stateful)
```
hl2      = (high+low)/2
atr      = ATR(period)                                 (period=10)
basicUp  = hl2 + mult·atr        basicLo = hl2 - mult·atr   (mult=3)
finalUp[i] = min(basicUp[i], finalUp[i-1]) if close[i-1] <= finalUp[i-1] else basicUp[i]
finalLo[i] = max(basicLo[i], finalLo[i-1]) if close[i-1] >= finalLo[i-1] else basicLo[i]
trend flips:
  if close[i] > finalUp[i-1] → uptrend (line = finalLo)
  if close[i] < finalLo[i-1] → downtrend (line = finalUp)
  else carry previous trend
supertrend[i] = finalLo[i] if uptrend else finalUp[i]
```
Output: `{ "<name>" (line value), "<name>.dir" (+1 up / -1 down) }`.
Must be computed by an explicit bar loop (stateful); vectorisation hides the carry logic.

## 8. VWAP (session-reset)
```
tp[i]   = (high[i]+low[i]+close[i]) / 3
cumPV   = cumsum(tp · volume)   reset at session start (09:15)
cumV    = cumsum(volume)        reset at session start
VWAP[i] = cumPV[i] / cumV[i]    (null if cumV == 0)
```
Resets every trading day. For index spot with zero volume, VWAP is undefined → indicator
unavailable; the condition referencing it evaluates False (warmup-not-ready semantics).

## 9. Stochastic Oscillator
```
LL = rolling_min(low, k_period)      HH = rolling_max(high, k_period)
%K = 100 · (close - LL) / (HH - LL)                 (k_period=14)
%D = SMA(%K, d_period)                               (d_period=3)
edge: HH == LL → %K = 0
```
Output dict: `{ "<name>.k", "<name>.d" }`.

## 10. Indicator Factory

```python
def compute(spec: IndicatorSpec, candles: pl.DataFrame) -> dict[str, pl.Series]:
    x = field_series(candles, spec.field)
    match spec.type:
        case "SMA":        return {spec.name: sma(x, spec.period)}
        case "EMA":        return {spec.name: ema(x, spec.period)}
        case "RSI":        return {spec.name: rsi(x, spec.period)}
        case "ATR":        return {spec.name: atr(candles, spec.period)}
        case "ADX":        return {spec.name: adx(candles, spec.period)}
        case "BBANDS":     b = bbands(x, spec.period, spec.std)
                           return {f"{spec.name}.basis":b.basis,
                                   f"{spec.name}.upper":b.upper,
                                   f"{spec.name}.lower":b.lower}
        case "MACD":       m = macd(x, spec.fast, spec.slow, spec.signal)
                           return {f"{spec.name}.macd":m.macd,
                                   f"{spec.name}.signal":m.signal,
                                   f"{spec.name}.hist":m.hist}
        case "SUPERTREND": s = supertrend(candles, spec.period, spec.mult)
                           return {spec.name:s.line, f"{spec.name}.dir":s.dir}
        case "VWAP":       return {spec.name: vwap(candles)}
        case "STOCH":      s = stoch(candles, spec.period, spec.d)
                           return {f"{spec.name}.k":s.k, f"{spec.name}.d":s.d}
```

The engine merges all returned dicts into one `indicators: dict[str, pl.Series]` keyed by
name (and `name.band` for multi-output), referenced by the condition engine ([04](04-condition-engine.md)).

## 11. Numerical & Edge Rules

- Division-by-zero → defined edge (RSI 0/100, %K 0, VWAP null) — never NaN propagation into conditions.
- Warmup positions are null; a condition with a null operand evaluates **False**.
- All math in `float64`. No premature rounding inside indicators (round only at display).
- No use of the current (forming) bar — only closed bars enter the series.

## 12. Reference Parity Requirement

For each indicator there is a golden fixture: a fixed NIFTY 5-min bar series with expected
values exported from TradingView. CI asserts `max(abs(ours - reference)) <= 0.01`. An
indicator without a passing fixture is marked `IMPLEMENTED`, never `VALIDATED`, and may not
be exposed in the UI as production-ready.

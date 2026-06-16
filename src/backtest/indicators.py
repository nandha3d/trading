"""Technical indicators computed on Polars Series of spot prices."""
from __future__ import annotations

import polars as pl


def compute_ema(series: pl.Series, period: int) -> pl.Series:
    """Exponential Moving Average."""
    return series.ewm_mean(span=period, adjust=False)


def compute_rsi(series: pl.Series, period: int = 14) -> pl.Series:
    """RSI using Wilder smoothing. Returns 0-100 float series, NaN → 50."""
    delta = series.diff()
    gain = delta.map_elements(lambda x: max(x, 0.0) if x is not None else 0.0,
                               return_dtype=pl.Float64)
    loss = delta.map_elements(lambda x: max(-x, 0.0) if x is not None else 0.0,
                               return_dtype=pl.Float64)
    avg_gain = gain.ewm_mean(com=period - 1, min_periods=period)
    avg_loss = loss.ewm_mean(com=period - 1, min_periods=period)
    rs = avg_gain / avg_loss.map_elements(
        lambda x: x if (x is not None and x != 0.0) else float("nan"),
        return_dtype=pl.Float64,
    )
    return (100.0 - (100.0 / (1.0 + rs))).fill_nan(50.0)


def compute_bollinger(series: pl.Series, period: int = 20,
                      num_std: float = 2.0) -> tuple[pl.Series, pl.Series, pl.Series]:
    """Returns (upper, middle, lower) Bollinger Bands."""
    mid = series.rolling_mean(window_size=period)
    std = series.rolling_std(window_size=period)
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


def compute_atr(high: pl.Series, low: pl.Series, close: pl.Series,
                period: int = 14) -> pl.Series:
    """Average True Range with Wilder smoothing (RMA, alpha = 1/period)."""
    prev_close = close.shift(1)
    tr = pl.DataFrame({
        "hl": (high - low).abs(),
        "hc": (high - prev_close).abs(),
        "lc": (low - prev_close).abs(),
    }).max_horizontal()
    return tr.ewm_mean(com=period - 1, adjust=False, min_periods=period)


def compute_supertrend(high: pl.Series, low: pl.Series, close: pl.Series,
                       period: int = 10, multiplier: float = 3.0
                       ) -> tuple[pl.Series, pl.Series]:
    """Supertrend. Returns (supertrend_line, direction).

    direction: +1 = uptrend (bullish, price above line),
               -1 = downtrend (bearish). Stateful band carry-forward, TradingView
    parity. NaN until ATR warms up.
    """
    atr = compute_atr(high, low, close, period).to_list()
    hl2 = ((high + low) / 2.0).to_list()
    c = close.to_list()
    n = len(c)

    st = [None] * n
    direction = [None] * n
    final_upper = [None] * n
    final_lower = [None] * n

    for i in range(n):
        a = atr[i]
        if a is None:
            continue
        basic_upper = hl2[i] + multiplier * a
        basic_lower = hl2[i] - multiplier * a

        prev_fu = final_upper[i - 1] if i > 0 and final_upper[i - 1] is not None else basic_upper
        prev_fl = final_lower[i - 1] if i > 0 and final_lower[i - 1] is not None else basic_lower
        prev_close = c[i - 1] if i > 0 else c[i]

        fu = basic_upper if (basic_upper < prev_fu or prev_close > prev_fu) else prev_fu
        fl = basic_lower if (basic_lower > prev_fl or prev_close < prev_fl) else prev_fl
        final_upper[i] = fu
        final_lower[i] = fl

        prev_dir = direction[i - 1] if i > 0 and direction[i - 1] is not None else 1
        if c[i] > fu:
            d = 1
        elif c[i] < fl:
            d = -1
        else:
            d = prev_dir
        direction[i] = d
        st[i] = fl if d == 1 else fu

    return pl.Series("supertrend", st), pl.Series("st_dir", direction)


def compute_vwap(high: pl.Series, low: pl.Series, close: pl.Series,
                 volume: pl.Series) -> pl.Series:
    """Volume-weighted average price, cumulative over the given series.

    Pass a single trading session's bars for an intraday (session-anchored)
    VWAP. typical price = (high + low + close) / 3.
    """
    tp = (high + low + close) / 3.0
    cum_tpv = (tp * volume).cum_sum()
    cum_vol = volume.cum_sum()
    return cum_tpv / cum_vol.map_elements(
        lambda x: x if (x is not None and x != 0) else float("nan"),
        return_dtype=pl.Float64,
    )


def compute_sma(series: pl.Series, period: int) -> pl.Series:
    """Simple Moving Average."""
    return series.rolling_mean(window_size=period)


def compute_macd(series: pl.Series, fast: int = 12, slow: int = 26,
                 signal: int = 9) -> tuple[pl.Series, pl.Series, pl.Series]:
    """MACD. Returns (macd_line, signal_line, histogram).

    macd = EMA(fast) - EMA(slow); signal = EMA(macd, signal); hist = macd - signal.
    """
    ema_fast = series.ewm_mean(span=fast, adjust=False)
    ema_slow = series.ewm_mean(span=slow, adjust=False)
    macd = ema_fast - ema_slow
    sig = macd.ewm_mean(span=signal, adjust=False)
    hist = macd - sig
    return macd, sig, hist


def last_valid(s: pl.Series) -> float | None:
    """Last non-null value in series."""
    vals = s.drop_nulls()
    return float(vals[-1]) if len(vals) > 0 else None

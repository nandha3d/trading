"""OI interpretation engine — the 4-quadrant classifier shared by every
OI Pulse screen (Connecting Dots, OI Analysis, Spurt, Trending OI ...).

Pure functions, no IO. See docs/SPEC/14-oi-pulse.md.

Price/LTP up + OI up   -> Long Buildup   (bullish)
Price/LTP down + OI up -> Short Buildup  (bearish)
Price/LTP up + OI down -> Short Covering (bullish)
Price/LTP down + OI down -> Long Unwinding (bearish)
"""
from __future__ import annotations

from enum import Enum
from typing import Optional


class Interp(str, Enum):
    LONG_BUILDUP = "Long Buildup"
    SHORT_BUILDUP = "Short Buildup"
    SHORT_COVERING = "Short Covering"
    LONG_UNWINDING = "Long Unwinding"
    NEUTRAL = "Neutral"


# bias: +1 bullish, -1 bearish, 0 neutral
_BIAS = {
    Interp.LONG_BUILDUP: +1,
    Interp.SHORT_COVERING: +1,
    Interp.SHORT_BUILDUP: -1,
    Interp.LONG_UNWINDING: -1,
    Interp.NEUTRAL: 0,
}


def classify_oi(price_chg: float, oi_chg: float, eps: float = 1e-9) -> Interp:
    """Classify one instrument's move into the OI quadrant.

    price_chg = LTP/close change vs previous bucket.
    oi_chg    = open-interest change vs previous bucket.
    Moves within +/- eps are treated as flat -> NEUTRAL.
    """
    if price_chg is None or oi_chg is None:
        return Interp.NEUTRAL
    p_up = price_chg > eps
    p_dn = price_chg < -eps
    oi_up = oi_chg > eps
    oi_dn = oi_chg < -eps

    if not (p_up or p_dn) or not (oi_up or oi_dn):
        return Interp.NEUTRAL
    if p_up and oi_up:
        return Interp.LONG_BUILDUP
    if p_dn and oi_up:
        return Interp.SHORT_BUILDUP
    if p_up and oi_dn:
        return Interp.SHORT_COVERING
    return Interp.LONG_UNWINDING  # p_dn and oi_dn


def bias_of(interp: Interp) -> int:
    """+1 bullish / -1 bearish / 0 neutral."""
    return _BIAS.get(interp, 0)


def interpret_strength(oi_chg: float, avg_oi_chg: float, k: float = 2.0) -> str:
    """'extreme' when |oi_chg| exceeds k x rolling-avg |oi change|, else 'normal'."""
    if avg_oi_chg is None or avg_oi_chg <= 0:
        return "normal"
    return "extreme" if abs(oi_chg or 0.0) > k * avg_oi_chg else "normal"


def dhl_break(price: float, day_high: float, day_low: float,
              prev_high: Optional[float] = None,
              prev_low: Optional[float] = None) -> Optional[dict]:
    """Day-High/Low break detection (the 'Call D. H/L Break' column).

    Returns {"type": "D.H.B"|"D.L.B", "level": float} when `price` makes a new
    day high/low. If prev_high/prev_low given, only fires on a *fresh* break
    (price exceeds the previous running extreme), avoiding repeat signals.
    """
    if price is None:
        return None
    hi = prev_high if prev_high is not None else day_high
    lo = prev_low if prev_low is not None else day_low
    if day_high is not None and price >= day_high and (prev_high is None or price > hi):
        return {"type": "D.H.B", "level": round(float(day_high), 2)}
    if day_low is not None and price <= day_low and (prev_low is None or price < lo):
        return {"type": "D.L.B", "level": round(float(day_low), 2)}
    return None

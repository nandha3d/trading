"""Black-Scholes IV + delta, for delta-based strike selection and unit conversion.

Uses py_vollib. IV is solved from the option's traded price; delta derived from
that IV. Returns None when the solve is impossible (price <= intrinsic, etc.)
so callers can skip bad rows instead of storing garbage.
"""
from __future__ import annotations

import warnings

warnings.filterwarnings("ignore")  # silence py_vollib deprecation + solver noise

try:
    from py_vollib.black_scholes.implied_volatility import implied_volatility
    from py_vollib.black_scholes.greeks.analytical import delta as _bs_delta
except Exception:  # pragma: no cover
    implied_volatility = None
    _bs_delta = None

RISK_FREE = 0.065  # India ~6.5%; override per need


def _flag(option_type: str) -> str:
    return "c" if option_type.upper() == "CE" else "p"


def years_to_expiry(now, expiry) -> float:
    """now: datetime, expiry: date. Returns time in years (>= tiny)."""
    from datetime import datetime, time

    exp_dt = datetime.combine(expiry, time(15, 30))
    secs = max((exp_dt - now).total_seconds(), 60.0)
    return secs / (365.0 * 24 * 3600)


def iv(price: float, spot: float, strike: float, t_years: float, option_type: str,
       r: float = RISK_FREE) -> float | None:
    if implied_volatility is None or price <= 0 or spot <= 0 or t_years <= 0:
        return None
    try:
        return float(implied_volatility(price, spot, strike, t_years, r, _flag(option_type)))
    except Exception:
        return None


def delta(price: float, spot: float, strike: float, t_years: float, option_type: str,
          r: float = RISK_FREE) -> float | None:
    v = iv(price, spot, strike, t_years, option_type, r)
    if v is None:
        return None
    try:
        return float(_bs_delta(_flag(option_type), spot, strike, t_years, r, v))
    except Exception:
        return None

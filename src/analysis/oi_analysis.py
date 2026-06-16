"""OI Analysis — per-strike, per-interval Call/Put OI interpretation table.

Mirrors the OI Pulse "OI Analysis" screen: for one strike, bucket the CE and PE
candles to N minutes and classify each side via the 4-quadrant engine, plus a
Day-High/Low break flag. See docs/SPEC/14-oi-pulse.md.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from src.data import storage
from .resample import resample_options
from .oi_interpret import classify_oi, dhl_break


def _session(day: date) -> tuple[datetime, datetime]:
    return (datetime(day.year, day.month, day.day, 9, 15),
            datetime(day.year, day.month, day.day, 15, 30))


def list_strikes(underlying: str, day_iso: str, expiry_iso: str) -> list[int]:
    day = date.fromisoformat(day_iso)
    exp = date.fromisoformat(expiry_iso)
    start, end = _session(day)
    cur = storage.db().cursor()
    try:
        rows = cur.execute(
            "SELECT DISTINCT strike FROM options_1m "
            "WHERE underlying=? AND expiry=? AND ts>=? AND ts<=? ORDER BY strike",
            [underlying.upper(), exp, start, end],
        ).fetchall()
        return [int(r[0]) for r in rows]
    finally:
        cur.close()


def expiries_on(underlying: str, day_iso: str) -> list[str]:
    """Expiries that actually traded on `day` for this underlying."""
    day = date.fromisoformat(day_iso)
    start, end = _session(day)
    cur = storage.db().cursor()
    try:
        rows = cur.execute(
            "SELECT DISTINCT expiry FROM options_1m "
            "WHERE underlying=? AND ts>=? AND ts<=? ORDER BY expiry",
            [underlying.upper(), start, end],
        ).fetchall()
        return [str(r[0]) for r in rows]
    finally:
        cur.close()


def _label(ts: datetime, interval: int) -> str:
    nxt = ts + timedelta(minutes=interval)
    return f"{ts.strftime('%H:%M')}-{nxt.strftime('%H:%M')}"


def build_oi_analysis(underlying: str, day_iso: str, expiry_iso: str,
                      strike: int, interval: int = 60,
                      mode: str = "historical") -> dict:
    underlying = underlying.upper()
    day = date.fromisoformat(day_iso)
    exp = date.fromisoformat(expiry_iso)
    strike = int(strike)
    start, end = _session(day)

    opts = storage.read_options(underlying, start, end, expiry=exp, strikes=[strike])
    if opts.is_empty():
        return {"rows": [], "underlying": underlying, "date": day_iso,
                "expiry": expiry_iso, "strike": strike, "interval": interval,
                "message": f"No option data for {underlying} {strike} on {day_iso}"}

    ro = resample_options(opts, interval).sort("ts")
    ce = {r["ts"]: r for r in ro.filter(ro["option_type"] == "CE").iter_rows(named=True)}
    pe = {r["ts"]: r for r in ro.filter(ro["option_type"] == "PE").iter_rows(named=True)}
    all_ts = sorted(set(ce) | set(pe))

    rows = []
    ce_hi = ce_lo = pe_hi = pe_lo = None
    for ts in all_ts:
        c = ce.get(ts)
        p = pe.get(ts)
        c_close = c["close"] if c else None
        p_close = p["close"] if p else None
        c_oi = (c["oi"] if c else 0) or 0
        p_oi = (p["oi"] if p else 0) or 0
        c_oi_chg = (c["oi_chg"] if c and c["oi_chg"] is not None else 0)
        p_oi_chg = (p["oi_chg"] if p and p["oi_chg"] is not None else 0)
        c_ltp_chg = (c["ltp_chg"] if c and c["ltp_chg"] is not None else 0)
        p_ltp_chg = (p["ltp_chg"] if p and p["ltp_chg"] is not None else 0)

        # running day high/low on close, for D.H/L break flag
        c_break = p_break = None
        if c_close is not None:
            ce_hi = c_close if ce_hi is None else max(ce_hi, c_close)
            ce_lo = c_close if ce_lo is None else min(ce_lo, c_close)
            c_break = dhl_break(c_close, ce_hi, ce_lo)
        if p_close is not None:
            pe_hi = p_close if pe_hi is None else max(pe_hi, p_close)
            pe_lo = p_close if pe_lo is None else min(pe_lo, p_close)
            p_break = dhl_break(p_close, pe_hi, pe_lo)

        rows.append({
            "time": _label(ts, interval),
            "call_oi": int(c_oi),
            "call_oi_chg": int(c_oi_chg),
            "call_ltp": round(float(c_close), 2) if c_close is not None else None,
            "call_ltp_chg": round(float(c_ltp_chg), 2),
            "call_interp": classify_oi(c_ltp_chg, c_oi_chg).value,
            "call_break": c_break,
            "total_oi_chg": int(c_oi_chg + p_oi_chg),
            "strike": strike,
            "put_oi": int(p_oi),
            "put_oi_chg": int(p_oi_chg),
            "put_ltp": round(float(p_close), 2) if p_close is not None else None,
            "put_ltp_chg": round(float(p_ltp_chg), 2),
            "put_interp": classify_oi(p_ltp_chg, p_oi_chg).value,
            "put_break": p_break,
        })

    rows.reverse()  # newest on top
    return {"rows": rows, "underlying": underlying, "date": day_iso,
            "expiry": expiry_iso, "strike": strike, "interval": interval,
            "mode": mode, "message": None}

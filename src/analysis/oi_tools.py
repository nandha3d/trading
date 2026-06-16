"""OI Pulse supporting tools — Statistics, Spurt, Big Movement, Trending OI,
Active Strikes. One DB read per call; all views derived from the same chain.

See docs/SPEC/14-oi-pulse.md section 5.
"""
from __future__ import annotations

from datetime import date, datetime

import polars as pl

from src.data import storage
from .resample import resample_options
from .oi_interpret import classify_oi


def _session(day: date) -> tuple[datetime, datetime]:
    return (datetime(day.year, day.month, day.day, 9, 15),
            datetime(day.year, day.month, day.day, 15, 30))


def _max_pain(strikes: list[int], ce_oi: dict, pe_oi: dict) -> int:
    best, best_pain = (strikes[0] if strikes else 0), float("inf")
    for target in strikes:
        pain = 0.0
        for s in strikes:
            if target > s:
                pain += (target - s) * ce_oi.get(s, 0)
            elif target < s:
                pain += (s - target) * pe_oi.get(s, 0)
        if pain < best_pain:
            best_pain, best = pain, target
    return best


def build_oi_tools(underlying: str, day_iso: str, expiry_iso: str,
                   interval: int = 15, top: int = 12) -> dict:
    underlying = underlying.upper()
    day = date.fromisoformat(day_iso)
    exp = date.fromisoformat(expiry_iso)
    start, end = _session(day)

    opts = storage.read_options(underlying, start, end, expiry=exp)
    if opts.is_empty():
        return {"underlying": underlying, "date": day_iso, "expiry": expiry_iso,
                "message": f"No option data for {underlying} on {day_iso}",
                "statistics": None, "spurt": [], "big_movement": [],
                "trending": None, "active_strikes": []}

    ro = resample_options(opts, interval).sort("ts")
    # collapse to per-contract day summary
    g = (ro.group_by(["strike", "option_type"])
           .agg([
               pl.col("oi").last().alias("oi_last"),
               pl.col("oi").first().alias("oi_first"),
               pl.col("oi_chg").last().alias("oi_chg_last"),
               pl.col("close").last().alias("ltp"),
               pl.col("ltp_chg").last().alias("ltp_chg_last"),
           ]))

    ce_oi: dict = {}
    pe_oi: dict = {}
    contracts = []  # flat list of per-contract dicts
    for r in g.iter_rows(named=True):
        s = int(r["strike"])
        ot = r["option_type"]
        oi_last = int(r["oi_last"] or 0)
        oi_first = int(r["oi_first"] or 0)
        day_chg = oi_last - oi_first
        rec = {
            "strike": s, "type": ot,
            "oi": oi_last,
            "oi_chg_bucket": int(r["oi_chg_last"] or 0),
            "oi_chg_day": day_chg,
            "ltp": round(float(r["ltp"]), 2) if r["ltp"] is not None else None,
            "ltp_chg": round(float(r["ltp_chg_last"] or 0), 2),
            "interp": classify_oi(r["ltp_chg_last"] or 0, r["oi_chg_last"] or 0).value,
        }
        contracts.append(rec)
        (ce_oi if ot == "CE" else pe_oi)[s] = oi_last

    strikes = sorted(set(ce_oi) | set(pe_oi))
    total_ce = sum(ce_oi.values())
    total_pe = sum(pe_oi.values())
    pcr = round(total_pe / total_ce, 3) if total_ce else None
    max_pain = _max_pain(strikes, ce_oi, pe_oi)

    # ---- Statistics: per-strike CE/PE table ----
    by_strike = {s: {"strike": s, "ce_oi": ce_oi.get(s, 0), "pe_oi": pe_oi.get(s, 0),
                     "ce_oi_chg": 0, "pe_oi_chg": 0}
                 for s in strikes}
    for c in contracts:
        d = by_strike[c["strike"]]
        d[("ce" if c["type"] == "CE" else "pe") + "_oi_chg"] = c["oi_chg_day"]
    statistics = {
        "total_ce_oi": total_ce, "total_pe_oi": total_pe,
        "pcr": pcr, "max_pain": max_pain,
        "rows": [by_strike[s] for s in strikes],
    }

    # ---- Spurt: biggest LAST-bucket OI jumps ----
    spurt = sorted(contracts, key=lambda c: abs(c["oi_chg_bucket"]), reverse=True)[:top]

    # ---- Big Movement: biggest DAY-cumulative OI change ----
    big = sorted(contracts, key=lambda c: abs(c["oi_chg_day"]), reverse=True)[:top]

    # ---- Active Strikes: most total OI (CE+PE) ----
    active = sorted(
        ({"strike": s, "ce_oi": ce_oi.get(s, 0), "pe_oi": pe_oi.get(s, 0),
          "total_oi": ce_oi.get(s, 0) + pe_oi.get(s, 0),
          "bias": "Put-heavy" if pe_oi.get(s, 0) > ce_oi.get(s, 0) else "Call-heavy"}
         for s in strikes),
        key=lambda x: x["total_oi"], reverse=True)[:top]

    # ---- Trending OI: net writing direction ----
    ce_day_chg = sum(c["oi_chg_day"] for c in contracts if c["type"] == "CE")
    pe_day_chg = sum(c["oi_chg_day"] for c in contracts if c["type"] == "PE")
    # Call writing (CE OI up) = bearish; Put writing (PE OI up) = bullish
    score = pe_day_chg - ce_day_chg
    denom = abs(pe_day_chg) + abs(ce_day_chg)
    bull_pct = round(50 + 50 * score / denom, 1) if denom else 50.0
    verdict = ("Bullish" if bull_pct > 55 else
               "Bearish" if bull_pct < 45 else "Neutral")
    trending = {
        "ce_oi_chg": ce_day_chg, "pe_oi_chg": pe_day_chg,
        "bull_pct": bull_pct, "bear_pct": round(100 - bull_pct, 1),
        "verdict": verdict,
    }

    return {"underlying": underlying, "date": day_iso, "expiry": expiry_iso,
            "interval": interval, "message": None,
            "statistics": statistics, "spurt": spurt, "big_movement": big,
            "trending": trending, "active_strikes": active}

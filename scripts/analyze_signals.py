"""Indicator / OI conditional strategies — entry & exit on signals, not a fixed clock.

Tests whether technical + OI signals cut the losing days of the time-based
straddle. Each strategy is simulated per day on 1-min spot + 5-min indicators,
entering when a condition fires (any time) and exiting on the opposite signal,
a stop, or end of day. Reported per expiry era.

Strategies:
  BASE_STRAD   sell ATM straddle 09:21, per-leg SL 88%           (time baseline)
  VWAP_STOP    BASE_STRAD + cut BOTH legs if spot runs >0.45% from session VWAP
               (an indicator trend-escape exit -> meant to reduce loss days)
  ST_DIR       Supertrend(10,3) on 5-min; first flip -> buy that side (CE up/PE down),
               exit on opposite flip / EOD, SL 50%                (directional)
  EMA_DIR      EMA9>EMA21 cross on 5-min -> buy CE; cross down -> buy PE; SL 50%
  RSI_REV      5-min RSI14: >70 sell CE, <30 sell PE (credit reversion), SL 88%, exit EOD
  OI_DIR       ATM OI buildup: strong CE-writing -> buy PE; strong PE-writing -> buy CE
               (sell-side pressure = price pushed the other way), SL 50%

Outputs (data/):
  signals_trades.csv , signals_report.html

Usage:
  python scripts/analyze_signals.py NIFTY 2023-01-02 2026-04-13
"""
from __future__ import annotations

import csv
import sys
import time as _time
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest import indicators as ind  # noqa: E402
from src.backtest.costs import CostModel  # noqa: E402
from src.backtest.engine import pick_expiry  # noqa: E402
from src.backtest.strategy import CONTRACT_SPECS  # noqa: E402
from src.data import storage  # noqa: E402

STRATS = ["BASE_STRAD", "VWAP_STOP", "ST_DIR", "EMA_DIR", "RSI_REV", "OI_DIR", "COMBO"]
EXPIRY_SWITCH = date(2025, 9, 1)
ENTRY = time(9, 21)
EXIT = time(14, 55)
SIG_START = time(9, 30)     # don't act on the first 15 min (let indicators warm)
SELL_SL = 88.0
BUY_SL = 50.0
VWAP_BAND = 0.0045          # 0.45% from VWAP = trend escape


def _minutes(day, t0, t1):
    cur, end, out = datetime.combine(day, t0), datetime.combine(day, t1), []
    while cur <= end:
        out.append(cur); cur += timedelta(minutes=1)
    return out


def _ffill(pm, grid):
    out = np.empty(len(grid)); last = np.nan
    for i, m in enumerate(grid):
        v = pm.get(m)
        if v is not None:
            last = v
        out[i] = last
    return out


def sell_exit_idx(a, entry, sl):
    thr = entry * (1 + sl / 100.0)
    rm = np.maximum.accumulate(a)
    hit = int(np.searchsorted(rm, thr, side="left"))
    return (hit, float(a[hit])) if hit < a.size else (a.size - 1, float(a[-1]))


def buy_exit_idx(a, entry, sl):
    thr = entry * (1 - sl / 100.0)
    rm = np.minimum.accumulate(a)
    hit = int(np.searchsorted(-rm, -thr, side="left"))
    return (hit, float(a[hit])) if hit < a.size else (a.size - 1, float(a[-1]))


def main():
    av = sys.argv[1:]
    u = av[0] if len(av) > 0 else "NIFTY"
    start = date.fromisoformat(av[1]) if len(av) > 1 else date(2023, 1, 2)
    end = date.fromisoformat(av[2]) if len(av) > 2 else date(2026, 4, 13)
    step = CONTRACT_SPECS[u]["strike_step"]; qty = CONTRACT_SPECS[u]["lot_size"]
    costs = CostModel()

    expiries = storage.list_expiries(u)
    days = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            e = pick_expiry(expiries, d, 0)
            if e:
                days.append((d, e))
        d = date.fromordinal(d.toordinal() + 1)
    by_month = defaultdict(list)
    for dd, ee in days:
        by_month[(dd.year, dd.month)].append((dd, ee))

    rows = []
    t0 = _time.time()
    cur = storage.db().cursor()
    try:
        for _k, md in sorted(by_month.items()):
            c0 = datetime.combine(min(x for x, _ in md), time(9, 15))
            c1 = datetime.combine(max(x for x, _ in md), time(15, 30))
            sdf = cur.execute("SELECT ts,open,high,low,close,volume FROM spot_1m WHERE underlying=? AND ts>=? AND ts<=? ORDER BY ts", [u, c0, c1]).pl()
            odf = cur.execute("SELECT ts,strike,option_type,close,oi,expiry FROM options_1m WHERE underlying=? AND ts>=? AND ts<=?", [u, c0, c1]).pl()
            if sdf.is_empty() or odf.is_empty():
                continue
            sby = {p["_d"][0]: p.drop("_d") for p in sdf.with_columns(pl.col("ts").dt.date().alias("_d")).partition_by("_d")}
            oby = {(p["_d"][0], p["expiry"][0]): p.drop("_d") for p in odf.with_columns(pl.col("ts").dt.date().alias("_d")).partition_by(["_d", "expiry"])}

            for day, exp in md:
                sd = sby.get(day); od = oby.get((day, exp))
                if sd is None or od is None or sd.is_empty() or od.is_empty():
                    continue
                row = _one_day(day, exp, sd, od, step, qty, costs)
                if row:
                    rows.append(row)
    finally:
        cur.close()
    secs = round(_time.time() - t0, 1)
    print(f"{len(rows)} days, {len(STRATS)} strategies in {secs}s")
    if not rows:
        print("no data"); return

    out = Path("data"); out.mkdir(exist_ok=True)
    cp = out / "signals_trades.csv"
    with cp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print("wrote", cp)
    (out / "signals_report.html").write_text(build(u, start, end, secs, rows), encoding="utf-8")
    print("wrote", out / "signals_report.html")

    for era in ["Thu-era", "Tue-era"]:
        er = [r for r in rows if r["era"] == era]
        if not er:
            continue
        print(f"== {era} ({len(er)} days) ==")
        for s in STRATS:
            a = _agg([float(r[s]) for r in er if r[s] != ""])
            print(f"  {s:11} net {a['net']:>10,.0f}  win {a['win']:>3}%  maxDD {a['dd']:>9,.0f}  lossSum {a['down']:>10,.0f}  n {a['n']}")

    print("== Monday directional (OI+ST+VWAP confluence) — 20% vs 50% stop ==")
    for era in ["Thu-era", "Tue-era"]:
        mr = [r for r in rows if r["era"] == era and r["weekday"] == "Mon"]
        if not mr:
            continue
        a20 = _agg([float(r["mon20"]) for r in mr if r["mon20"] != ""])
        a50 = _agg([float(r["mon50"]) for r in mr if r["mon50"] != ""])
        print(f"  {era}  20%SL net {a20['net']:>8,.0f} win {a20['win']:>3}% maxDD {a20['dd']:>8,.0f} n {a20['n']}"
              f"  |  50%SL net {a50['net']:>8,.0f} win {a50['win']:>3}% maxDD {a50['dd']:>8,.0f} n {a50['n']}")


def _one_day(day, exp, sd, od, step, qty, costs):
    grid = _minutes(day, time(9, 15), EXIT)
    gidx = {m: i for i, m in enumerate(grid)}
    ge = gidx.get(datetime.combine(day, ENTRY))
    if ge is None:
        return None
    sd = sd.sort("ts")
    spm = {r["ts"].replace(second=0, microsecond=0): r["close"] for r in sd.select(["ts", "close"]).iter_rows(named=True)}
    spot = _ffill(spm, grid)
    if not np.isfinite(spot[ge]):
        return None
    espot = spot[ge]
    atm = int(round(espot / step) * step)

    # session "mean price" line, aligned to grid. Index spot has NO volume, so
    # fall back to equal-weight typical price (anchored cumulative average).
    vwap_pm = {}
    cum_tpv = 0.0; cum_w = 0.0
    for r in sd.select(["ts", "high", "low", "close", "volume"]).iter_rows(named=True):
        v = r["volume"] or 0
        w = v if v > 0 else 1.0          # no volume on indices -> equal weight
        tp = ((r["high"] or r["close"]) + (r["low"] or r["close"]) + r["close"]) / 3.0
        cum_tpv += tp * w; cum_w += w
        if cum_w > 0:
            vwap_pm[r["ts"].replace(second=0, microsecond=0)] = cum_tpv / cum_w
    vwap = _ffill(vwap_pm, grid)

    # 5-min resample for indicators
    five = (sd.group_by_dynamic("ts", every="5m", closed="left", label="left")
              .agg(o=pl.col("open").first(), h=pl.col("high").max(),
                   l=pl.col("low").min(), c=pl.col("close").last(), v=pl.col("volume").sum())
              .sort("ts"))
    ftimes = list(five["ts"].to_list())
    fc = five["c"]
    _, st_dir = ind.compute_supertrend(five["h"], five["l"], five["c"], 10, 3.0)
    sdir = st_dir.to_list()
    ema9 = ind.compute_ema(fc, 9).to_list()
    ema21 = ind.compute_ema(fc, 21).to_list()
    rsi = ind.compute_rsi(fc, 14).to_list()

    # option price arrays + OI
    opm = defaultdict(dict)
    oi_at = {}
    for r in od.select(["strike", "option_type", "ts", "close", "oi"]).iter_rows(named=True):
        m = r["ts"].replace(second=0, microsecond=0)
        opm[(r["strike"], r["option_type"])][m] = r["close"]
        oi_at.setdefault((r["strike"], r["option_type"]), {})[m] = r["oi"]
    cache = {}

    def arr(strike, ot, _opm=opm, _cache=cache, _grid=grid):
        key = (strike, ot)
        if key not in _cache:
            pm = _opm.get(key)
            _cache[key] = _ffill(pm, _grid) if pm else None
        return _cache[key]

    res = {s: None for s in STRATS}
    res["BASE_STRAD"] = _straddle(arr, atm, ge, qty, costs, trend_stop=None)
    res["VWAP_STOP"] = _straddle(arr, atm, ge, qty, costs, trend_stop=(spot, vwap))

    def grid_idx_for_bar(i):
        end_t = (ftimes[i + 1] if i + 1 < len(ftimes) else ftimes[i] + timedelta(minutes=5))
        return gidx.get(end_t.replace(second=0, microsecond=0))

    sig_start_idx = gidx.get(datetime.combine(day, SIG_START), 0)

    sig_after = datetime.combine(day, SIG_START)
    res["ST_DIR"] = _dir_from_signal(_first_flip(sdir, ftimes, sig_after), grid_idx_for_bar, arr, spot, step, qty, costs, sig_start_idx)
    res["EMA_DIR"] = _dir_from_signal(_first_ema_cross(ema9, ema21, ftimes, sig_after), grid_idx_for_bar, arr, spot, step, qty, costs, sig_start_idx)
    res["RSI_REV"] = _rsi_credit(rsi, grid_idx_for_bar, arr, spot, step, qty, costs, sig_start_idx)
    res["OI_DIR"] = _oi_dir(oi_at, atm, grid, gidx, arr, spot, qty, costs, ge)

    oi_vote = _oi_vote(oi_at, atm, grid, gidx, ge)
    res["COMBO"] = _combo(sdir, ftimes, sig_after, grid_idx_for_bar, arr, spot, vwap,
                          step, qty, costs, sig_start_idx, oi_vote, atm, ge)

    era = "Thu-era" if day < EXPIRY_SWITCH else "Tue-era"
    out = {"date": day.isoformat(), "weekday": day.strftime("%a"), "era": era,
           "dte": max((exp - day).days, 0)}
    for s in STRATS:
        out[s] = "" if res[s] is None else round(res[s], 1)
    # Monday directional: does a tight 20% stop beat 50%? (confluence-picked side)
    if day.weekday() == 0:
        m20 = _mon_dir(sdir, ftimes, sig_after, grid_idx_for_bar, arr, spot, vwap,
                       step, qty, costs, sig_start_idx, oi_vote, 20.0)
        m50 = _mon_dir(sdir, ftimes, sig_after, grid_idx_for_bar, arr, spot, vwap,
                       step, qty, costs, sig_start_idx, oi_vote, 50.0)
        out["mon20"] = "" if m20 is None else round(m20, 1)
        out["mon50"] = "" if m50 is None else round(m50, 1)
    else:
        out["mon20"] = ""; out["mon50"] = ""
    return out


def _straddle(arr, atm, ge, qty, costs, trend_stop):
    ce, pe = arr(atm, "CE"), arr(atm, "PE")
    if ce is None or pe is None or not (np.isfinite(ce[ge]) and np.isfinite(pe[ge]) and ce[ge] > 0 and pe[ge] > 0):
        return None
    cx, px = ce[ge:], pe[ge:]
    ci, cexit = sell_exit_idx(cx, cx[0], SELL_SL)
    pi, pexit = sell_exit_idx(px, px[0], SELL_SL)
    if trend_stop is not None:
        spot, vwap = trend_stop
        ss, vv = spot[ge:], vwap[ge:]
        tstop = None
        for j in range(len(ss)):
            if np.isfinite(ss[j]) and np.isfinite(vv[j]) and vv[j] > 0 and abs(ss[j] - vv[j]) / vv[j] > VWAP_BAND:
                tstop = j; break
        if tstop is not None:
            if tstop < ci:
                cexit = float(cx[tstop])
            if tstop < pi:
                pexit = float(px[tstop])
    return (cx[0] - cexit) * qty + (px[0] - pexit) * qty - costs.leg_cost(cx[0], cexit, qty) - costs.leg_cost(px[0], pexit, qty)


def _bar_end(ftimes, i):
    return ftimes[i + 1] if i + 1 < len(ftimes) else ftimes[i] + timedelta(minutes=5)


def _first_flip(sdir, ftimes, after):
    for i in range(1, len(sdir)):
        if _bar_end(ftimes, i) < after:
            continue
        if sdir[i] is not None and sdir[i - 1] is not None and sdir[i] != sdir[i - 1]:
            return (i, "CE" if sdir[i] == 1 else "PE")
    return None


def _first_ema_cross(e9, e21, ftimes, after):
    for i in range(1, len(e9)):
        if _bar_end(ftimes, i) < after:
            continue
        if None in (e9[i], e21[i], e9[i - 1], e21[i - 1]):
            continue
        if e9[i - 1] <= e21[i - 1] and e9[i] > e21[i]:
            return (i, "CE")
        if e9[i - 1] >= e21[i - 1] and e9[i] < e21[i]:
            return (i, "PE")
    return None


def _dir_from_signal(sig, grid_idx_for_bar, arr, spot, step, qty, costs, sig_start_idx):
    if not sig:
        return None
    bi, side = sig
    ei = grid_idx_for_bar(bi)
    if ei is None or ei < sig_start_idx or not np.isfinite(spot[ei]):
        return None
    k = int(round(spot[ei] / step) * step)
    leg = arr(k, side)
    if leg is None or not np.isfinite(leg[ei]) or leg[ei] <= 0:
        return None
    seg = leg[ei:]
    _, ex = buy_exit_idx(seg, seg[0], BUY_SL)
    return (ex - seg[0]) * qty - costs.leg_cost(seg[0], ex, qty)


def _rsi_credit(rsi, grid_idx_for_bar, arr, spot, step, qty, costs, sig_start_idx):
    for i in range(len(rsi)):
        if rsi[i] is None:
            continue
        side = "CE" if rsi[i] > 70 else "PE" if rsi[i] < 30 else None
        if side is None:
            continue
        ei = grid_idx_for_bar(i)
        if ei is None or ei < sig_start_idx or not np.isfinite(spot[ei]):
            continue
        k = int(round(spot[ei] / step) * step)
        leg = arr(k, side)
        if leg is None or not np.isfinite(leg[ei]) or leg[ei] <= 0:
            continue
        seg = leg[ei:]
        _, ex = sell_exit_idx(seg, seg[0], SELL_SL)
        return (seg[0] - ex) * qty - costs.leg_cost(seg[0], ex, qty)
    return None


def _oi_dir(oi_at, atm, grid, gidx, arr, spot, qty, costs, ge):
    open_m = grid[0]; ent_m = grid[ge]
    def oi(otype):
        d = oi_at.get((atm, otype), {})
        return (d.get(ent_m) or 0), (d.get(open_m) or 0)
    ce_now, ce_op = oi("CE"); pe_now, pe_op = oi("PE")
    ce_chg = ce_now - ce_op; pe_chg = pe_now - pe_op
    if max(ce_chg, pe_chg) <= 0:
        return None
    if ce_chg > pe_chg * 1.3:
        side = "PE"   # heavy CE writing = resistance/bearish -> buy put
    elif pe_chg > ce_chg * 1.3:
        side = "CE"   # heavy PE writing = support/bullish -> buy call
    else:
        return None
    leg = arr(atm, side)
    if leg is None or not np.isfinite(leg[ge]) or leg[ge] <= 0:
        return None
    seg = leg[ge:]
    _, ex = buy_exit_idx(seg, seg[0], BUY_SL)
    return (ex - seg[0]) * qty - costs.leg_cost(seg[0], ex, qty)


def _oi_vote(oi_at, atm, grid, gidx, ge):
    """+1 bullish (PE writing -> buy CE), -1 bearish (CE writing -> buy PE), 0 flat."""
    open_m = grid[0]; ent_m = grid[ge]
    def chg(ot):
        d = oi_at.get((atm, ot), {})
        return (d.get(ent_m) or 0) - (d.get(open_m) or 0)
    ce_chg = chg("CE"); pe_chg = chg("PE")
    if max(ce_chg, pe_chg) <= 0:
        return 0
    if ce_chg > pe_chg * 1.3:
        return -1
    if pe_chg > ce_chg * 1.3:
        return 1
    return 0


def _votes(sdir, i, spot, vwap, ei, oi_vote):
    """Combined direction score: Supertrend + VWAP position + OI buildup."""
    st = 1 if sdir[i] == 1 else -1 if sdir[i] == -1 else 0
    dev = (spot[ei] - vwap[ei]) / vwap[ei]
    vw = 1 if dev > VWAP_BAND else -1 if dev < -VWAP_BAND else 0
    return st + vw + oi_vote


def _first_confluence(sdir, ftimes, after, grid_idx_for_bar, spot, vwap, sig_start_idx, oi_vote):
    """First 5-min bar (>= SIG_START) where >=2 of {ST,VWAP,OI} agree on a side."""
    for i in range(1, len(sdir)):
        if _bar_end(ftimes, i) < after:
            continue
        ei = grid_idx_for_bar(i)
        if ei is None or ei < sig_start_idx or not np.isfinite(spot[ei]) or not np.isfinite(vwap[ei]) or vwap[ei] <= 0:
            continue
        tot = _votes(sdir, i, spot, vwap, ei, oi_vote)
        if tot >= 2 or tot <= -2:
            return (ei, "CE" if tot > 0 else "PE")
    return None


def _combo(sdir, ftimes, after, grid_idx_for_bar, arr, spot, vwap, step, qty, costs, sig_start_idx, oi_vote, atm, ge):
    """Adaptive: on indicator confluence buy the trend side (50% stop); if no
    confluence all day, fall back to selling the straddle with a VWAP trend-stop."""
    pick = _first_confluence(sdir, ftimes, after, grid_idx_for_bar, spot, vwap, sig_start_idx, oi_vote)
    if pick is not None:
        ei, side = pick
        k = int(round(spot[ei] / step) * step)
        leg = arr(k, side)
        if leg is not None and np.isfinite(leg[ei]) and leg[ei] > 0:
            seg = leg[ei:]
            _, ex = buy_exit_idx(seg, seg[0], BUY_SL)
            return (ex - seg[0]) * qty - costs.leg_cost(seg[0], ex, qty)
    return _straddle(arr, atm, ge, qty, costs, trend_stop=(spot, vwap))


def _mon_dir(sdir, ftimes, after, grid_idx_for_bar, arr, spot, vwap, step, qty, costs, sig_start_idx, oi_vote, sl):
    """Monday directional buy at the given stop %: confluence side, else first
    Supertrend flip. Used to test whether a tight 20% stop helps on Mondays."""
    pick = _first_confluence(sdir, ftimes, after, grid_idx_for_bar, spot, vwap, sig_start_idx, oi_vote)
    if pick is None:
        fl = _first_flip(sdir, ftimes, after)
        if fl:
            bi, side = fl; ei = grid_idx_for_bar(bi)
            if ei is not None and ei >= sig_start_idx and np.isfinite(spot[ei]):
                pick = (ei, side)
    if pick is None:
        return None
    ei, side = pick
    k = int(round(spot[ei] / step) * step)
    leg = arr(k, side)
    if leg is None or not np.isfinite(leg[ei]) or leg[ei] <= 0:
        return None
    seg = leg[ei:]
    _, ex = buy_exit_idx(seg, seg[0], sl)
    return (ex - seg[0]) * qty - costs.leg_cost(seg[0], ex, qty)


def _agg(vals):
    n = len(vals)
    if not n:
        return dict(n=0, net=0, avg=0, win=0, dd=0, down=0)
    eq = np.cumsum(vals); dd = float((np.maximum.accumulate(eq) - eq).max())
    down = sum(v for v in vals if v < 0)
    return dict(n=n, net=round(sum(vals)), avg=round(sum(vals) / n),
                win=round(sum(1 for v in vals if v > 0) / n * 100), dd=round(dd), down=round(down))


def money(n):
    n = float(n); s = "-" if n < 0 else ""; a = abs(n)
    if a >= 1e5: return f"{s}₹{a/1e5:.2f}L"
    if a >= 1e3: return f"{s}₹{a/1e3:.1f}K"
    return f"{s}₹{a:.0f}"


def cls(n):
    return "pos" if float(n) >= 0 else "neg"


NAMES = {"BASE_STRAD": "Straddle (time, baseline)", "VWAP_STOP": "Straddle + VWAP trend-stop",
         "ST_DIR": "Supertrend directional", "EMA_DIR": "EMA 9/21 cross directional",
         "RSI_REV": "RSI reversion (credit)", "OI_DIR": "OI-buildup directional",
         "COMBO": "COMBO: OI+Supertrend+VWAP confluence"}


def build(u, start, end, secs, rows):
    sections = ""
    for era in ["Thu-era", "Tue-era"]:
        er = [r for r in rows if r["era"] == era]
        if not er:
            continue
        base = _agg([float(r["BASE_STRAD"]) for r in er if r["BASE_STRAD"] != ""])
        mx = max(abs(_agg([float(r[s]) for r in er if r[s] != ""])["net"]) for s in STRATS) or 1
        body = ""
        for s in STRATS:
            a = _agg([float(r[s]) for r in er if r[s] != ""])
            w = int(abs(a["net"]) / mx * 100)
            ddcut = base["dd"] - a["dd"]
            body += (f"<tr><td class='lbl'>{NAMES[s]}</td>"
                     f"<td class='{cls(a['net'])}'>{money(a['net'])}<div class='bw'><div class='b {cls(a['net'])}b' style='width:{w}%'></div></div></td>"
                     f"<td>{a['win']}%</td><td class='neg'>{money(a['down'])}</td>"
                     f"<td>{money(a['dd'])}</td><td class='{cls(ddcut)}'>{money(ddcut)}</td><td>{a['n']}</td></tr>")
        lab = "Thursday-expiry era (to 31 Aug 2025)" if era == "Thu-era" else "Tuesday-expiry era (from 1 Sep 2025)"
        sections += (f"<h2>{lab} · {len(er)} days</h2><div class='card'><table>"
                     "<tr><th>Strategy</th><th>Net</th><th>Win</th><th>Loss-day sum</th><th>Max DD</th><th>DD cut vs base</th><th>Days</th></tr>"
                     f"{body}</table><p class='muted'>\"Loss-day sum\" = total of all losing days (closer to zero = fewer/softer losses). "
                     "\"DD cut vs base\" = how much smaller the worst drawdown is than the plain straddle (green = improvement).</p></div>")
    return _PAGE.format(u=u, start=start, end=end, secs=secs, n=len(rows),
                        gen=datetime.now().strftime("%d %b %Y, %H:%M"), sections=sections)


_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Indicator / OI Signal Strategies</title>
<style>
 :root{{--bg:#0b0f17;--card:#111827;--line:#1f2937;--mut:#9ca3af;--pos:#36c660;--neg:#ef4444;--blue:#3b82f6}}
 body{{background:var(--bg);color:#e5e7eb;font:15px/1.6 system-ui,Segoe UI,Arial;margin:0}}
 .wrap{{max-width:900px;margin:0 auto;padding:28px 20px 60px}}
 h1{{font-size:24px;margin:0 0 6px}} h2{{font-size:18px;margin:28px 0 10px;display:flex;gap:8px;align-items:center}}
 h2:before{{content:'';width:5px;height:18px;background:var(--blue);border-radius:3px}}
 h3{{font-size:15px;margin:0 0 6px}} .sub{{color:var(--mut);margin-bottom:14px}} .muted{{color:var(--mut);font-size:12.5px}}
 .card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 18px;margin:10px 0}}
 table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{padding:7px 9px;text-align:right;border-bottom:1px solid var(--line)}}
 th{{color:var(--mut)}} td.lbl,th:first-child{{text-align:left}} .pos{{color:var(--pos)}} .neg{{color:var(--neg)}}
 .bw{{height:4px;background:#1f2937;border-radius:3px;margin-top:4px;max-width:150px}} .b{{height:4px;border-radius:3px}} .posb{{background:var(--pos)}} .negb{{background:var(--neg)}}
 b{{color:#fff}} ul{{margin:6px 0 0;padding-left:20px}}
</style></head><body><div class="wrap">
<h1>Indicator &amp; OI Signal Strategies</h1>
<div class="sub">{u} · {start} -> {end} · {n} days · {gen} · computed {secs}s · split by expiry era</div>
<div class="card"><p>Goal: use signals (Supertrend, EMA, RSI, VWAP, OI buildup) for <b>condition-based entry/exit</b> instead of a fixed clock, and see what <b>reduces the losing days</b> of the plain straddle. The straddle also gets a VWAP "trend-stop" exit variant. Directional strategies enter when their signal fires and exit on the opposite signal, a stop, or end of day.</p></div>
{sections}
<div class="card"><h3>Strategy meanings</h3><ul>
 <li><b>Straddle (baseline)</b> - sell ATM Call+Put at 9:21, 88% stop each. Reference.</li>
 <li><b>Straddle + VWAP trend-stop</b> - same, but if price runs &gt;0.45% from the day's VWAP (a trend starting), cut both legs early.</li>
 <li><b>Supertrend directional</b> - on the first Supertrend flip, buy the trend side (Call up / Put down), 50% stop.</li>
 <li><b>EMA 9/21 cross</b> - buy Call on bullish cross, Put on bearish cross.</li>
 <li><b>RSI reversion</b> - RSI&gt;70 sell Call, RSI&lt;30 sell Put (fade the extreme), 88% stop.</li>
 <li><b>OI-buildup directional</b> - heavy Call-writing (resistance) -&gt; buy Put; heavy Put-writing (support) -&gt; buy Call.</li>
 <li><b>COMBO (OI+Supertrend+VWAP)</b> - score all three; if &ge;2 agree on a side, buy that side (50% stop). If they never agree, sell the straddle with a VWAP trend-stop. One adaptive rule: trade direction only on confluence, else collect premium safely.</li>
</ul></div>
<p class="muted">Past results are not a promise of future returns. Costs &amp; slippage included; live fills may differ.</p>
</div></body></html>"""


if __name__ == "__main__":
    main()

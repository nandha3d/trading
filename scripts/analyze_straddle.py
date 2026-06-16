"""Deep multi-factor analysis of the ATM short-straddle 'best' config.

For the winning grid combo (entry 09:21, exit 14:55, per-leg SL 88%), this:
  * rebuilds every trading day's straddle with full entry greeks + IV,
  * runs SL variants  -> No-SL / SL88 / SL88+re-entry / Trailing-SL (20/30/40/50%),
  * buckets net P&L by IV, VIX regime, DTE, weekday, entry theta, net delta skew,
  * reports correlations of P&L vs IV / theta / vega.

Outputs (data/):
  straddle_trades.csv      -> per-trade rows (all variants + greeks)
  straddle_analysis.html   -> self-contained report (tables + bars)

Usage:
  python scripts/analyze_straddle.py NIFTY 2023-01-02 2026-04-13 09:21 14:55 88
"""
from __future__ import annotations

import csv
import statistics as st
import sys
import time as _time
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest import greeks  # noqa: E402
from src.backtest.costs import CostModel  # noqa: E402
from src.backtest.engine import pick_expiry  # noqa: E402
from src.backtest.strategy import CONTRACT_SPECS  # noqa: E402
from src.data import storage  # noqa: E402

try:
    from py_vollib.black_scholes.greeks.analytical import theta as _bs_theta, gamma as _bs_gamma, vega as _bs_vega
except Exception:  # pragma: no cover
    _bs_theta = _bs_gamma = _bs_vega = None

R = greeks.RISK_FREE
TRAILS = [20.0, 30.0, 40.0, 50.0]


def _t(s: str) -> time:
    h, m = map(int, s.split(":"))
    return time(h, m)


def _minutes(day: date, t0: time, t1: time) -> list[datetime]:
    cur, end, out = datetime.combine(day, t0), datetime.combine(day, t1), []
    while cur <= end:
        out.append(cur); cur += timedelta(minutes=1)
    return out


def _ffill(pm: dict, grid: list[datetime]) -> np.ndarray:
    out = np.empty(len(grid)); last = np.nan
    for i, m in enumerate(grid):
        v = pm.get(m)
        if v is not None:
            last = v
        out[i] = last
    return out


# ---- per-leg SL simulations on a price suffix (SELL leg) ----

def sl_once(a: np.ndarray, entry: float, sl: float) -> tuple[float, str]:
    """First-touch SL; returns (exit_price, reason)."""
    thr = entry * (1 + sl / 100.0)
    rm = np.maximum.accumulate(a)
    hit = int(np.searchsorted(rm, thr, side="left"))
    if hit < a.size:
        return float(a[hit]), "STOPLOSS"
    return float(a[-1]), "TIME"


def sl_reentry(a: np.ndarray, sl: float, costs: CostModel, qty: int) -> tuple[float, int]:
    """SL with re-entry of a fresh same-strike SELL each time it stops. Net pnl, n_fills."""
    i, n, pnl, fills = 0, a.size, 0.0, 0
    while i < n:
        entry = a[i]
        if not np.isfinite(entry) or entry <= 0:
            break
        seg = a[i:]
        thr = entry * (1 + sl / 100.0)
        rm = np.maximum.accumulate(seg)
        rel = int(np.searchsorted(rm, thr, side="left"))
        fills += 1
        if rel < seg.size:
            exit_p = float(seg[rel]); pnl += (entry - exit_p) * qty - costs.leg_cost(entry, exit_p, qty)
            i = i + rel + 1
        else:
            exit_p = float(seg[-1]); pnl += (entry - exit_p) * qty - costs.leg_cost(entry, exit_p, qty)
            break
    return pnl, fills


def trail_exit(a: np.ndarray, entry: float, trail: float) -> float:
    """Trailing SL for a SELL leg: exit when give-back from peak profit exceeds
    trail% of entry premium. peak favorable = entry - min(mark so far)."""
    step = entry * trail / 100.0
    peak_fav = 0.0
    for mark in a:
        if not np.isfinite(mark):
            continue
        fav = entry - mark
        if fav > peak_fav:
            peak_fav = fav
        if peak_fav > 0 and fav <= peak_fav - step:
            return float(mark)
    return float(a[-1])


def main() -> None:
    av = sys.argv[1:]
    u = av[0] if len(av) > 0 else "NIFTY"
    start = date.fromisoformat(av[1]) if len(av) > 1 else date(2023, 1, 2)
    end = date.fromisoformat(av[2]) if len(av) > 2 else date(2026, 4, 13)
    entry_t = _t(av[3]) if len(av) > 3 else time(9, 21)
    exit_t = _t(av[4]) if len(av) > 4 else time(14, 55)
    sl = float(av[5]) if len(av) > 5 else 88.0

    cspec = CONTRACT_SPECS[u]; step = cspec["strike_step"]; qty = cspec["lot_size"]
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

    by_month: dict = {}
    for dd, ee in days:
        by_month.setdefault((dd.year, dd.month), []).append((dd, ee))

    rows = []  # per-trade dicts
    t0 = _time.time()
    cur = storage.db().cursor()
    try:
        for _key, mdays in sorted(by_month.items()):
            c0 = datetime.combine(min(x for x, _ in mdays), time(9, 15))
            c1 = datetime.combine(max(x for x, _ in mdays), time(15, 30))
            sdf = cur.execute("SELECT ts,close FROM spot_1m WHERE underlying=? AND ts>=? AND ts<=? ORDER BY ts",
                              [u, c0, c1]).pl()
            odf = cur.execute("SELECT ts,strike,option_type,close,expiry FROM options_1m WHERE underlying=? AND ts>=? AND ts<=?",
                              [u, c0, c1]).pl()
            if sdf.is_empty() or odf.is_empty():
                continue
            spot_by = {p["_d"][0]: p.drop("_d") for p in sdf.with_columns(pl.col("ts").dt.date().alias("_d")).partition_by("_d")}
            opt_by = {(p["_d"][0], p["expiry"][0]): p.drop("_d") for p in odf.with_columns(pl.col("ts").dt.date().alias("_d")).partition_by(["_d", "expiry"])}

            for day, exp in mdays:
                sd = spot_by.get(day); od = opt_by.get((day, exp))
                if sd is None or od is None or sd.is_empty() or od.is_empty():
                    continue
                grid = _minutes(day, time(9, 15), exit_t)
                gidx = {m: i for i, m in enumerate(grid)}
                ge = gidx.get(datetime.combine(day, entry_t))
                if ge is None:
                    continue
                spm = {r["ts"].replace(second=0, microsecond=0): r["close"] for r in sd.select(["ts", "close"]).iter_rows(named=True)}
                espot = _ffill(spm, grid)[ge]
                if not np.isfinite(espot):
                    continue
                atm = int(round(espot / step) * step)

                opm = {}
                for r in od.select(["strike", "option_type", "ts", "close"]).iter_rows(named=True):
                    opm.setdefault((r["strike"], r["option_type"]), {})[r["ts"].replace(second=0, microsecond=0)] = r["close"]
                ce_pm, pe_pm = opm.get((atm, "CE")), opm.get((atm, "PE"))
                if not ce_pm or not pe_pm:
                    continue
                ce = _ffill(ce_pm, grid)[ge:]
                pe = _ffill(pe_pm, grid)[ge:]
                ce0, pe0 = ce[0], pe[0]
                if not (np.isfinite(ce0) and np.isfinite(pe0) and ce0 > 0 and pe0 > 0):
                    continue

                edt = datetime.combine(day, entry_t)
                ty = greeks.years_to_expiry(edt, exp)
                dte = max((exp - day).days, 0)
                ce_iv = greeks.iv(ce0, espot, atm, ty, "CE") or 0.0
                pe_iv = greeks.iv(pe0, espot, atm, ty, "PE") or 0.0
                iv_avg = (ce_iv + pe_iv) / 2 * 100 if (ce_iv and pe_iv) else (ce_iv or pe_iv) * 100
                ce_d = greeks.delta(ce0, espot, atm, ty, "CE") or 0.0
                pe_d = greeks.delta(pe0, espot, atm, ty, "PE") or 0.0

                def g(fn, flag, iv):
                    if fn is None or iv <= 0:
                        return 0.0
                    try:
                        return float(fn(flag, espot, atm, ty, R, iv))
                    except Exception:
                        return 0.0
                # collected greeks (seller): theta positive = we earn
                net_theta = -(g(_bs_theta, "c", ce_iv) + g(_bs_theta, "p", pe_iv)) * qty
                net_vega = (g(_bs_vega, "c", ce_iv) + g(_bs_vega, "p", pe_iv)) * qty
                net_gamma = (g(_bs_gamma, "c", ce_iv) + g(_bs_gamma, "p", pe_iv)) * qty
                net_delta = (ce_d + pe_d) * qty

                # ---- variants ----
                nosl = ((ce0 - ce[-1]) + (pe0 - pe[-1])) * qty - costs.leg_cost(ce0, ce[-1], qty) - costs.leg_cost(pe0, pe[-1], qty)
                cex, crsn = sl_once(ce, ce0, sl); pex, prsn = sl_once(pe, pe0, sl)
                base = ((ce0 - cex) + (pe0 - pex)) * qty - costs.leg_cost(ce0, cex, qty) - costs.leg_cost(pe0, pex, qty)
                base_rsn = "STOPLOSS" if "STOPLOSS" in (crsn, prsn) else "TIME"
                rp_ce, f_ce = sl_reentry(ce, sl, costs, qty)
                rp_pe, f_pe = sl_reentry(pe, sl, costs, qty)
                reentry = rp_ce + rp_pe
                trails = {}
                for tr in TRAILS:
                    tcex = trail_exit(ce, ce0, tr); tpex = trail_exit(pe, pe0, tr)
                    trails[tr] = ((ce0 - tcex) + (pe0 - tpex)) * qty - costs.leg_cost(ce0, tcex, qty) - costs.leg_cost(pe0, tpex, qty)

                rows.append({
                    "date": day.isoformat(), "dte": dte, "weekday": day.strftime("%a"),
                    "spot": round(espot, 1), "atm": atm,
                    "ce_entry": round(ce0, 2), "pe_entry": round(pe0, 2),
                    "straddle_prem": round(ce0 + pe0, 2),
                    "iv": round(iv_avg, 2), "regime": _regime(iv_avg),
                    "net_delta": round(net_delta, 1), "net_theta": round(net_theta, 1),
                    "net_vega": round(net_vega, 1), "net_gamma": round(net_gamma, 4),
                    "pnl_nosl": round(nosl, 1), "pnl_sl": round(base, 1), "sl_reason": base_rsn,
                    "pnl_reentry": round(reentry, 1), "reentry_fills": f_ce + f_pe,
                    **{f"pnl_trail{int(tr)}": round(trails[tr], 1) for tr in TRAILS},
                })
    finally:
        cur.close()
    secs = round(_time.time() - t0, 1)
    print(f"{len(rows)} trades analyzed in {secs}s")
    if not rows:
        print("no data"); return

    out = Path("data"); out.mkdir(exist_ok=True)
    csv_path = out / "straddle_trades.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print("wrote", csv_path)

    html = build_report(u, start, end, entry_t, exit_t, sl, secs, rows)
    html_path = out / "straddle_analysis.html"
    html_path.write_text(html, encoding="utf-8")
    print("wrote", html_path)


def _regime(iv: float) -> str:
    if iv < 12: return "low (<12)"
    if iv < 15: return "normal (12-15)"
    if iv < 18: return "elevated (15-18)"
    if iv < 22: return "high (18-22)"
    return "extreme (22+)"


def _agg(vals: list[float]) -> dict:
    n = len(vals)
    if n == 0:
        return {"n": 0, "net": 0, "avg": 0, "win": 0, "dd": 0}
    eq = np.cumsum(vals); peak = np.maximum.accumulate(eq); dd = float(np.max(peak - eq)) if n else 0
    wins = sum(1 for v in vals if v > 0)
    return {"n": n, "net": round(sum(vals), 0), "avg": round(sum(vals) / n, 0),
            "win": round(wins / n * 100, 1), "dd": round(dd, 0)}


def _bucket(rows, key, getbucket, pnl_key="pnl_sl", order=None):
    b: dict = {}
    for r in rows:
        b.setdefault(getbucket(r), []).append(r[pnl_key])
    items = list(b.items())
    if order:
        items.sort(key=lambda kv: order.index(kv[0]) if kv[0] in order else 99)
    else:
        items.sort(key=lambda kv: kv[0])
    return [(k, _agg(v)) for k, v in items]


def _corr(rows, xk, yk):
    xs = [r[xk] for r in rows]; ys = [r[yk] for r in rows]
    if len(xs) < 3 or st.pstdev(xs) == 0 or st.pstdev(ys) == 0:
        return 0.0
    mx, my = st.mean(xs), st.mean(ys)
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / len(xs)
    return round(cov / (st.pstdev(xs) * st.pstdev(ys)), 3)


def build_report(u, start, end, et, xt, sl, secs, rows) -> str:
    variants = [
        ("No stop-loss (hold to exit)", "pnl_nosl"),
        (f"Per-leg SL {sl:.0f}% (baseline)", "pnl_sl"),
        (f"SL {sl:.0f}% + re-entry", "pnl_reentry"),
        *[(f"Trailing SL {int(tr)}%", f"pnl_trail{int(tr)}") for tr in TRAILS],
    ]
    var_rows = [(name, _agg([r[k] for r in rows])) for name, k in variants]
    base_net = _agg([r["pnl_sl"] for r in rows])["net"]

    def vtable():
        head = "<tr><th>Variant</th><th>Net P&L</th><th>vs SL88</th><th>Avg/day</th><th>Win%</th><th>Max DD</th><th>Trades</th></tr>"
        body = ""
        for name, a in var_rows:
            diff = a["net"] - base_net
            body += f"<tr><td style='text-align:left'>{name}</td><td class='{cls(a['net'])}'>{rs(a['net'])}</td><td class='{cls(diff)}'>{rs(diff)}</td><td>{rs(a['avg'])}</td><td>{a['win']}</td><td>{rs(a['dd'])}</td><td>{a['n']}</td></tr>"
        return head + body

    def btable(title, buckets):
        head = f"<tr><th>{title}</th><th>Net</th><th>Avg</th><th>Win%</th><th>Max DD</th><th>n</th></tr>"
        mx = max((abs(a["net"]) for _, a in buckets), default=1) or 1
        body = ""
        for k, a in buckets:
            w = int(abs(a["net"]) / mx * 100)
            bar = f"<div class='bar {cls(a['net'])}b' style='width:{w}%'></div>"
            body += f"<tr><td style='text-align:left'>{k}</td><td class='{cls(a['net'])}'>{rs(a['net'])}<div class='barwrap'>{bar}</div></td><td>{rs(a['avg'])}</td><td>{a['win']}</td><td>{rs(a['dd'])}</td><td>{a['n']}</td></tr>"
        return head + body

    iv_b = _bucket(rows, "iv", lambda r: r["regime"], order=["low (<12)", "normal (12-15)", "elevated (15-18)", "high (18-22)", "extreme (22+)"])
    dte_b = _bucket(rows, "dte", lambda r: _dte_bucket(r["dte"]), order=["0 (expiry)", "1", "2-3", "4-7", "8+"])
    wd_b = _bucket(rows, "weekday", lambda r: r["weekday"], order=["Mon", "Tue", "Wed", "Thu", "Fri"])
    theta_b = _bucket(rows, "net_theta", lambda r: _q_bucket(r["net_theta"], rows, "net_theta"))
    delta_b = _bucket(rows, "net_delta", lambda r: _absdelta_bucket(r["net_delta"]))
    vega_b = _bucket(rows, "net_vega", lambda r: _q_bucket(r["net_vega"], rows, "net_vega"))
    prem_b = _bucket(rows, "straddle_prem", lambda r: _q_bucket(r["straddle_prem"], rows, "straddle_prem"))

    cors = [
        ("P&L vs entry IV", _corr(rows, "iv", "pnl_sl")),
        ("P&L vs net theta collected", _corr(rows, "net_theta", "pnl_sl")),
        ("P&L vs net vega", _corr(rows, "net_vega", "pnl_sl")),
        ("P&L vs straddle premium", _corr(rows, "straddle_prem", "pnl_sl")),
        ("P&L vs net delta skew", _corr(rows, "net_delta", "pnl_sl")),
        ("P&L vs DTE", _corr(rows, "dte", "pnl_sl")),
    ]
    ctable = "<tr><th>Relationship</th><th>Pearson r</th><th>Read</th></tr>" + "".join(
        f"<tr><td style='text-align:left'>{n}</td><td class='{cls(v)}'>{v:+.3f}</td><td style='text-align:left;color:#9ca3af'>{_read_corr(v)}</td></tr>" for n, v in cors)

    sl_hit = sum(1 for r in rows if r["sl_reason"] == "STOPLOSS")
    reentry_extra = _agg([r["pnl_reentry"] for r in rows])["net"] - base_net
    best_trail = max(TRAILS, key=lambda tr: _agg([r[f"pnl_trail{int(tr)}"] for r in rows])["net"])
    best_trail_net = _agg([r[f"pnl_trail{int(best_trail)}"] for r in rows])["net"]

    verdict = f"""
    <ul>
      <li><b>SL {sl:.0f}% hit on {sl_hit}/{len(rows)} days ({sl_hit/len(rows)*100:.0f}%)</b>. Baseline net {rs(base_net)}.</li>
      <li><b>Re-entry after SL: {('+' if reentry_extra>=0 else '')}{rs(reentry_extra)} vs baseline</b> — {'adds edge' if reentry_extra>0 else 'destroys edge (re-selling into the same move)'}.</li>
      <li><b>Best trailing = {int(best_trail)}%</b> -> net {rs(best_trail_net)} ({('+' if best_trail_net-base_net>=0 else '')}{rs(best_trail_net-base_net)} vs SL88). {'Trailing helps.' if best_trail_net>base_net else 'Fixed SL beats trailing here.'}</li>
      <li>Theta correlation {cors[1][1]:+.3f}, IV correlation {cors[0][1]:+.3f} — {'higher IV/theta days pay more' if cors[1][1]>0.05 else 'edge not simply IV-driven'}.</li>
    </ul>"""

    return _PAGE.format(
        u=u, start=start, end=end, et=et.strftime("%H:%M"), xt=xt.strftime("%H:%M"),
        sl=int(sl), n=len(rows), secs=secs, gen=datetime.now().strftime("%Y-%m-%d %H:%M"),
        vtable=vtable(), verdict=verdict, ctable=ctable,
        iv_b=btable("Entry IV regime", iv_b), dte_b=btable("Days to expiry", dte_b),
        wd_b=btable("Weekday", wd_b), theta_b=btable("Net theta (quartile)", theta_b),
        delta_b=btable("Net delta skew", delta_b), vega_b=btable("Net vega (quartile)", vega_b),
        prem_b=btable("Straddle premium (quartile)", prem_b),
    )


def _dte_bucket(d):
    if d <= 0: return "0 (expiry)"
    if d == 1: return "1"
    if d <= 3: return "2-3"
    if d <= 7: return "4-7"
    return "8+"


def _absdelta_bucket(nd):
    a = abs(nd)
    if a < 5: return "near 0 (<5)"
    if a < 15: return "5-15"
    if a < 30: return "15-30"
    return "30+"


_QCACHE: dict = {}

def _q_bucket(v, rows, key):
    if key not in _QCACHE:
        xs = sorted(r[key] for r in rows)
        n = len(xs)
        _QCACHE[key] = [xs[n // 4], xs[n // 2], xs[3 * n // 4]]
    q1, q2, q3 = _QCACHE[key]
    if v <= q1: return f"Q1 low (<={q1:.0f})"
    if v <= q2: return f"Q2 (<={q2:.0f})"
    if v <= q3: return f"Q3 (<={q3:.0f})"
    return f"Q4 high (>{q3:.0f})"


def _read_corr(v):
    a = abs(v)
    s = "strong" if a > 0.4 else "moderate" if a > 0.2 else "weak" if a > 0.08 else "negligible"
    d = "positive" if v > 0 else "negative"
    return f"{s} {d}"


def rs(n):
    n = float(n)
    sign = "-" if n < 0 else ""
    a = abs(n)
    if a >= 1e5: return f"{sign}₹{a/1e5:.2f}L"
    if a >= 1e3: return f"{sign}₹{a/1e3:.1f}K"
    return f"{sign}₹{a:.0f}"


def cls(n):
    return "pos" if float(n) >= 0 else "neg"


_PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>Straddle Deep Analysis</title>
<style>
 body{{background:#0b0f17;color:#e5e7eb;font:13px/1.45 system-ui,Segoe UI,Arial;margin:0;padding:24px;max-width:1100px}}
 h1{{font-size:21px;margin:0 0 4px}} h2{{font-size:15px;margin:26px 0 8px;border-left:3px solid #2563eb;padding-left:8px}}
 .sub{{color:#9ca3af;margin-bottom:8px}}
 table{{border-collapse:collapse;width:100%;font-size:12px;margin-bottom:6px}}
 th,td{{padding:5px 9px;text-align:right;border-bottom:1px solid #1f2937}}
 th{{color:#9ca3af;font-weight:600}}
 .pos{{color:#36c660}} .neg{{color:#ef4444}}
 .panel{{background:#111827;border:1px solid #1f2937;border-radius:10px;padding:14px 16px;margin-bottom:10px}}
 .barwrap{{height:3px;background:#1f2937;border-radius:2px;margin-top:3px;overflow:hidden}}
 .bar{{height:3px}} .posb{{background:#36c660}} .negb{{background:#ef4444}}
 ul{{line-height:1.7}} .grid2{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
 @media(max-width:780px){{.grid2{{grid-template-columns:1fr}}}}
</style></head><body>
<h1>ATM Short Straddle - Deep Analysis</h1>
<div class="sub">{u} · {start} -> {end} · entry {et} · exit {xt} · per-leg SL {sl}% · {n} trades · computed {secs}s · {gen}</div>
<div class="panel"><h2 style="margin-top:0">Verdict</h2>{verdict}</div>
<h2>Stop-loss / re-entry / trailing comparison</h2>
<div class="panel"><table>{vtable}</table></div>
<h2>What drives the P&L (correlations)</h2>
<div class="panel"><table>{ctable}</table></div>
<h2>P&L by factor (baseline SL)</h2>
<div class="grid2">
 <div class="panel"><table>{iv_b}</table></div>
 <div class="panel"><table>{dte_b}</table></div>
 <div class="panel"><table>{theta_b}</table></div>
 <div class="panel"><table>{vega_b}</table></div>
 <div class="panel"><table>{delta_b}</table></div>
 <div class="panel"><table>{wd_b}</table></div>
 <div class="panel"><table>{prem_b}</table></div>
</div>
</body></html>"""


if __name__ == "__main__":
    main()

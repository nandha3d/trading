"""Per-weekday strategy bake-off -> best strategy for each day -> all-day plan.

For every trading day we simulate several strategies on the SAME data and record
each one's P&L, then per weekday pick the winner and stitch them into one
"different strategy each day" portfolio (to fix the days a plain straddle loses).

Strategies (entry 09:21, exit 14:55, ATM ref, 1 lot, costs included):
  STRADDLE    sell ATM CE + ATM PE, per-leg SL 88%            (neutral)
  STRANGLE    sell CE@ATM+2 + PE@ATM-2 strikes, per-leg SL 88% (neutral, wider)
  LONG_STRAD  buy ATM CE + ATM PE, hold to exit               (wants a big move)
  ORB_DIR     opening range 9:15-9:30; on breakout buy ATM CE/PE, SL 50% (trend)
  MOM_CREDIT  if morning up -> sell ATM PE, if down -> sell ATM CE, SL 88% (trend, credit)

Outputs (data/):
  byday_trades.csv     -> per-day P&L of every strategy
  byday_report.html    -> per-weekday tables + recommended all-day plan

Usage:
  python scripts/analyze_byday.py NIFTY 2023-01-02 2026-04-13
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

from src.backtest.costs import CostModel  # noqa: E402
from src.backtest.engine import pick_expiry  # noqa: E402
from src.backtest.strategy import CONTRACT_SPECS  # noqa: E402
from src.data import storage  # noqa: E402

STRATS = ["STRADDLE", "STRANGLE", "LONG_STRAD", "ORB_DIR", "MOM_CREDIT"]
EXPIRY_SWITCH = date(2025, 9, 1)   # NSE NIFTY weekly expiry moved Thu -> Tue
ENTRY = time(9, 21)
EXIT = time(14, 55)
OR_END = time(9, 30)
SELL_SL = 88.0
BUY_SL = 50.0
STRANGLE_STEPS = 2


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


def sell_exit(a, entry, sl):
    thr = entry * (1 + sl / 100.0)
    rm = np.maximum.accumulate(a)
    hit = int(np.searchsorted(rm, thr, side="left"))
    return float(a[hit]) if hit < a.size else float(a[-1])


def buy_exit(a, entry, sl):
    thr = entry * (1 - sl / 100.0)
    rm = np.minimum.accumulate(a)
    hit = int(np.searchsorted(-rm, -thr, side="left"))
    return float(a[hit]) if hit < a.size else float(a[-1])


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
            sdf = cur.execute("SELECT ts,close FROM spot_1m WHERE underlying=? AND ts>=? AND ts<=? ORDER BY ts", [u, c0, c1]).pl()
            odf = cur.execute("SELECT ts,strike,option_type,close,expiry FROM options_1m WHERE underlying=? AND ts>=? AND ts<=?", [u, c0, c1]).pl()
            if sdf.is_empty() or odf.is_empty():
                continue
            sby = {p["_d"][0]: p.drop("_d") for p in sdf.with_columns(pl.col("ts").dt.date().alias("_d")).partition_by("_d")}
            oby = {(p["_d"][0], p["expiry"][0]): p.drop("_d") for p in odf.with_columns(pl.col("ts").dt.date().alias("_d")).partition_by(["_d", "expiry"])}

            for day, exp in md:
                sd = sby.get(day); od = oby.get((day, exp))
                if sd is None or od is None or sd.is_empty() or od.is_empty():
                    continue
                grid = _minutes(day, time(9, 15), EXIT)
                gidx = {m: i for i, m in enumerate(grid)}
                ge = gidx.get(datetime.combine(day, ENTRY))
                if ge is None:
                    continue
                spm = {r["ts"].replace(second=0, microsecond=0): r["close"] for r in sd.select(["ts", "close"]).iter_rows(named=True)}
                spot = _ffill(spm, grid)
                espot = spot[ge]
                if not np.isfinite(espot):
                    continue
                atm = int(round(espot / step) * step)

                opm = defaultdict(dict)
                for r in od.select(["strike", "option_type", "ts", "close"]).iter_rows(named=True):
                    opm[(r["strike"], r["option_type"])][r["ts"].replace(second=0, microsecond=0)] = r["close"]
                cache = {}

                def arr(strike, ot, _opm=opm, _cache=cache, _grid=grid):
                    key = (strike, ot)
                    if key not in _cache:
                        pm = _opm.get(key)
                        _cache[key] = _ffill(pm, _grid) if pm else None
                    return _cache[key]

                res = {s: None for s in STRATS}

                res["STRADDLE"] = _sell_pair(arr, atm, atm, ge, qty, costs, SELL_SL)
                res["STRANGLE"] = _sell_pair(arr, atm + STRANGLE_STEPS * step, atm - STRANGLE_STEPS * step, ge, qty, costs, SELL_SL)

                ce, pe = arr(atm, "CE"), arr(atm, "PE")
                if ce is not None and pe is not None and np.isfinite(ce[ge]) and np.isfinite(pe[ge]) and ce[ge] > 0 and pe[ge] > 0:
                    cx, px = ce[ge:], pe[ge:]
                    res["LONG_STRAD"] = ((cx[-1] - cx[0]) + (px[-1] - px[0])) * qty - costs.leg_cost(cx[0], cx[-1], qty) - costs.leg_cost(px[0], px[-1], qty)

                o0 = spot[0]
                up = bool(np.isfinite(o0) and (espot - o0) > 0)
                leg = arr(atm, "PE" if up else "CE")
                if leg is not None and np.isfinite(leg[ge]) and leg[ge] > 0:
                    seg = leg[ge:]; en = seg[0]; ex = sell_exit(seg, en, SELL_SL)
                    res["MOM_CREDIT"] = (en - ex) * qty - costs.leg_cost(en, ex, qty)

                oe = gidx.get(datetime.combine(day, OR_END))
                if oe is not None and oe > 0:
                    win = spot[:oe + 1]
                    if np.isfinite(win).any():
                        orh = np.nanmax(win); orl = np.nanmin(win)
                        bi = None; bdir = None
                        for i in range(oe + 1, len(grid)):
                            if not np.isfinite(spot[i]):
                                continue
                            if spot[i] > orh:
                                bi, bdir = i, "CE"; break
                            if spot[i] < orl:
                                bi, bdir = i, "PE"; break
                        if bi is not None:
                            batm = int(round(spot[bi] / step) * step)
                            leg = arr(batm, bdir)
                            if leg is not None and np.isfinite(leg[bi]) and leg[bi] > 0:
                                seg = leg[bi:]; en = seg[0]; ex = buy_exit(seg, en, BUY_SL)
                                res["ORB_DIR"] = (ex - en) * qty - costs.leg_cost(en, ex, qty)

                era = "Thu-era" if day < EXPIRY_SWITCH else "Tue-era"
                row = {"date": day.isoformat(), "weekday": day.strftime("%a"), "era": era,
                       "dte": max((exp - day).days, 0), "spot": round(espot, 1), "atm": atm,
                       "dir": "up" if up else "down"}
                for s in STRATS:
                    row[s] = "" if res[s] is None else round(res[s], 1)
                rows.append(row)
    finally:
        cur.close()
    secs = round(_time.time() - t0, 1)
    print(f"{len(rows)} days, {len(STRATS)} strategies in {secs}s")
    if not rows:
        print("no data"); return

    out = Path("data"); out.mkdir(exist_ok=True)
    cp = out / "byday_trades.csv"
    with cp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print("wrote", cp)
    hp = out / "byday_report.html"
    hp.write_text(build(u, start, end, secs, rows), encoding="utf-8")
    print("wrote", hp)

    for era in ["Thu-era", "Tue-era"]:
        er = [r for r in rows if r["era"] == era]
        if not er:
            continue
        print(f"== {era} ({len(er)} days) ==")
        best = {}
        for wd in ["Mon", "Tue", "Wed", "Thu", "Fri"]:
            rr = [r for r in er if r["weekday"] == wd]
            if not rr:
                continue
            scores = {s: _agg([float(r[s]) for r in rr if r[s] != ""]) for s in STRATS}
            bs = max(scores, key=lambda s: scores[s]["net"])
            best[wd] = scores[bs]["net"]
            print(f"  {wd}: best={bs} net={scores[bs]['net']:,.0f} win={scores[bs]['win']}% | straddle={scores['STRADDLE']['net']:,.0f}")
        combined = sum(best.values())
        strad = sum(_agg([float(r["STRADDLE"]) for r in er if r["weekday"] == wd and r["STRADDLE"] != ""])["net"] for wd in best)
        print(f"  ALL-DAY best={combined:,.0f}  vs straddle={strad:,.0f}  (+{combined-strad:,.0f})")


def _sell_pair(arr, kce, kpe, ge, qty, costs, sl):
    ce, pe = arr(kce, "CE"), arr(kpe, "PE")
    if ce is None or pe is None or not (np.isfinite(ce[ge]) and np.isfinite(pe[ge]) and ce[ge] > 0 and pe[ge] > 0):
        return None
    cx, px = ce[ge:], pe[ge:]
    cex = sell_exit(cx, cx[0], sl); pex = sell_exit(px, px[0], sl)
    return (cx[0] - cex) * qty + (px[0] - pex) * qty - costs.leg_cost(cx[0], cex, qty) - costs.leg_cost(px[0], pex, qty)


def _agg(vals):
    n = len(vals)
    if not n:
        return dict(n=0, net=0, avg=0, win=0, dd=0)
    eq = np.cumsum(vals); dd = float((np.maximum.accumulate(eq) - eq).max())
    return dict(n=n, net=round(sum(vals)), avg=round(sum(vals) / n),
                win=round(sum(1 for v in vals if v > 0) / n * 100), dd=round(dd))


def money(n):
    n = float(n); s = "-" if n < 0 else ""; a = abs(n)
    if a >= 1e5: return f"{s}₹{a/1e5:.2f}L"
    if a >= 1e3: return f"{s}₹{a/1e3:.1f}K"
    return f"{s}₹{a:.0f}"


def cls(n):
    return "pos" if float(n) >= 0 else "neg"


NAMES = {"STRADDLE": "Short Straddle", "STRANGLE": "Short Strangle", "LONG_STRAD": "Long Straddle",
         "ORB_DIR": "Directional breakout (ORB)", "MOM_CREDIT": "Momentum credit (sell trend side)"}
KIND = {"STRADDLE": "neutral", "STRANGLE": "neutral", "LONG_STRAD": "buy big-move",
        "ORB_DIR": "directional", "MOM_CREDIT": "directional"}


ERA_LABEL = {"Thu-era": "Thursday-expiry era (Jan 2023 - 31 Aug 2025)",
             "Tue-era": "Tuesday-expiry era (1 Sep 2025 - now)"}


def _era_section(era, rows):
    full = {"Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday", "Fri": "Friday"}
    er = [r for r in rows if r["era"] == era]
    if not er:
        return ""
    wd_tables = ""; plan_cards = ""; combined = 0; strad_only = 0
    exp_wd = "Thu" if era == "Thu-era" else "Tue"
    for wd in ["Mon", "Tue", "Wed", "Thu", "Fri"]:
        rr = [r for r in er if r["weekday"] == wd]
        if not rr:
            continue
        scores = {s: _agg([float(r[s]) for r in rr if r[s] != ""]) for s in STRATS}
        best = max(STRATS, key=lambda s: scores[s]["net"])
        combined += scores[best]["net"]; strad_only += scores["STRADDLE"]["net"]
        mx = max(abs(scores[s]["net"]) for s in STRATS) or 1
        body = ""
        for s in sorted(STRATS, key=lambda s: -scores[s]["net"]):
            a = scores[s]; w = int(abs(a["net"]) / mx * 100)
            star = " &#11088;" if s == best else ""
            body += (f"<tr><td class='lbl'>{NAMES[s]}{star}<div class='muted'>{KIND[s]}</div></td>"
                     f"<td class='{cls(a['net'])}'>{money(a['net'])}<div class='bw'><div class='b {cls(a['net'])}b' style='width:{w}%'></div></div></td>"
                     f"<td>{money(a['avg'])}</td><td>{a['win']}%</td><td>{a['n']}</td></tr>")
        exp_tag = " <span class='pill'>EXPIRY DAY</span>" if wd == exp_wd else ""
        wd_tables += (f"<div class='card'><h3>{full[wd]}{exp_tag}</h3>"
                      f"<table><tr><th>Strategy</th><th>Total</th><th>Per day</th><th>Win</th><th>Days</th></tr>{body}</table></div>")
        ba = scores[best]; tone = "good" if ba["net"] > 0 else "bad"
        plan_cards += (f"<div class='daycard {tone}'><div class='dhead'><span class='dname'>{full[wd]}{exp_tag}</span>"
                       f"<span class='dpnl {cls(ba['net'])}'>{money(ba['net'])} · {money(ba['avg'])}/day · {ba['win']}% win</span></div>"
                       f"<div class='daction'><b>Use:</b> {NAMES[best]} <span class='muted'>({KIND[best]})</span></div>"
                       f"<div class='muted'>{_why(best)}</div></div>")
    hero = (f"<div class='card hero'><div class='muted'>{ERA_LABEL[era]} · {len(er)} days</div>"
            f"<div class='big pos'>{money(combined)}</div>"
            f"<p>Best strategy each weekday vs straddle-every-day ({money(strad_only)}). "
            f"Tailoring adds <b>{money(combined - strad_only)}</b>. Expiry day this era = <b>{full[exp_wd]}</b>.</p></div>")
    return (f"<h2>{ERA_LABEL[era]}</h2>{hero}"
            f"<h3 style='margin-top:14px'>Recommended plan</h3>{plan_cards}"
            f"<h3 style='margin-top:14px'>Full bake-off</h3>{wd_tables}")


def build(u, start, end, secs, rows):
    sections = "".join(_era_section(e, rows) for e in ["Thu-era", "Tue-era"])
    return _PAGE.format(u=u, start=start, end=end, secs=secs, n=len(rows),
                        gen=datetime.now().strftime("%d %b %Y, %H:%M"), sections=sections)


def _why(best):
    w = {
        "STRADDLE": "Calm, range-bound day - collect premium both sides.",
        "STRANGLE": "Mild drift - wider breakevens survive small moves.",
        "LONG_STRAD": "Expansion day - pay premium, profit from a big move.",
        "ORB_DIR": "Trending day - ride the opening-range breakout direction.",
        "MOM_CREDIT": "Trending day - sell the option the trend is moving away from.",
    }
    return w.get(best, "")


_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>All-Day Strategy Plan</title>
<style>
 :root{{--bg:#0b0f17;--card:#111827;--line:#1f2937;--mut:#9ca3af;--pos:#36c660;--neg:#ef4444;--blue:#3b82f6}}
 *{{box-sizing:border-box}} body{{background:var(--bg);color:#e5e7eb;font:15px/1.6 system-ui,Segoe UI,Arial;margin:0}}
 .wrap{{max-width:920px;margin:0 auto;padding:28px 20px 60px}}
 h1{{font-size:25px;margin:0 0 6px}} h2{{font-size:19px;margin:30px 0 10px;display:flex;gap:8px;align-items:center}}
 h2:before{{content:'';width:5px;height:20px;background:var(--blue);border-radius:3px}}
 h3{{font-size:16px;margin:0 0 6px}} .sub{{color:var(--mut);margin-bottom:16px}} .muted{{color:var(--mut);font-size:13px}}
 .card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 18px;margin:12px 0}}
 .hero{{background:linear-gradient(135deg,#0f1b34,#111827);border:1px solid #243049}} .hero .big{{font-size:28px;font-weight:800}}
 table{{border-collapse:collapse;width:100%;font-size:13.5px}} th,td{{padding:7px 9px;text-align:right;border-bottom:1px solid var(--line);vertical-align:top}}
 th{{color:var(--mut)}} td.lbl,th:first-child{{text-align:left}} .pos{{color:var(--pos)}} .neg{{color:var(--neg)}}
 .bw{{height:4px;background:#1f2937;border-radius:3px;margin-top:4px;max-width:150px}} .b{{height:4px;border-radius:3px}} .posb{{background:var(--pos)}} .negb{{background:var(--neg)}}
 .daycard{{border-radius:12px;padding:13px 16px;border:1px solid var(--line);background:var(--card);margin:10px 0}}
 .daycard.good{{border-left:5px solid var(--pos)}} .daycard.bad{{border-left:5px solid var(--neg)}}
 .dhead{{display:flex;justify-content:space-between;flex-wrap:wrap;align-items:baseline}} .dname{{font-size:18px;font-weight:800}} .dpnl{{font-size:13px}}
 .daction{{background:#0b1220;border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin:8px 0}}
 .pill{{display:inline-block;padding:1px 8px;border-radius:99px;font-size:11px;font-weight:700;background:#0f3d22;color:#36c660;vertical-align:middle}}
 b{{color:#fff}}
</style></head><body><div class="wrap">
<h1>All-Day Plan - Split by Expiry Era</h1>
<div class="sub">{u} · {start} -> {end} · {n} days · 5 strategies/day · {gen} · computed {secs}s</div>
<div class="card"><p class="muted">NSE moved NIFTY weekly expiry from <b>Thursday</b> to <b>Tuesday</b> on <b>1 Sep 2025</b>. The two eras are analysed separately - the profitable "money day" follows the expiry, so it shifts between eras. &#11088; = best strategy that weekday. "Per day" = average over days that strategy actually traded.</p></div>

{sections}

<div class="card"><h3>What each strategy means</h3>
 <ul>
  <li><b>Short Straddle</b> - sell ATM Call + Put. Wins on calm days. (neutral)</li>
  <li><b>Short Strangle</b> - sell slightly out-of-money Call + Put. Wider safe zone, smaller premium. (neutral)</li>
  <li><b>Long Straddle</b> - buy ATM Call + Put. Wins only on big-move days. (expansion)</li>
  <li><b>Directional breakout (ORB)</b> - watch first 15 min range; buy a Call if price breaks up, a Put if it breaks down; 50% stop. (trend)</li>
  <li><b>Momentum credit</b> - if morning is up, sell the Put; if down, sell the Call; 88% stop. (trend)</li>
 </ul>
</div>
<p class="muted">Past results are not a promise of future returns. Costs &amp; slippage included; live fills may differ.</p>
</div></body></html>"""


if __name__ == "__main__":
    main()

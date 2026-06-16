"""OI-context analysis for the ATM straddle days.

Reuses per-trade P&L from data/straddle_trades.csv (entry 09:21, SL 88%) and, at
the same entry minute, computes OI metrics from the full option chain:
  * PCR (PE OI / CE OI, near-ATM band)
  * Max-pain strike + distance from spot
  * Total chain OI (liquidity regime)
  * ATM CE/PE OI change since 09:15 open -> buildup quadrant
Then buckets straddle P&L by each, to see which OI scenarios favor selling.

Outputs (data/):
  oi_trades.csv        -> straddle rows + OI metrics
  oi_analysis.html     -> self-contained report

Usage:
  python scripts/analyze_oi.py NIFTY 2023-01-02 2026-04-13 09:21
"""
from __future__ import annotations

import csv
import sys
import time as _time
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest.engine import pick_expiry  # noqa: E402
from src.backtest.strategy import CONTRACT_SPECS  # noqa: E402
from src.data import storage  # noqa: E402


def _t(s: str) -> time:
    h, m = map(int, s.split(":"))
    return time(h, m)


def _snap_at(rows: list[dict], minute: datetime) -> dict[tuple[int, str], dict]:
    """Latest row per (strike, type) at or before `minute`."""
    out: dict[tuple[int, str], dict] = {}
    for r in rows:
        ts = r["ts"]
        if ts > minute:
            continue
        k = (r["strike"], r["option_type"])
        cur = out.get(k)
        if cur is None or ts > cur["ts"]:
            out[k] = r
    return out


def _max_pain(snap: dict[tuple[int, str], dict], strikes: list[int]) -> int | None:
    """Strike where option writers lose least (classic OI max-pain)."""
    best, best_loss = None, None
    for s in strikes:
        loss = 0.0
        for k in strikes:
            ce_oi = (snap.get((k, "CE")) or {}).get("oi") or 0
            pe_oi = (snap.get((k, "PE")) or {}).get("oi") or 0
            if s > k:
                loss += ce_oi * (s - k)   # call writers pay
            if s < k:
                loss += pe_oi * (k - s)   # put writers pay
        if best_loss is None or loss < best_loss:
            best_loss, best = loss, s
    return best


def main() -> None:
    av = sys.argv[1:]
    u = av[0] if len(av) > 0 else "NIFTY"
    start = date.fromisoformat(av[1]) if len(av) > 1 else date(2023, 1, 2)
    end = date.fromisoformat(av[2]) if len(av) > 2 else date(2026, 4, 13)
    entry_t = _t(av[3]) if len(av) > 3 else time(9, 21)

    step = CONTRACT_SPECS[u]["strike_step"]

    pnl_by: dict[str, dict] = {}
    csv_in = Path("data/straddle_trades.csv")
    if csv_in.exists():
        for r in csv.DictReader(csv_in.open(encoding="utf-8")):
            pnl_by[r["date"]] = r
    if not pnl_by:
        print("run scripts/analyze_straddle.py first (need data/straddle_trades.csv)"); return

    expiries = storage.list_expiries(u)
    days = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            e = pick_expiry(expiries, d, 0)
            if e and d.isoformat() in pnl_by:
                days.append((d, e))
        d = date.fromordinal(d.toordinal() + 1)

    by_month: dict = {}
    for dd, ee in days:
        by_month.setdefault((dd.year, dd.month), []).append((dd, ee))

    out_rows = []
    t0 = _time.time()
    cur = storage.db().cursor()
    try:
        for _key, mdays in sorted(by_month.items()):
            c0 = datetime.combine(min(x for x, _ in mdays), time(9, 15))
            c1 = datetime.combine(max(x for x, _ in mdays), time(9, 35))  # morning window only
            sdf = cur.execute("SELECT ts,close FROM spot_1m WHERE underlying=? AND ts>=? AND ts<=? ORDER BY ts",
                              [u, c0, c1]).pl()
            odf = cur.execute("SELECT ts,strike,option_type,close,oi,expiry FROM options_1m WHERE underlying=? AND ts>=? AND ts<=?",
                              [u, c0, c1]).pl()
            if sdf.is_empty() or odf.is_empty():
                continue
            spot_by = {p["_d"][0]: p for p in sdf.with_columns(pl.col("ts").dt.date().alias("_d")).partition_by("_d")}
            opt_by = {(p["_d"][0], p["expiry"][0]): p for p in odf.with_columns(pl.col("ts").dt.date().alias("_d")).partition_by(["_d", "expiry"])}

            for day, exp in mdays:
                sd = spot_by.get(day); od = opt_by.get((day, exp))
                if sd is None or od is None or sd.is_empty() or od.is_empty():
                    continue
                edt = datetime.combine(day, entry_t)
                open_dt = datetime.combine(day, time(9, 15))
                es = sd.sort("ts").filter(pl.col("ts") <= edt)
                if es.is_empty():
                    continue
                espot = es["close"][-1]
                atm = int(round(espot / step) * step)

                orows = od.select(["ts", "strike", "option_type", "close", "oi"]).to_dicts()
                snap = _snap_at(orows, edt)
                open_snap = _snap_at(orows, open_dt + timedelta(minutes=1))
                if not snap:
                    continue
                strikes = sorted({k for (k, _) in snap.keys()})
                band = [s for s in strikes if abs(s - atm) <= 5 * step]

                ce_oi = sum((snap.get((s, "CE")) or {}).get("oi") or 0 for s in band)
                pe_oi = sum((snap.get((s, "PE")) or {}).get("oi") or 0 for s in band)
                pcr = round(pe_oi / ce_oi, 3) if ce_oi else 0.0
                total_oi = sum((snap.get((s, t)) or {}).get("oi") or 0 for s in strikes for t in ("CE", "PE"))
                mp = _max_pain(snap, strikes) or atm
                mp_dist = round((mp - espot) / espot * 100, 2)

                def ochg(otype):
                    now = (snap.get((atm, otype)) or {}).get("oi") or 0
                    op = (open_snap.get((atm, otype)) or {}).get("oi") or 0
                    return now - op
                ce_chg, pe_chg = ochg("CE"), ochg("PE")
                buildup = _buildup(ce_chg, pe_chg)

                pr = pnl_by[day.isoformat()]
                out_rows.append({
                    "date": day.isoformat(), "weekday": pr["weekday"], "dte": pr["dte"],
                    "iv": pr["iv"], "spot": round(espot, 1), "atm": atm,
                    "pcr": pcr, "total_oi": total_oi,
                    "max_pain": mp, "mp_dist_pct": mp_dist,
                    "atm_ce_oi_chg": ce_chg, "atm_pe_oi_chg": pe_chg, "buildup": buildup,
                    "pnl_sl": float(pr["pnl_sl"]),
                })
    finally:
        cur.close()
    secs = round(_time.time() - t0, 1)
    print(f"{len(out_rows)} days with OI context in {secs}s")
    if not out_rows:
        print("no data"); return

    out = Path("data"); out.mkdir(exist_ok=True)
    cp = out / "oi_trades.csv"
    with cp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader(); w.writerows(out_rows)
    print("wrote", cp)

    hp = out / "oi_analysis.html"
    hp.write_text(build(u, start, end, entry_t, secs, out_rows), encoding="utf-8")
    print("wrote", hp)


def _buildup(ce_chg, pe_chg) -> str:
    if abs(ce_chg) < 1 and abs(pe_chg) < 1:
        return "flat"
    if ce_chg > pe_chg and ce_chg > 0:
        return "CE writing (resistance)"
    if pe_chg > ce_chg and pe_chg > 0:
        return "PE writing (support)"
    if ce_chg < 0 and ce_chg < pe_chg:
        return "CE unwind"
    return "PE unwind"


def _agg(vals):
    n = len(vals)
    if n == 0:
        return {"n": 0, "net": 0, "avg": 0, "win": 0}
    return {"n": n, "net": round(sum(vals)), "avg": round(sum(vals) / n),
            "win": round(sum(1 for v in vals if v > 0) / n * 100, 1)}


def _corr(rows, xk, yk):
    import statistics as st
    xs = [float(r[xk]) for r in rows]; ys = [float(r[yk]) for r in rows]
    if len(xs) < 3 or st.pstdev(xs) == 0 or st.pstdev(ys) == 0:
        return 0.0
    mx, my = st.mean(xs), st.mean(ys)
    return round(sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / len(xs) / (st.pstdev(xs) * st.pstdev(ys)), 3)


def build(u, start, end, et, secs, rows) -> str:
    def bk(getb, order=None, pnl="pnl_sl"):
        b = defaultdict(list)
        for r in rows:
            b[getb(r)].append(float(r[pnl]))
        items = sorted(b.items(), key=lambda kv: (order.index(kv[0]) if order and kv[0] in order else 99, kv[0]))
        return [(k, _agg(v)) for k, v in items]

    def tbl(title, buckets):
        mx = max((abs(a["net"]) for _, a in buckets), default=1) or 1
        rs_ = "<tr><th>%s</th><th>Net</th><th>Avg</th><th>Win%%</th><th>n</th></tr>" % title
        for k, a in buckets:
            w = int(abs(a["net"]) / mx * 100)
            rs_ += f"<tr><td style='text-align:left'>{k}</td><td class='{cls(a['net'])}'>{rs(a['net'])}<div class='bw'><div class='b {cls(a['net'])}b' style='width:{w}%'></div></div></td><td>{rs(a['avg'])}</td><td>{a['win']}</td><td>{a['n']}</td></tr>"
        return rs_

    def pcrb(r):
        p = float(r["pcr"])
        if p < 0.7: return "low <0.7 (CE heavy)"
        if p < 0.9: return "0.7-0.9"
        if p < 1.1: return "0.9-1.1 (balanced)"
        if p < 1.4: return "1.1-1.4"
        return ">1.4 (PE heavy)"

    def mpb(r):
        d = abs(float(r["mp_dist_pct"]))
        if d < 0.2: return "at max-pain (<0.2%)"
        if d < 0.5: return "0.2-0.5%"
        if d < 1.0: return "0.5-1.0%"
        return ">1.0% away"

    xs = sorted(float(x["total_oi"]) for x in rows); n = len(xs)
    q1, q2, q3 = xs[n // 4], xs[n // 2], xs[3 * n // 4]
    def oib(r):
        v = float(r["total_oi"])
        return "Q1 low OI" if v <= q1 else "Q2" if v <= q2 else "Q3" if v <= q3 else "Q4 high OI"

    pcr_t = tbl("PCR (near-ATM)", bk(pcrb, ["low <0.7 (CE heavy)", "0.7-0.9", "0.9-1.1 (balanced)", "1.1-1.4", ">1.4 (PE heavy)"]))
    mp_t = tbl("Spot vs max-pain", bk(mpb, ["at max-pain (<0.2%)", "0.2-0.5%", "0.5-1.0%", ">1.0% away"]))
    oi_t = tbl("Total chain OI", bk(oib, ["Q1 low OI", "Q2", "Q3", "Q4 high OI"]))
    bu_t = tbl("ATM OI buildup (since open)", bk(lambda r: r["buildup"]))

    cors = [("P&L vs PCR", _corr(rows, "pcr", "pnl_sl")),
            ("P&L vs |max-pain distance|", _corr(rows, "mp_dist_pct", "pnl_sl")),
            ("P&L vs total OI", _corr(rows, "total_oi", "pnl_sl"))]
    ct = "<tr><th>Relationship</th><th>r</th></tr>" + "".join(
        f"<tr><td style='text-align:left'>{n2}</td><td class='{cls(v)}'>{v:+.3f}</td></tr>" for n2, v in cors)

    return _PAGE.format(u=u, start=start, end=end, et=et.strftime("%H:%M"),
                        n=len(rows), secs=secs, gen=datetime.now().strftime("%Y-%m-%d %H:%M"),
                        pcr=pcr_t, mp=mp_t, oi=oi_t, bu=bu_t, ct=ct)


def rs(n):
    n = float(n); sign = "-" if n < 0 else ""; a = abs(n)
    if a >= 1e5: return f"{sign}₹{a/1e5:.2f}L"
    if a >= 1e3: return f"{sign}₹{a/1e3:.1f}K"
    return f"{sign}₹{a:.0f}"


def cls(n):
    return "pos" if float(n) >= 0 else "neg"


_PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>OI Analysis - Straddle</title>
<style>
 body{{background:#0b0f17;color:#e5e7eb;font:13px/1.45 system-ui,Segoe UI,Arial;margin:0;padding:24px;max-width:1000px}}
 h1{{font-size:21px;margin:0 0 4px}} h2{{font-size:15px;margin:24px 0 8px;border-left:3px solid #2563eb;padding-left:8px}}
 .sub{{color:#9ca3af;margin-bottom:8px}}
 table{{border-collapse:collapse;width:100%;font-size:12px}}
 th,td{{padding:5px 9px;text-align:right;border-bottom:1px solid #1f2937}}
 th{{color:#9ca3af}}
 .pos{{color:#36c660}}.neg{{color:#ef4444}}
 .panel{{background:#111827;border:1px solid #1f2937;border-radius:10px;padding:14px 16px;margin-bottom:10px}}
 .bw{{height:3px;background:#1f2937;border-radius:2px;margin-top:3px}} .b{{height:3px}} .posb{{background:#36c660}}.negb{{background:#ef4444}}
 .grid2{{display:grid;grid-template-columns:1fr 1fr;gap:10px}} @media(max-width:760px){{.grid2{{grid-template-columns:1fr}}}}
</style></head><body>
<h1>OI Context - ATM Short Straddle</h1>
<div class="sub">{u} · {start} -> {end} · entry {et} · {n} days · {secs}s · {gen}</div>
<h2>Correlations</h2><div class="panel"><table>{ct}</table></div>
<h2>P&L by OI scenario (baseline SL)</h2>
<div class="grid2">
 <div class="panel"><table>{pcr}</table></div>
 <div class="panel"><table>{mp}</table></div>
 <div class="panel"><table>{oi}</table></div>
 <div class="panel"><table>{bu}</table></div>
</div>
</body></html>"""


if __name__ == "__main__":
    main()

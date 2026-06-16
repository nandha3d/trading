"""Master Playbook — merge every backtest finding into ONE plain-English HTML.

Reads the per-trade CSVs from the other analysis scripts and renders a single
document: the two-era regime split, day-by-day best strategy, the indicator
safety-net (incl. the OI+Supertrend+VWAP COMBO and the Monday 20%-vs-50%
directional test), IV regimes, option greeks, OI scenarios, exit-method
comparison, DTE, and a final green/red checklist.

Inputs (data/): straddle_trades.csv, oi_trades.csv, byday_trades.csv, signals_trades.csv
Output: data/master_playbook.html

Usage: python scripts/master_playbook.py
"""
from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

import numpy as np

DATA = Path("data")
SWITCH = date(2025, 9, 1)
ERAS = ["Thu-era", "Tue-era"]
ERA_LABEL = {"Thu-era": "Thursday-expiry era (to 31 Aug 2025)",
             "Tue-era": "Tuesday-expiry era (from 1 Sep 2025)"}
WD = ["Mon", "Tue", "Wed", "Thu", "Fri"]


# ---------- io / math helpers ----------
def load(name):
    p = DATA / f"{name}.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fnum(x):
    if x is None or x == "":
        return None
    try:
        return float(x)
    except ValueError:
        return None


def era_of(dstr):
    return "Thu-era" if date.fromisoformat(dstr[:10]) < SWITCH else "Tue-era"


def money(n):
    n = float(n); s = "-" if n < 0 else ""; a = abs(n)
    if a >= 1e5:
        return f"{s}₹{a/1e5:.2f}L"
    if a >= 1e3:
        return f"{s}₹{a/1e3:.1f}K"
    return f"{s}₹{a:.0f}"


def cls(n):
    return "pos" if float(n) >= 0 else "neg"


def agg(vals):
    vals = [v for v in vals if v is not None]
    n = len(vals)
    if not n:
        return dict(n=0, net=0, avg=0, win=0, dd=0, down=0)
    eq = np.cumsum(vals)
    dd = float((np.maximum.accumulate(eq) - eq).max())
    down = sum(v for v in vals if v < 0)
    return dict(n=n, net=round(sum(vals)), avg=round(sum(vals) / n),
                win=round(sum(1 for v in vals if v > 0) / n * 100),
                dd=round(dd), down=round(down))


def corr(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return 0.0
    a = np.array([p[0] for p in pairs]); b = np.array([p[1] for p in pairs])
    if a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def buckets(rows, keyfn, valfn, edges, labels):
    out = [[] for _ in labels]
    for r in rows:
        k = keyfn(r); v = valfn(r)
        if k is None or v is None:
            continue
        idx = len(edges)
        for i, e in enumerate(edges):
            if k < e:
                idx = i; break
        out[idx].append(v)
    return [(labels[i], agg(out[i])) for i in range(len(labels))]


def terciles(rows, keyfn, valfn, names=("low", "mid", "high")):
    pairs = [(keyfn(r), valfn(r)) for r in rows if keyfn(r) is not None and valfn(r) is not None]
    pairs.sort(key=lambda p: p[0])
    n = len(pairs)
    if n < 6:
        return []
    t = n // 3
    groups = [pairs[:t], pairs[t:2 * t], pairs[2 * t:]]
    return [(names[i], agg([v for _, v in groups[i]]),
             (groups[i][0][0], groups[i][-1][0])) for i in range(3)]


# ---------- strategy meta ----------
BYDAY = ["STRADDLE", "STRANGLE", "LONG_STRAD", "ORB_DIR", "MOM_CREDIT"]
BYDAY_NAMES = {"STRADDLE": "Sell ATM straddle", "STRANGLE": "Sell OTM strangle (±2 strikes)",
               "LONG_STRAD": "Buy ATM straddle", "ORB_DIR": "Opening-range breakout (directional)",
               "MOM_CREDIT": "Momentum credit (sell the quiet side)"}
SIG = ["BASE_STRAD", "VWAP_STOP", "COMBO", "OI_DIR", "ST_DIR", "EMA_DIR", "RSI_REV"]
SIG_NAMES = {"BASE_STRAD": "Straddle (plain, time-based)", "VWAP_STOP": "Straddle + VWAP trend-stop",
             "COMBO": "COMBO: OI+Supertrend+VWAP confluence", "OI_DIR": "OI-buildup directional",
             "ST_DIR": "Supertrend directional", "EMA_DIR": "EMA 9/21 cross directional",
             "RSI_REV": "RSI reversion (credit)"}


# ---------- sections ----------
def sec_tldr(byday, sig):
    rows = ""
    for era in ERAS:
        br = [r for r in byday if r["era"] == era]
        sr = [r for r in sig if r["era"] == era]
        if not br:
            continue
        # all-day best = sum of best strategy per weekday
        allbest = 0
        for wd in WD:
            wr = [r for r in br if r["weekday"] == wd]
            if wr:
                allbest += max(agg([fnum(r[s]) for r in wr])["net"] for s in BYDAY)
        strd = agg([fnum(r["STRADDLE"]) for r in br])["net"]
        combo = agg([fnum(r["COMBO"]) for r in sr])["net"] if sr else 0
        rows += (f"<tr><td class='lbl'>{ERA_LABEL[era]}</td>"
                 f"<td class='{cls(strd)}'>{money(strd)}</td>"
                 f"<td class='{cls(allbest)}'><b>{money(allbest)}</b></td>"
                 f"<td class='{cls(combo)}'>{money(combo)}</td>"
                 f"<td>{len(br)}</td></tr>")
    return (f"<div class='card hi'><h3>The one thing to remember</h3>"
            "<p>The edge follows the <b>expiry cycle, not the calendar weekday</b>. "
            "When NSE moved NIFTY weekly expiry from Thursday to Tuesday (1 Sep 2025), "
            "the market regime flipped. A plain straddle prints money in the calm "
            "Thursday-era but <b>loses</b> in the trending Tuesday-era — there you must "
            "switch to a day-specific playbook or an indicator-guided strategy.</p>"
            "<table><tr><th>Regime</th><th>Plain straddle every day</th>"
            "<th>Best-strategy-per-day</th><th>COMBO (adaptive)</th><th>Days</th></tr>"
            f"{rows}</table>"
            "<p class='muted'>\"Best-per-day\" = pick each weekday's winning strategy "
            "(see day-by-day below). COMBO = one adaptive rule that trades direction only "
            "when OI+Supertrend+VWAP agree, else sells premium with a trend-stop.</p></div>")


def card_color(best):
    if best in ("STRADDLE", "STRANGLE", "MOM_CREDIT"):
        return "g"   # premium selling
    if best == "LONG_STRAD":
        return "a"   # long vol
    return "b"       # directional


def sec_byday(byday):
    out = ""
    for era in ERAS:
        er = [r for r in byday if r["era"] == era]
        if not er:
            continue
        cards = ""
        for wd in WD:
            wr = [r for r in er if r["weekday"] == wd]
            if not wr:
                continue
            ag = {s: agg([fnum(r[s]) for r in wr]) for s in BYDAY}
            best = max(BYDAY, key=lambda s: ag[s]["net"])
            b = ag[best]; strd = ag["STRADDLE"]
            edge = b["net"] - strd["net"]
            col = card_color(best)
            note = "" if best == "STRADDLE" else f"<div class='edge'>+{money(edge)} vs straddle</div>"
            cards += (f"<div class='day {col}'><div class='dh'>{wd}</div>"
                      f"<div class='dn'>{BYDAY_NAMES[best]}</div>"
                      f"<div class='dp {cls(b['net'])}'>{money(b['net'])} net · {b['win']}% win</div>"
                      f"{note}<div class='muted2'>{b['n']} days</div></div>")
        out += (f"<h2>Day-by-day — {ERA_LABEL[era]}</h2>"
                f"<div class='days'>{cards}</div>")
    return out


def sec_signals(sig):
    out = ""
    for era in ERAS:
        er = [r for r in sig if r["era"] == era]
        if not er:
            continue
        base = agg([fnum(r["BASE_STRAD"]) for r in er])
        body = ""
        for s in SIG:
            a = agg([fnum(r[s]) for r in er])
            ddcut = base["dd"] - a["dd"]
            hi = " class='row-hi'" if s == "COMBO" else ""
            body += (f"<tr{hi}><td class='lbl'>{SIG_NAMES[s]}</td>"
                     f"<td class='{cls(a['net'])}'>{money(a['net'])}</td>"
                     f"<td>{a['win']}%</td><td class='neg'>{money(a['down'])}</td>"
                     f"<td>{money(a['dd'])}</td><td class='{cls(ddcut)}'>{money(ddcut)}</td>"
                     f"<td>{a['n']}</td></tr>")
        out += (f"<h2>Indicator safety-net — {ERA_LABEL[era]}</h2><div class='card'><table>"
                "<tr><th>Strategy</th><th>Net</th><th>Win</th><th>Loss-day sum</th>"
                "<th>Max DD</th><th>DD cut vs straddle</th><th>Days</th></tr>"
                f"{body}</table></div>")
    # Monday 20 vs 50
    mon = ""
    for era in ERAS:
        mr = [r for r in sig if r["era"] == era and r["weekday"] == "Mon"]
        if not mr:
            continue
        a20 = agg([fnum(r["mon20"]) for r in mr])
        a50 = agg([fnum(r["mon50"]) for r in mr])
        better = "20% tighter stop" if a20["net"] > a50["net"] else "50% wider stop"
        mon += (f"<tr><td class='lbl'>{ERA_LABEL[era]}</td>"
                f"<td class='{cls(a20['net'])}'>{money(a20['net'])}</td><td>{a20['win']}%</td><td>{money(a20['dd'])}</td>"
                f"<td class='{cls(a50['net'])}'>{money(a50['net'])}</td><td>{a50['win']}%</td><td>{money(a50['dd'])}</td>"
                f"<td><b>{better}</b></td><td>{a20['n']}</td></tr>")
    out += ("<h2>Monday directional — does a 20% stop work?</h2><div class='card'>"
            "<p>Question asked: on Mondays, take an OI+Supertrend+VWAP confluence directional "
            "trade — is a tight <b>20% stop</b> better than a loose <b>50% stop</b>?</p><table>"
            "<tr><th>Regime</th><th>20% net</th><th>20% win</th><th>20% DD</th>"
            "<th>50% net</th><th>50% win</th><th>50% DD</th><th>Winner</th><th>Mondays</th></tr>"
            f"{mon}</table><p class='muted'>A tight 20% stop caps each losing Monday small but "
            "stops out more often; the wider 50% lets winners run but bleeds more on trend-fail days.</p></div>")
    return out


def sec_iv(strad):
    bk = buckets(strad, lambda r: fnum(r["iv"]), lambda r: fnum(r["pnl_sl"]),
                 [12, 16, 20, 24], ["< 12", "12 - 16", "16 - 20", "20 - 24", "> 24"])
    body = "".join(
        f"<tr><td class='lbl'>IV {lab}</td><td class='{cls(a['net'])}'>{money(a['net'])}</td>"
        f"<td class='{cls(a['avg'])}'>{money(a['avg'])}</td><td>{a['win']}%</td><td>{a['n']}</td></tr>"
        for lab, a in bk)
    return ("<h2>IV regime — sell only when premium is rich</h2><div class='card'><table>"
            "<tr><th>Entry IV</th><th>Net</th><th>Avg/day</th><th>Win</th><th>Days</th></tr>"
            f"{body}</table><p class='muted'>High IV = fat premium to collect AND it usually "
            "over-states the real move (variance risk premium). Low IV = thin premium, no cushion. "
            "Sell straddles in high IV; stand aside when IV is low.</p></div>")


def sec_greeks(strad):
    pnl = [fnum(r["pnl_sl"]) for r in strad]
    rows = [("Theta (time decay collected)", "net_theta"),
            ("Delta (direction exposure)", "net_delta"),
            ("Vega (vol exposure)", "net_vega"),
            ("Gamma (move sensitivity)", "net_gamma")]
    cbody = ""
    for nm, col in rows:
        c = corr([fnum(r[col]) for r in strad], pnl)
        verdict = ("strong driver" if abs(c) >= 0.15 else "weak" if abs(c) >= 0.07 else "negligible")
        cbody += (f"<tr><td class='lbl'>{nm}</td><td class='{cls(c)}'>{c:+.3f}</td>"
                  f"<td>{verdict}</td></tr>")
    # theta terciles
    tt = terciles(strad, lambda r: fnum(r["net_theta"]), lambda r: fnum(r["pnl_sl"]))
    tbody = "".join(
        f"<tr><td class='lbl'>{nm} theta</td><td>{rng[0]:.1f} → {rng[1]:.1f}</td>"
        f"<td class='{cls(a['net'])}'>{money(a['net'])}</td><td>{a['win']}%</td><td>{a['n']}</td></tr>"
        for nm, a, rng in tt)
    return ("<h2>Option greeks — what actually pays</h2><div class='card'>"
            "<table><tr><th>Greek</th><th>Correlation with P&amp;L</th><th>Verdict</th></tr>"
            f"{cbody}</table>"
            "<p class='muted'>Correlation: how strongly a greek tracks profit (+ helps, − hurts). "
            "Theta is the seller's engine; delta/gamma are noise on most days.</p>"
            "<table><tr><th>Theta band</th><th>Range</th><th>Net</th><th>Win</th><th>Days</th></tr>"
            f"{tbody}</table><p class='muted'>More positive net theta at entry = more decay to harvest "
            "= better days. Enter when theta is highest (near expiry, high IV).</p></div>")


def sec_oi(oi):
    pcr = buckets(oi, lambda r: fnum(r["pcr"]), lambda r: fnum(r["pnl_sl"]),
                  [0.8, 1.0, 1.2, 1.4], ["< 0.8", "0.8 - 1.0", "1.0 - 1.2", "1.2 - 1.4", "> 1.4"])
    pbody = "".join(
        f"<tr><td class='lbl'>PCR {lab}</td><td class='{cls(a['net'])}'>{money(a['net'])}</td>"
        f"<td>{a['win']}%</td><td>{a['n']}</td></tr>" for lab, a in pcr)
    mp = buckets(oi, lambda r: abs(fnum(r["mp_dist_pct"])) if fnum(r["mp_dist_pct"]) is not None else None,
                 lambda r: fnum(r["pnl_sl"]),
                 [0.3, 0.6, 1.0], ["< 0.3%", "0.3 - 0.6%", "0.6 - 1.0%", "> 1.0%"])
    mbody = "".join(
        f"<tr><td class='lbl'>{lab} from max-pain</td><td class='{cls(a['net'])}'>{money(a['net'])}</td>"
        f"<td>{a['win']}%</td><td>{a['n']}</td></tr>" for lab, a in mp)
    return ("<h2>Open-Interest scenarios</h2><div class='card'>"
            "<table><tr><th>Put/Call OI ratio</th><th>Net</th><th>Win</th><th>Days</th></tr>"
            f"{pbody}</table><p class='muted'>Very high PCR (&gt;1.4) = crowded put-writing / "
            "stretched market = straddles lose. Balanced PCR (0.8–1.2) is the sweet spot.</p>"
            "<table><tr><th>Spot distance</th><th>Net</th><th>Win</th><th>Days</th></tr>"
            f"{mbody}</table><p class='muted'>When spot sits near max-pain, pinning helps the "
            "seller. Far from max-pain = a move already underway = worse for straddles.</p></div>")


def sec_exits(strad):
    cols = [("pnl_nosl", "No stop (hold to close)"), ("pnl_sl", "88% per-leg stop"),
            ("pnl_reentry", "Stop + re-enter"),
            ("pnl_trail20", "Trail 20%"), ("pnl_trail30", "Trail 30%"),
            ("pnl_trail40", "Trail 40%"), ("pnl_trail50", "Trail 50%")]
    body = ""
    for col, nm in cols:
        a = agg([fnum(r[col]) for r in strad])
        body += (f"<tr><td class='lbl'>{nm}</td><td class='{cls(a['net'])}'>{money(a['net'])}</td>"
                 f"<td>{a['win']}%</td><td>{money(a['dd'])}</td><td>{a['n']}</td></tr>")
    return ("<h2>Exit method — how to manage the straddle</h2><div class='card'><table>"
            "<tr><th>Method</th><th>Net</th><th>Win</th><th>Max DD</th><th>Days</th></tr>"
            f"{body}</table><p class='muted'>Re-entering after a stop usually adds losses. "
            "A trailing stop keeps most of the profit while cutting the worst drawdown — "
            "the best risk-adjusted exit.</p></div>")


def sec_dte(strad):
    bk = buckets(strad, lambda r: fnum(r["dte"]), lambda r: fnum(r["pnl_sl"]),
                 [1, 2, 4, 8], ["0 (expiry day)", "1", "2 - 3", "4 - 7", "8+"])
    body = "".join(
        f"<tr><td class='lbl'>{lab}</td><td class='{cls(a['net'])}'>{money(a['net'])}</td>"
        f"<td class='{cls(a['avg'])}'>{money(a['avg'])}</td><td>{a['win']}%</td><td>{a['n']}</td></tr>"
        for lab, a in bk)
    return ("<h2>Days-to-expiry — when to be in the trade</h2><div class='card'><table>"
            "<tr><th>DTE at entry</th><th>Net</th><th>Avg/day</th><th>Win</th><th>Days</th></tr>"
            f"{body}</table><p class='muted'>Theta is fastest in the last 0–1 days — that is "
            "where selling pays. The 4–7 DTE zone is a graveyard: slow decay, full gap risk.</p></div>")


def sec_checklist():
    green = ["Expiry day or the day before", "IV above ~16 (rich premium)",
             "PCR balanced 0.8–1.2, spot near max-pain", "Positive, high net theta at entry",
             "Calm Thursday-era → plain straddle, 88% stop or trail 40–50%"]
    red = ["IV below ~12 (thin premium, no cushion)", "PCR &gt; 1.4 or spot far from max-pain",
           "4–7 days to expiry", "Day-after-expiry trend days",
           "Re-entering blindly after a stop"]
    blue = ["Tuesday-era → don't sell blindly; use COMBO or the day-specific playbook",
            "Strong one-sided OI buildup → tilt directional (buy the opposite side)",
            "Price runs &gt;0.45% from VWAP → trend-stop the straddle",
            "Monday directional → use the stop the table above favours"]
    g = "".join(f"<li>{x}</li>" for x in green)
    r = "".join(f"<li>{x}</li>" for x in red)
    b = "".join(f"<li>{x}</li>" for x in blue)
    return ("<h2>Final checklist</h2><div class='cols'>"
            f"<div class='card ok'><h3>✅ Sell premium when</h3><ul>{g}</ul></div>"
            f"<div class='card bad'><h3>⛔ Stand aside / hedge when</h3><ul>{r}</ul></div>"
            f"<div class='card info'><h3>🧭 Use indicators when</h3><ul>{b}</ul></div></div>")


def build():
    strad = load("straddle_trades")
    oi = load("oi_trades")
    byday = load("byday_trades")
    sig = load("signals_trades")
    missing = [n for n, d in [("straddle_trades", strad), ("oi_trades", oi),
                              ("byday_trades", byday), ("signals_trades", sig)] if not d]
    if missing:
        print("WARNING missing inputs:", ", ".join(missing))

    parts = []
    if byday or sig:
        parts.append(sec_tldr(byday, sig))
    if byday:
        parts.append(sec_byday(byday))
    if sig:
        parts.append(sec_signals(sig))
    if strad:
        parts.append(sec_iv(strad))
        parts.append(sec_greeks(strad))
    if oi:
        parts.append(sec_oi(oi))
    if strad:
        parts.append(sec_exits(strad))
        parts.append(sec_dte(strad))
    parts.append(sec_checklist())

    n = len(strad) or len(sig) or len(byday)
    html = PAGE.format(gen=datetime.now().strftime("%d %b %Y, %H:%M"),
                       n=n, body="\n".join(parts))
    out = DATA / "master_playbook.html"
    out.write_text(html, encoding="utf-8")
    print("wrote", out)


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NIFTY Options — Master Playbook</title>
<style>
 :root{{--bg:#0b0f17;--card:#111827;--line:#1f2937;--mut:#9ca3af;--pos:#36c660;--neg:#ef4444;--blue:#3b82f6;--amber:#f59e0b}}
 *{{box-sizing:border-box}}
 body{{background:var(--bg);color:#e5e7eb;font:15px/1.6 system-ui,Segoe UI,Arial;margin:0}}
 .wrap{{max-width:960px;margin:0 auto;padding:28px 20px 70px}}
 h1{{font-size:26px;margin:0 0 4px}}
 h2{{font-size:19px;margin:30px 0 10px;display:flex;gap:8px;align-items:center}}
 h2:before{{content:'';width:5px;height:19px;background:var(--blue);border-radius:3px}}
 h3{{font-size:15px;margin:0 0 8px}}
 .sub{{color:var(--mut);margin-bottom:18px}} .muted{{color:var(--mut);font-size:12.5px}}
 .muted2{{color:var(--mut);font-size:11.5px;margin-top:3px}}
 .card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 18px;margin:10px 0}}
 .card.hi{{border-color:#2d3a52;background:linear-gradient(180deg,#13203a,#111827)}}
 table{{border-collapse:collapse;width:100%;font-size:13px;margin:6px 0}}
 th,td{{padding:7px 9px;text-align:right;border-bottom:1px solid var(--line)}}
 th{{color:var(--mut);font-weight:600}} td.lbl,th:first-child{{text-align:left}}
 .pos{{color:var(--pos)}} .neg{{color:var(--neg)}} b{{color:#fff}}
 tr.row-hi td{{background:#13203a}}
 ul{{margin:6px 0 0;padding-left:20px}} li{{margin:3px 0}}
 .days{{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:10px}}
 .day{{border:1px solid var(--line);border-radius:10px;padding:11px 13px;border-left-width:4px}}
 .day.g{{border-left-color:var(--pos)}} .day.b{{border-left-color:var(--blue)}} .day.a{{border-left-color:var(--amber)}}
 .dh{{font-weight:700;font-size:13px;color:var(--mut);letter-spacing:.5px}}
 .dn{{font-size:13.5px;margin:2px 0 4px;color:#fff}} .dp{{font-size:13px;font-weight:600}}
 .edge{{font-size:11.5px;color:var(--pos);margin-top:2px}}
 .cols{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:10px}}
 .card.ok{{border-color:#1f4d2e}} .card.bad{{border-color:#4d2222}} .card.info{{border-color:#23395e}}
</style></head><body><div class="wrap">
<h1>NIFTY Options — Master Playbook</h1>
<div class="sub">All findings merged · {n} trading days · generated {gen} · costs &amp; slippage included</div>
{body}
<p class="muted" style="margin-top:24px">Backtested on historical data. Past results do not guarantee future returns. Live fills, slippage and liquidity may differ. For research, not investment advice.</p>
</div></body></html>"""


if __name__ == "__main__":
    build()

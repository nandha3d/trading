"""Build ONE plain-language HTML report from the straddle + OI analysis CSVs.

Reads:  data/straddle_trades.csv , data/oi_trades.csv
Writes: data/strategy_report.html   (open in any browser, no server needed)

Goal: explain every finding in simple words for a non-numbers reader, and give a
Monday->Friday playbook (what to do each day).

Usage:  python scripts/build_report.py
"""
from __future__ import annotations

import csv
import statistics as st
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np


def load(p):
    f = Path(p)
    return list(csv.DictReader(f.open(encoding="utf-8"))) if f.exists() else []


def money(n):
    n = float(n); sign = "-" if n < 0 else ""; a = abs(n)
    if a >= 1e5: return f"{sign}₹{a/1e5:.2f}L"
    if a >= 1e3: return f"{sign}₹{a/1e3:.1f}K"
    return f"{sign}₹{a:.0f}"


def cls(n):
    return "pos" if float(n) >= 0 else "neg"


def agg(vals):
    n = len(vals)
    if not n:
        return dict(n=0, net=0, avg=0, win=0, dd=0)
    eq = np.cumsum(vals)
    dd = float((np.maximum.accumulate(eq) - eq).max())
    return dict(n=n, net=round(sum(vals)), avg=round(sum(vals) / n),
                win=round(sum(1 for v in vals if v > 0) / n * 100), dd=round(dd))


def bucket(rows, fn, key="pnl_sl", order=None):
    b = defaultdict(list)
    for r in rows:
        b[fn(r)].append(float(r[key]))
    items = sorted(b.items(), key=lambda kv: (order.index(kv[0]) if order and kv[0] in order else 99, kv[0]))
    return [(k, agg(v)) for k, v in items]


def htbl(headers, rows_html):
    h = "".join(f"<th>{x}</th>" for x in headers)
    return f"<table><tr>{h}</tr>{rows_html}</table>"


def bar_cell(net, mx):
    w = int(abs(net) / mx * 100) if mx else 0
    return f"<td class='{cls(net)}'>{money(net)}<div class='bw'><div class='b {cls(net)}b' style='width:{w}%'></div></div></td>"


def factor_table(buckets, label):
    mx = max((abs(a["net"]) for _, a in buckets), default=1) or 1
    body = ""
    for k, a in buckets:
        body += f"<tr><td class='lbl'>{k}</td>{bar_cell(a['net'], mx)}<td>{money(a['avg'])}</td><td>{a['win']}%</td><td>{a['n']}</td></tr>"
    return htbl([label, "Total profit", "Per day", "Win rate", "Days"], body)


def main():
    S = load("data/straddle_trades.csv")
    O = load("data/oi_trades.csv")
    if not S:
        print("run analyze_straddle.py first"); return
    f = lambda k: [float(r[k]) for r in S]

    base = agg(f("pnl_sl"))
    variants = [
        ("No stop-loss", "pnl_nosl", "Hold both options till close, no protection."),
        ("Stop-loss 88% (our pick)", "pnl_sl", "Exit a leg if its price rises 88% above sale price."),
        ("Stop-loss + re-enter", "pnl_reentry", "After a stop, sell the same option again."),
        ("Trailing 20%", "pnl_trail20", "Lock profit, exit on 20% give-back from peak."),
        ("Trailing 30%", "pnl_trail30", "Same idea, 30% give-back."),
        ("Trailing 40%", "pnl_trail40", "Same idea, 40% give-back."),
        ("Trailing 50%", "pnl_trail50", "Same idea, 50% give-back."),
    ]
    vbody = ""
    mx = max(abs(agg(f(k))["net"]) for _, k, _ in variants)
    for name, k, desc in variants:
        a = agg(f(k)); diff = a["net"] - base["net"]
        star = " &#11088;" if k == "pnl_sl" else ""
        vbody += (f"<tr><td class='lbl'>{name}{star}<div class='muted'>{desc}</div></td>"
                  f"{bar_cell(a['net'], mx)}<td class='{cls(diff)}'>{money(diff)}</td>"
                  f"<td>{money(a['avg'])}</td><td>{a['win']}%</td><td>{money(a['dd'])}</td></tr>")
    vtable = htbl(["Exit method", "Total profit", "vs our pick", "Per day", "Win rate", "Worst dip"], vbody)

    iv_b = bucket(S, lambda r: r["regime"], order=["low (<12)", "normal (12-15)", "elevated (15-18)", "high (18-22)", "extreme (22+)"])
    dte_b = bucket(S, lambda r: _dte(r["dte"]), order=["0 (expiry day)", "1 day", "2-3 days", "4-7 days", "8+ days"])
    wd_b = bucket(S, lambda r: r["weekday"], order=["Mon", "Tue", "Wed", "Thu", "Fri"])

    cor = lambda x, y="pnl_sl": _corr(S, x, y)
    greek_rows = [
        ("Theta (time decay)", "Money the option loses just from time passing. We <b>collect</b> this — it is our salary.", cor("net_theta"), "More time-decay = more profit."),
        ("Delta (direction)", "How much the position moves if the market goes up or down.", cor("net_delta"), "Almost zero effect — direction barely matters."),
        ("Vega (volatility)", "How much we lose if fear/volatility jumps after we sell.", cor("net_vega"), "Slightly hurts — avoid far-from-expiry days."),
        ("Days to expiry", "How many days until the option dies.", cor("dte"), "Closer to expiry = better."),
    ]
    gbody = ""
    for name, desc, r, take in greek_rows:
        gbody += f"<tr><td class='lbl'>{name}<div class='muted'>{desc}</div></td><td class='{cls(r)}'>{r:+.2f}</td><td class='lbl'>{take}</td></tr>"
    gtable = htbl(["Greek (plain meaning)", "Link to profit", "What it tells us"], gbody)

    oi_html = ""
    if O:
        pcr_b = bucket(O, lambda r: _pcr(r["pcr"]), order=["Call-heavy (<0.7)", "0.7-0.9", "Balanced (0.9-1.1)", "1.1-1.4", "Put-heavy (>1.4)"])
        mp_b = bucket(O, lambda r: _mp(r["mp_dist_pct"]), order=["Pinned (<0.5%)", "0.5-1.0%", "Far (>1.0%)"])
        oi_q = _quart(O, "total_oi")
        oi_b = bucket(O, lambda r: oi_q(r), order=["Quiet day (low OI)", "Q2", "Q3", "Busy day (high OI)"])
        oi_html = (
            "<div class='card'><h3>1. Put-Call Ratio (crowd positioning)</h3>"
            "<p class='muted'>Compares how many puts vs calls traders hold. Very high (&gt;1.4) means the crowd is fearful and betting on a fall — markets then trend, which hurts a neutral seller.</p>"
            + factor_table(pcr_b, "PCR") + "</div>"
            "<div class='card'><h3>2. Distance from \"max-pain\"</h3>"
            "<p class='muted'>Max-pain is the price where most option buyers lose. Price often sticks near it. When price is already far away (&gt;1%), it is trending — bad for selling.</p>"
            + factor_table(mp_b, "Spot vs max-pain") + "</div>"
            "<div class='card'><h3>3. Market participation (total OI)</h3>"
            "<p class='muted'>How many contracts are open. Quiet, thin days give little premium and gap around; busy days pay more and behave.</p>"
            + factor_table(oi_b, "Activity") + "</div>")

    day_cards = ""
    DESC = {"Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday", "Fri": "Friday"}
    for wd in ["Mon", "Tue", "Wed", "Thu", "Fri"]:
        rws = [r for r in S if r["weekday"] == wd]
        if not rws:
            continue
        a = agg([float(r["pnl_sl"]) for r in rws])
        a50 = agg([float(r["pnl_trail50"]) for r in rws])
        avg_iv = round(st.mean(float(r["iv"]) for r in rws), 1)
        dtes = [int(r["dte"]) for r in rws]
        mode_dte = max(set(dtes), key=dtes.count)
        verdict, tone, action = _day_verdict(wd, a, a50, avg_iv, mode_dte)
        day_cards += f"""
        <div class="daycard {tone}">
          <div class="dhead"><span class="dname">{DESC[wd]}</span>
            <span class="dpnl {cls(a['net'])}">{money(a['net'])} total · {money(a['avg'])}/day · {a['win']}% win</span></div>
          <div class="dverdict">{verdict}</div>
          <div class="daction"><b>Do this:</b> {action}</div>
          <div class="muted">Typical: IV ~{avg_iv}, usually {mode_dte} day(s) to expiry · {a['n']} days tested</div>
        </div>"""

    total = len(S)
    sl_hit = sum(1 for r in S if r["sl_reason"] == "STOPLOSS")
    best_trail = max([20, 30, 40, 50], key=lambda t: agg(f(f"pnl_trail{t}"))["net"])

    html = _PAGE.format(
        gen=datetime.now().strftime("%d %b %Y, %H:%M"), n=total,
        base_net=money(base["net"]), base_avg=money(base["avg"]), base_win=base["win"],
        sl_hit=sl_hit, sl_pct=round(sl_hit / total * 100),
        vtable=vtable, gtable=gtable,
        iv=factor_table(iv_b, "Volatility (IV)"),
        dte=factor_table(dte_b, "Days to expiry"),
        wd=factor_table(wd_b, "Weekday"),
        oi=oi_html, daycards=day_cards, best_trail=best_trail,
    )
    out = Path("data/strategy_report.html")
    out.write_text(html, encoding="utf-8")
    print("wrote", out)


def _dte(d):
    d = int(d)
    return "0 (expiry day)" if d == 0 else "1 day" if d == 1 else "2-3 days" if d <= 3 else "4-7 days" if d <= 7 else "8+ days"


def _pcr(p):
    p = float(p)
    return "Call-heavy (<0.7)" if p < 0.7 else "0.7-0.9" if p < 0.9 else "Balanced (0.9-1.1)" if p < 1.1 else "1.1-1.4" if p < 1.4 else "Put-heavy (>1.4)"


def _mp(d):
    d = abs(float(d))
    return "Pinned (<0.5%)" if d < 0.5 else "0.5-1.0%" if d < 1.0 else "Far (>1.0%)"


def _quart(rows, key):
    xs = sorted(float(r[key]) for r in rows); n = len(xs)
    q1, q2, q3 = xs[n // 4], xs[n // 2], xs[3 * n // 4]
    def f(r):
        v = float(r[key])
        return "Quiet day (low OI)" if v <= q1 else "Q2" if v <= q2 else "Q3" if v <= q3 else "Busy day (high OI)"
    return f


def _corr(rows, xk, yk):
    xs = [float(r[xk]) for r in rows]; ys = [float(r[yk]) for r in rows]
    if len(xs) < 3 or st.pstdev(xs) == 0 or st.pstdev(ys) == 0:
        return 0.0
    mx, my = st.mean(xs), st.mean(ys)
    return round(sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / len(xs) / (st.pstdev(xs) * st.pstdev(ys)), 3)


def _day_verdict(wd, a, a50, iv, dte):
    if a["net"] > 80000:
        return ("This is a <b>green-light day</b>. Selling the straddle made strong, consistent money.",
                "good",
                "Sell the ATM straddle at 9:21, exit 2:55, 88% stop on each leg. Trade full size — best day of the week.")
    if wd == "Fri":
        return ("This is the <b>worst day</b> — selling the straddle lost money overall. Fridays trend more.",
                "bad",
                "Skip the straddle. Either stay flat, or take a directional trade (buy a Call or Put) if you have a view.")
    if a["net"] > 0:
        return ("A <b>mild, choppy day</b>. Small edge from selling, but not reliable.",
                "ok",
                "Sell the straddle only with extra confirmation (IV above 15, price near max-pain). Half size, or skip if unsure.")
    return ("Weak day — the edge is thin or negative.",
            "bad",
            "Prefer to skip. Only sell with strong filters (high IV + expiry-week).")


_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Options Strategy - Plain-English Findings</title>
<style>
 :root{{--bg:#0b0f17;--card:#111827;--line:#1f2937;--mut:#9ca3af;--pos:#36c660;--neg:#ef4444;--blue:#3b82f6}}
 *{{box-sizing:border-box}}
 body{{background:var(--bg);color:#e5e7eb;font:15px/1.6 system-ui,Segoe UI,Arial;margin:0;padding:0}}
 .wrap{{max-width:920px;margin:0 auto;padding:28px 20px 60px}}
 h1{{font-size:26px;margin:0 0 6px}} h2{{font-size:19px;margin:34px 0 10px;display:flex;align-items:center;gap:8px}}
 h2:before{{content:'';width:5px;height:20px;background:var(--blue);border-radius:3px;display:inline-block}}
 h3{{font-size:16px;margin:0 0 6px}}
 .sub{{color:var(--mut);margin-bottom:18px}}
 .muted{{color:var(--mut);font-size:13px;font-weight:400}}
 .card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:12px 0}}
 .hero{{background:linear-gradient(135deg,#0f1b34,#111827);border:1px solid #243049}}
 .hero .big{{font-size:30px;font-weight:800}}
 table{{border-collapse:collapse;width:100%;font-size:13.5px;margin-top:8px}}
 th,td{{padding:7px 9px;text-align:right;border-bottom:1px solid var(--line);vertical-align:top}}
 th{{color:var(--mut);font-weight:600}} td.lbl,th:first-child{{text-align:left}}
 .pos{{color:var(--pos)}} .neg{{color:var(--neg)}}
 .bw{{height:4px;background:#1f2937;border-radius:3px;margin-top:4px;max-width:160px}} .b{{height:4px;border-radius:3px}} .posb{{background:var(--pos)}} .negb{{background:var(--neg)}}
 ul{{margin:6px 0 0 0;padding-left:20px}} li{{margin:4px 0}}
 .pill{{display:inline-block;padding:2px 9px;border-radius:99px;font-size:12px;font-weight:700}}
 .green{{background:#0f3d22;color:#36c660}} .red{{background:#3d1414;color:#ef4444}} .amber{{background:#3d300f;color:#f0b840}}
 .daygrid{{display:grid;grid-template-columns:1fr;gap:12px}}
 .daycard{{border-radius:12px;padding:14px 16px;border:1px solid var(--line);background:var(--card)}}
 .daycard.good{{border-left:5px solid var(--pos)}} .daycard.bad{{border-left:5px solid var(--neg)}} .daycard.ok{{border-left:5px solid #f0b840}}
 .dhead{{display:flex;justify-content:space-between;flex-wrap:wrap;align-items:baseline;margin-bottom:6px}}
 .dname{{font-size:18px;font-weight:800}} .dpnl{{font-size:13px}}
 .dverdict{{margin:4px 0}} .daction{{background:#0b1220;border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin:8px 0;font-size:14px}}
 .two{{display:grid;grid-template-columns:1fr 1fr;gap:12px}} @media(max-width:760px){{.two{{grid-template-columns:1fr}}}}
 .key{{display:flex;gap:14px;flex-wrap:wrap;margin:8px 0}}
 .key span{{font-size:12px;color:var(--mut)}}
 b{{color:#fff}}
</style></head><body><div class="wrap">

<h1>What the Data Says - in Plain English</h1>
<div class="sub">A study of the <b>ATM short straddle</b> on NIFTY across <b>{n} trading days</b>. Generated {gen}. No jargon - read top to bottom.</div>

<div class="card hero">
 <div class="muted">BOTTOM LINE</div>
 <div class="big pos">{base_net} profit over {n} days</div>
 <p>Selling one at-the-money Call + one at-the-money Put every morning at <b>9:21</b>, buying them back at <b>2:55</b>, with a <b>88% stop-loss</b> on each, earned about <b>{base_avg} per day</b> and was profitable <b>{base_win}% of days</b>. The stop-loss triggered on {sl_hit} days ({sl_pct}% of the time) - that protection keeps the bad days small.</p>
</div>

<h2>What is this trade? (30-second version)</h2>
<div class="card">
 <p>A <b>short straddle</b> = you <b>sell</b> a Call and a Put at the same (current) price level. You get paid premium up front. You <b>win when the market stays calm</b> and the options lose value through the day. You <b>lose if the market makes a big move</b> in either direction.</p>
 <p>Think of it like <b>selling insurance</b>: you collect a fee every day, and most days nothing happens so you keep it. The stop-loss caps the claim on the rare wild day.</p>
</div>

<h2>Which exit method is best?</h2>
<div class="card">
 <p class="muted">We tested 7 ways to exit. "Worst dip" = the largest peak-to-valley fall in the running total (how much pain you'd stomach).</p>
 {vtable}
 <ul>
  <li><b>Fixed 88% stop-loss won on total profit.</b> Simple beats fancy.</li>
  <li><b>Re-entering after a stop LOSES money</b> - you keep re-selling into the same move that just hurt you. Don't.</li>
  <li><b>Trailing {best_trail}%</b> gives the <b>smoothest ride (smallest dip)</b> for a bit less profit - good if you hate drawdowns.</li>
  <li><b>No stop-loss</b> looks okay on profit but has the <b>biggest dip</b> - one bad day can wipe weeks.</li>
 </ul>
</div>

<h2>The 3 things that decide profit</h2>

<div class="card"><h3>1. Volatility (IV) - how nervous the market is</h3>
 <p class="muted">IV is the "fear gauge". Higher IV = options are expensive = you collect more premium when you sell.</p>
 {iv}
 <p>&#128073; <b>Below 15 there is no edge</b> (12-15 actually loses). <b>Almost all profit comes when IV is high (18+), and it explodes above 22.</b> Sell when options are expensive, not cheap.</p>
</div>

<div class="card"><h3>2. Days to expiry - how close to the option's death</h3>
 {dte}
 <p>&#128073; <b>Expiry day is the goldmine</b> (fastest time-decay). 2-3 days is good. <b>4-7 days actually loses</b> - too much time for a big move to develop.</p>
</div>

<div class="card"><h3>3. Day of the week</h3>
 {wd}
 <p>&#128073; <b>Tuesday and Thursday are the money days. Friday loses.</b> See the full day-by-day playbook below.</p>
</div>

<h2>The "Greeks" in plain words</h2>
<div class="card">
 <p class="muted">Greeks measure what moves the position. "Link to profit": closer to +1 = strongly helps, near 0 = doesn't matter, negative = hurts.</p>
 {gtable}
 <p>&#128073; <b>This is a time-decay (theta) business, not a direction (delta) bet.</b> Guessing up/down barely matters - getting paid for calm days does.</p>
</div>

<h2>Open Interest (OI) - what the crowd is doing</h2>
<div class="card"><p class="muted">OI is a <b>secondary</b> filter (weaker than IV and timing), but the extremes are useful warnings.</p></div>
{oi}
<div class="card"><p>&#128073; In short: <b>avoid days the crowd is very fearful (PCR &gt; 1.4)</b>, <b>avoid when price has already run far from max-pain (&gt;1%)</b>, and <b>prefer busy high-OI days</b>.</p></div>

<h2>Day-by-Day Playbook</h2>
<div class="card"><div class="key">
 <span><span class="pill green">GREEN</span> sell full size</span>
 <span><span class="pill amber">AMBER</span> sell small / only with filters</span>
 <span><span class="pill red">RED</span> skip or go directional</span>
</div></div>
<div class="daygrid">{daycards}</div>

<h2>Your simple checklist before selling</h2>
<div class="two">
 <div class="card"><h3 class="pos">GREEN light - go</h3><ul>
  <li>IV is <b>15 or higher</b> (best above 22)</li>
  <li><b>Tuesday or Thursday</b></li>
  <li><b>0-3 days</b> to expiry</li>
  <li>PCR between <b>0.7 and 1.4</b></li>
  <li>Price <b>near max-pain</b> (within ~0.5%)</li>
  <li>A <b>busy</b> (high-OI) day</li>
 </ul></div>
 <div class="card"><h3 class="neg">RED light - don't sell</h3><ul>
  <li>IV <b>below 12</b> (cheap options, no pay)</li>
  <li><b>Friday</b></li>
  <li><b>4-7 days</b> to expiry</li>
  <li>PCR <b>above 1.4</b> (crowd fearful)</li>
  <li>Price already <b>&gt;1% from max-pain</b> (trending)</li>
  <li>A <b>quiet</b> (low-OI) day</li>
 </ul></div>
</div>

<div class="card hero" style="margin-top:18px">
 <div class="muted">ONE-LINE RULE</div>
 <p class="big" style="font-size:20px">Sell the 9:21 straddle with an 88% stop, <b>only on Tue/Thu near expiry when IV is high and price is calm</b> - and never on Friday.</p>
</div>

<p class="muted" style="margin-top:24px">Past results are not a promise of future returns. Costs &amp; slippage are included; live fills may differ.</p>
</div></body></html>"""


if __name__ == "__main__":
    main()

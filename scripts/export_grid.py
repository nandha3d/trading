"""Run the ATM straddle grid sweep and export results to CSV (Excel) + standalone HTML.

Usage:
    python scripts/export_grid.py NIFTY 2023-01-02 2026-04-13

Outputs (in data/):
    grid_<UNDERLYING>_full.csv   -> open in Excel, all combos
    grid_<UNDERLYING>_full.html  -> self-contained heatmap + best + sortable table
"""
from __future__ import annotations

import csv
import json
import sys
import time
from datetime import date, datetime, time as dtime
from pathlib import Path

# allow "python scripts/export_grid.py" from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest import grid  # noqa: E402


def _t(s: str) -> dtime:
    h, m = map(int, s.split(":"))
    return dtime(h, m)


def main() -> None:
    args = sys.argv[1:]
    underlying = args[0] if len(args) > 0 else "NIFTY"
    start = date.fromisoformat(args[1]) if len(args) > 1 else date(2023, 1, 2)
    end = date.fromisoformat(args[2]) if len(args) > 2 else date(2026, 4, 13)
    entry_start = _t(args[3]) if len(args) > 3 else dtime(9, 18)
    entry_end = _t(args[4]) if len(args) > 4 else dtime(13, 0)
    exit_time = _t(args[5]) if len(args) > 5 else dtime(14, 55)

    t0 = time.time()
    res = grid.run_straddle_grid(
        underlying, start, end,
        entry_start=entry_start, entry_end=entry_end, exit_time=exit_time,
        sl_lo=10.0, sl_hi=100.0, sl_step=1.0, entry_step_min=1,
    )
    secs = round(time.time() - t0, 1)
    cells = res.cells
    print(f"swept {len(cells)} combos over {res.days_used} days in {secs}s")

    out = Path("data")
    out.mkdir(exist_ok=True)
    csv_path = out / f"grid_{underlying}_full.csv"
    html_path = out / f"grid_{underlying}_full.html"

    # ---- CSV (Excel) ----
    cols = ["entry_time", "sl_pct", "net", "gross", "cost", "trades", "wins",
            "win_rate", "avg", "max_dd"]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for c in sorted(cells, key=lambda c: c.net, reverse=True):
            w.writerow([c.entry_time, c.sl_pct, c.net, c.gross, c.cost, c.trades,
                        c.wins, round(c.win_rate * 100, 2), c.avg, c.max_dd])
    print(f"wrote {csv_path}")

    # ---- HTML (self-contained) ----
    payload = {
        "underlying": underlying,
        "start": start.isoformat(), "end": end.isoformat(),
        "exit": exit_time.strftime("%H:%M"),
        "days": res.days_used, "secs": secs,
        "entry_times": res.entry_times, "sl_values": res.sl_values,
        "best": vars(res.best) if res.best else None,
        "cells": [vars(c) for c in cells],
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    html_path.write_text(_HTML.replace("__DATA__", json.dumps(payload)), encoding="utf-8")
    print(f"wrote {html_path}")
    if res.best:
        b = res.best
        print(f"BEST entry {b.entry_time} SL {b.sl_pct}% net {b.net} win {b.win_rate:.1%} dd {b.max_dd}")


_HTML = r"""<!doctype html><html><head><meta charset="utf-8">
<title>Straddle Grid Sweep</title>
<style>
 body{background:#0b0f17;color:#e5e7eb;font:13px/1.4 system-ui,Segoe UI,Arial;margin:0;padding:24px}
 h1{font-size:20px;margin:0 0 4px} .sub{color:#9ca3af;margin-bottom:18px}
 .cards{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px}
 .card{background:#111827;border:1px solid #1f2937;border-radius:10px;padding:12px 16px;min-width:120px}
 .card .l{color:#9ca3af;font-size:11px} .card .v{font-size:18px;font-weight:700}
 .pos{color:#36c660}.neg{color:#ef4444}
 .panel{background:#111827;border:1px solid #1f2937;border-radius:10px;padding:16px;margin-bottom:20px}
 canvas{image-rendering:pixelated;cursor:crosshair;max-width:100%}
 table{border-collapse:collapse;width:100%;font-size:12px}
 th,td{padding:5px 8px;text-align:right;border-bottom:1px solid #1f2937}
 th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}
 th{color:#9ca3af;cursor:pointer;user-select:none;position:sticky;top:0;background:#111827}
 th:hover{color:#fff} tr:hover td{background:#1f2937}
 .legend{display:flex;align-items:center;gap:8px;font-size:11px;color:#9ca3af}
 .bar{width:120px;height:10px;border-radius:4px;background:linear-gradient(90deg,#d23030,#1f2937,#36c660)}
 #tip{position:fixed;background:#1f2937;border:1px solid #374151;border-radius:6px;padding:6px 8px;font-size:12px;pointer-events:none;display:none;z-index:9}
 .axis{display:flex;justify-content:space-between;color:#6b7280;font-size:11px;margin-top:4px}
</style></head><body>
<h1>ATM Short Straddle — Grid Sweep</h1>
<div class="sub" id="sub"></div>
<div class="cards" id="cards"></div>
<div class="panel">
 <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
  <b>Heatmap — entry time (X) × stop-loss% (Y), color = net P&amp;L</b>
  <div class="legend"><span>loss</span><span class="bar"></span><span>profit</span></div>
 </div>
 <canvas id="hm"></canvas>
 <div class="axis"><span id="ex0"></span><span id="ex1"></span></div>
 <div style="color:#6b7280;font-size:11px">Y: SL top→bottom low→high · white box = best</div>
</div>
<div class="panel">
 <b>All combos (click header to sort) — showing top 200; full set in CSV</b>
 <div style="max-height:520px;overflow:auto;margin-top:8px"><table id="tbl"></table></div>
</div>
<div id="tip"></div>
<script>
const D=__DATA__;
const fmt=n=>Math.abs(n)>=1e5?(n/1e5).toFixed(2)+'L':Math.abs(n)>=1e3?(n/1e3).toFixed(1)+'K':(+n).toFixed(0);
document.getElementById('sub').textContent=
 `${D.underlying} · ${D.start} → ${D.end} · exit ${D.exit} · ${D.days} trading days · ${D.cells.length} combos · swept in ${D.secs}s · generated ${D.generated}`;
const maxAbs=D.cells.reduce((a,c)=>Math.max(a,Math.abs(c.net)),0);
function color(net){if(maxAbs<=0)return'#1f2937';let t=Math.max(-1,Math.min(1,net/maxAbs));
 if(t>=0){let g=Math.round(60+150*t);return`rgb(${Math.round(40*(1-t))},${g},${Math.round(60*(1-t))+40})`;}
 let r=Math.round(60+150*-t);return`rgb(${r},${Math.round(40*(1+t))},${Math.round(40*(1+t))})`;}
// cards
const b=D.best;
if(b){const C=document.getElementById('cards');
 const mk=(l,v,cls)=>`<div class="card"><div class="l">${l}</div><div class="v ${cls||''}">${v}</div></div>`;
 C.innerHTML=mk('Best entry',b.entry_time)+mk('Best SL %',b.sl_pct+'%')
  +mk('Net P&L','₹'+fmt(b.net),b.net>=0?'pos':'neg')
  +mk('Win rate',(b.win_rate*100).toFixed(1)+'%')+mk('Trades',b.trades)
  +mk('Max DD','₹'+fmt(b.max_dd))+mk('Avg/trade','₹'+fmt(b.avg));}
// heatmap
const ets=D.entry_times,sls=D.sl_values,CW=5,CH=4;
const map=new Map();D.cells.forEach(c=>map.set(c.entry_time+'|'+c.sl_pct,c));
const cv=document.getElementById('hm');cv.width=ets.length*CW;cv.height=sls.length*CH;
const cx=cv.getContext('2d');cx.fillStyle='#0b0f17';cx.fillRect(0,0,cv.width,cv.height);
for(let x=0;x<ets.length;x++)for(let y=0;y<sls.length;y++){const c=map.get(ets[x]+'|'+sls[y]);if(!c)continue;cx.fillStyle=color(c.net);cx.fillRect(x*CW,y*CH,CW,CH);}
if(b){const bx=ets.indexOf(b.entry_time),by=sls.indexOf(b.sl_pct);if(bx>=0&&by>=0){cx.strokeStyle='#fff';cx.lineWidth=1.5;cx.strokeRect(bx*CW-1,by*CH-1,CW+2,CH+2);}}
document.getElementById('ex0').textContent='entry '+ets[0]+' →';
document.getElementById('ex1').textContent='→ '+ets[ets.length-1];
const tip=document.getElementById('tip');
cv.addEventListener('mousemove',e=>{const r=cv.getBoundingClientRect();
 const x=Math.floor((e.clientX-r.left)/r.width*ets.length),y=Math.floor((e.clientY-r.top)/r.height*sls.length);
 const c=map.get(ets[x]+'|'+sls[y]);if(!c){tip.style.display='none';return;}
 tip.style.display='block';tip.style.left=(e.clientX+12)+'px';tip.style.top=(e.clientY+12)+'px';
 tip.innerHTML=`<b>${c.entry_time} · SL ${c.sl_pct}%</b><br><span class="${c.net>=0?'pos':'neg'}">net ₹${fmt(c.net)}</span><br>win ${(c.win_rate*100).toFixed(0)}% · ${c.trades} trades<br>avg ₹${fmt(c.avg)} · DD ₹${fmt(c.max_dd)}`;});
cv.addEventListener('mouseleave',()=>tip.style.display='none');
// table (top 200, sortable)
const cols=[['entry_time','Entry'],['sl_pct','SL%'],['net','Net'],['win_rate','Win%'],['trades','Trades'],['avg','Avg'],['max_dd','MaxDD'],['gross','Gross'],['cost','Cost']];
let rows=[...D.cells].sort((a,b)=>b.net-a.net).slice(0,200),sortKey='net',asc=false;
function draw(){const t=document.getElementById('tbl');
 t.innerHTML='<thead><tr>'+cols.map(c=>`<th data-k="${c[0]}">${c[1]}</th>`).join('')+'</tr></thead><tbody>'
 +rows.map(r=>`<tr><td>${r.entry_time}</td><td>${r.sl_pct}</td>
   <td class="${r.net>=0?'pos':'neg'}">₹${fmt(r.net)}</td><td>${(r.win_rate*100).toFixed(1)}</td>
   <td>${r.trades}</td><td>₹${fmt(r.avg)}</td><td>₹${fmt(r.max_dd)}</td>
   <td>₹${fmt(r.gross)}</td><td>₹${fmt(r.cost)}</td></tr>`).join('')+'</tbody>';
 t.querySelectorAll('th').forEach(th=>th.onclick=()=>{const k=th.dataset.k;asc=(k===sortKey)?!asc:false;sortKey=k;
  rows.sort((a,b)=>{const x=a[k],y=b[k];return (x<y?-1:x>y?1:0)*(asc?1:-1);});draw();});}
draw();
</script></body></html>"""


if __name__ == "__main__":
    main()

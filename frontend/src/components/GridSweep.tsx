import { useEffect, useRef, useState, useMemo } from "react";
import { runGrid } from "../api";
import type { GridRequest, GridResponse, GridCell } from "../types";

const DEFAULT: GridRequest = {
  underlying: "NIFTY",
  start: "2023-01-02",
  end: "2026-04-13",
  entry_start: "09:18",
  entry_end: "13:00",
  exit_time: "14:55",
  sl_lo: 10,
  sl_hi: 100,
  sl_step: 1,
  entry_step_min: 1,
  expiry_offset: 0,
  lots: 1,
};

const fmt = (n: number) =>
  Math.abs(n) >= 1e5 ? `${(n / 1e5).toFixed(2)}L` : Math.abs(n) >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : n.toFixed(0);

// diverging red->green around 0, scaled by max abs magnitude
function color(net: number, maxAbs: number): string {
  if (maxAbs <= 0) return "#1f2937";
  const t = Math.max(-1, Math.min(1, net / maxAbs));
  if (t >= 0) {
    const g = Math.round(60 + 150 * t);
    return `rgb(${Math.round(40 * (1 - t))},${g},${Math.round(60 * (1 - t)) + 40})`;
  }
  const r = Math.round(60 + 150 * -t);
  return `rgb(${r},${Math.round(40 * (1 + t))},${Math.round(40 * (1 + t))})`;
}

export default function GridSweep() {
  const [req, setReq] = useState<GridRequest>(DEFAULT);
  const [res, setRes] = useState<GridResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [hover, setHover] = useState<{ x: number; y: number; cell: GridCell } | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const cellMap = useMemo(() => {
    const m = new Map<string, GridCell>();
    res?.cells.forEach((c) => m.set(`${c.entry_time}|${c.sl_pct}`, c));
    return m;
  }, [res]);

  const maxAbs = useMemo(() => {
    if (!res) return 0;
    return res.cells.reduce((a, c) => Math.max(a, Math.abs(c.net)), 0);
  }, [res]);

  const CW = 5, CH = 4;

  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv || !res) return;
    const nx = res.entry_times.length, ny = res.sl_values.length;
    cv.width = nx * CW;
    cv.height = ny * CH;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    ctx.fillStyle = "#0b0f17";
    ctx.fillRect(0, 0, cv.width, cv.height);
    for (let xi = 0; xi < nx; xi++) {
      for (let yi = 0; yi < ny; yi++) {
        const c = cellMap.get(`${res.entry_times[xi]}|${res.sl_values[yi]}`);
        if (!c) continue;
        ctx.fillStyle = color(c.net, maxAbs);
        ctx.fillRect(xi * CW, yi * CH, CW, CH);
      }
    }
    // mark best with white box
    if (res.best) {
      const bx = res.entry_times.indexOf(res.best.entry_time);
      const by = res.sl_values.indexOf(res.best.sl_pct);
      if (bx >= 0 && by >= 0) {
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 1.5;
        ctx.strokeRect(bx * CW - 1, by * CH - 1, CW + 2, CH + 2);
      }
    }
  }, [res, cellMap, maxAbs]);

  async function run() {
    setLoading(true);
    setErr(null);
    setHover(null);
    try {
      setRes(await runGrid(req));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  function onMove(e: React.MouseEvent<HTMLCanvasElement>) {
    if (!res) return;
    const r = canvasRef.current!.getBoundingClientRect();
    const xi = Math.floor(((e.clientX - r.left) / r.width) * res.entry_times.length);
    const yi = Math.floor(((e.clientY - r.top) / r.height) * res.sl_values.length);
    const c = cellMap.get(`${res.entry_times[xi]}|${res.sl_values[yi]}`);
    if (c) setHover({ x: e.clientX, y: e.clientY, cell: c });
    else setHover(null);
  }

  const top = useMemo(
    () => (res ? [...res.cells].sort((a, b) => b.net - a.net).slice(0, 12) : []),
    [res]
  );

  const num = (k: keyof GridRequest) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setReq({ ...req, [k]: Number(e.target.value) });
  const str = (k: keyof GridRequest) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setReq({ ...req, [k]: e.target.value });

  const F = ({ label, children }: { label: string; children: React.ReactNode }) => (
    <label className="flex flex-col gap-1 text-xs text-gray-400">
      {label}
      {children}
    </label>
  );
  const inp = "bg-gray-950 border border-gray-700 rounded px-2 py-1 text-gray-100 text-sm w-full";

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold">Auto Sweep — ATM Short Straddle</h2>
        <p className="text-sm text-gray-500">
          Brute-force every entry-time × stop-loss% combo over the range. SELL ATM CE + PE,
          same SL% per leg, exit by time. Ranked by net P&amp;L.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 bg-gray-900 border border-gray-800 rounded-lg p-4">
        <F label="Underlying">
          <select className={inp} value={req.underlying} onChange={str("underlying")}>
            <option>NIFTY</option>
            <option>BANKNIFTY</option>
            <option>FINNIFTY</option>
          </select>
        </F>
        <F label="Start"><input type="date" className={inp} value={req.start} onChange={str("start")} /></F>
        <F label="End"><input type="date" className={inp} value={req.end} onChange={str("end")} /></F>
        <F label="Entry from"><input type="time" className={inp} value={req.entry_start} onChange={str("entry_start")} /></F>
        <F label="Entry to"><input type="time" className={inp} value={req.entry_end} onChange={str("entry_end")} /></F>
        <F label="Exit"><input type="time" className={inp} value={req.exit_time} onChange={str("exit_time")} /></F>
        <F label="SL low %"><input type="number" className={inp} value={req.sl_lo} onChange={num("sl_lo")} /></F>
        <F label="SL high %"><input type="number" className={inp} value={req.sl_hi} onChange={num("sl_hi")} /></F>
        <F label="SL step %"><input type="number" className={inp} value={req.sl_step} onChange={num("sl_step")} /></F>
        <F label="Entry step min"><input type="number" className={inp} value={req.entry_step_min} onChange={num("entry_step_min")} /></F>
        <F label="Lots"><input type="number" className={inp} value={req.lots} onChange={num("lots")} /></F>
        <F label="Expiry offset"><input type="number" className={inp} value={req.expiry_offset} onChange={num("expiry_offset")} /></F>
        <div className="flex items-end col-span-2">
          <button
            onClick={run}
            disabled={loading}
            className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded px-4 py-2 text-sm font-semibold w-full"
          >
            {loading ? "Sweeping…" : "Run Sweep"}
          </button>
        </div>
      </div>

      {err && <div className="text-red-400 text-sm bg-red-950/40 border border-red-900 rounded p-3">{err}</div>}

      {loading && (
        <div className="text-gray-400 text-sm animate-pulse">
          Scanning full range month-by-month… ~20k combos. Multi-year ranges can take a few minutes.
        </div>
      )}

      {res && res.best && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <Stat label="Best entry" value={res.best.entry_time} />
          <Stat label="Best SL %" value={`${res.best.sl_pct}%`} />
          <Stat label="Net P&L" value={`₹${fmt(res.best.net)}`} good={res.best.net >= 0} />
          <Stat label="Win rate" value={`${(res.best.win_rate * 100).toFixed(1)}%`} />
          <Stat label="Max DD" value={`₹${fmt(res.best.max_dd)}`} />
        </div>
      )}

      {res && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold">
              Heatmap · {res.entry_times.length} entries × {res.sl_values.length} SL ·{" "}
              {res.days_used} days · {res.cells.length} combos
            </h3>
            <div className="flex items-center gap-2 text-[10px] text-gray-500">
              <span>loss</span>
              <span className="inline-block w-24 h-2 rounded" style={{ background: "linear-gradient(90deg,#d23030,#1f2937,#36c660)" }} />
              <span>profit</span>
            </div>
          </div>
          <div className="relative overflow-auto">
            <canvas
              ref={canvasRef}
              onMouseMove={onMove}
              onMouseLeave={() => setHover(null)}
              className="cursor-crosshair"
              style={{ imageRendering: "pixelated", width: "100%", maxWidth: `${res.entry_times.length * 5}px` }}
            />
            <div className="flex justify-between text-[10px] text-gray-500 mt-1">
              <span>entry {res.entry_times[0]} →</span>
              <span>→ {res.entry_times[res.entry_times.length - 1]}</span>
            </div>
            <div className="text-[10px] text-gray-500">
              Y axis: SL {res.sl_values[0]}% (top) → {res.sl_values[res.sl_values.length - 1]}% (bottom) · white box = best
            </div>
          </div>
          {hover && (
            <div
              className="fixed z-50 bg-gray-800 border border-gray-600 rounded px-2 py-1 text-xs pointer-events-none shadow-lg"
              style={{ left: hover.x + 12, top: hover.y + 12 }}
            >
              <div className="font-semibold">{hover.cell.entry_time} · SL {hover.cell.sl_pct}%</div>
              <div className={hover.cell.net >= 0 ? "text-green-400" : "text-red-400"}>net ₹{fmt(hover.cell.net)}</div>
              <div className="text-gray-400">win {(hover.cell.win_rate * 100).toFixed(0)}% · {hover.cell.trades} trades · avg ₹{fmt(hover.cell.avg)}</div>
              <div className="text-gray-400">maxDD ₹{fmt(hover.cell.max_dd)}</div>
            </div>
          )}
        </div>
      )}

      {top.length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <h3 className="text-sm font-semibold mb-2">Top 12 combos by net P&amp;L</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-500 text-xs border-b border-gray-800">
                <th className="text-left py-1">#</th>
                <th className="text-left">Entry</th>
                <th className="text-right">SL %</th>
                <th className="text-right">Net</th>
                <th className="text-right">Win %</th>
                <th className="text-right">Trades</th>
                <th className="text-right">Avg</th>
                <th className="text-right">Max DD</th>
              </tr>
            </thead>
            <tbody>
              {top.map((c, i) => (
                <tr key={i} className="border-b border-gray-800/50 hover:bg-gray-800/40">
                  <td className="py-1 text-gray-500">{i + 1}</td>
                  <td className="font-mono">{c.entry_time}</td>
                  <td className="text-right">{c.sl_pct}</td>
                  <td className={`text-right font-semibold ${c.net >= 0 ? "text-green-400" : "text-red-400"}`}>₹{fmt(c.net)}</td>
                  <td className="text-right">{(c.win_rate * 100).toFixed(1)}</td>
                  <td className="text-right text-gray-400">{c.trades}</td>
                  <td className="text-right text-gray-400">₹{fmt(c.avg)}</td>
                  <td className="text-right text-gray-400">₹{fmt(c.max_dd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, good }: { label: string; value: string; good?: boolean }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-3">
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`text-lg font-bold ${good === undefined ? "text-gray-100" : good ? "text-green-400" : "text-red-400"}`}>
        {value}
      </div>
    </div>
  );
}

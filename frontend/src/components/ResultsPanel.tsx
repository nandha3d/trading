import { useMemo, useState, useEffect } from "react";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
  BarChart, Bar, Cell,
} from "recharts";
import type { BacktestResponse, TradeResult } from "../types";
import TradeDrawer from "./TradeDrawer";
import { getBacktestAnalytics, getSlippageSensitivity, exportBacktestUrl } from "../api";

interface Props { result: BacktestResponse }

const INR = (n: number) => {
  const abs = Math.abs(n);
  const s = abs >= 1000 ? abs.toLocaleString("en-IN", { maximumFractionDigits: 0 }) : abs.toFixed(0);
  return `${n < 0 ? "-" : ""}₹${s}`;
};
const fmt2 = (n: number) => n.toFixed(2);

const EXIT_COLOR: Record<string, string> = {
  TARGET: "text-green-400", STOPLOSS: "text-red-400",
  TRAIL: "text-yellow-400", TIME: "text-gray-500", MIXED: "text-blue-400",
};
const EXIT_DOT: Record<string, string> = {
  TARGET: "text-green-400", STOPLOSS: "text-red-400", TRAIL: "text-yellow-400",
};
const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"
];
const WEEKDAYS_SHORT = ["S", "M", "T", "W", "T", "F", "S"];

const parseDate = (dStr: string) => {
  const [y, m, d] = dStr.split("-").map(Number);
  return new Date(y, m - 1, d);
};

function getDte(t: TradeResult) {
  if (!t.expiry) return 0;
  const d1 = parseDate(t.day);
  const d2 = parseDate(t.expiry);
  return Math.round((d2.getTime() - d1.getTime()) / (1000 * 60 * 60 * 24));
};

function buildGrid(trades: TradeResult[]) {
  const g: Record<number, Record<number, number>> = {}, yp: Record<number, number[]> = {};
  for (const t of trades) {
    const d = parseDate(t.day), y = d.getFullYear(), m = d.getMonth();
    if (!g[y]) g[y] = {};
    g[y][m] = (g[y][m] ?? 0) + t.net;
    (yp[y] = yp[y] ?? []).push(t.net);
  }
  const ym: Record<number, number> = {};
  for (const [y, ns] of Object.entries(yp)) {
    let eq = 0, pk = 0, mdd = 0;
    for (const n of ns) { eq += n; pk = Math.max(pk, eq); mdd = Math.min(mdd, eq - pk); }
    ym[parseInt(y)] = mdd;
  }
  return { g, ym, years: Object.keys(g).map(Number).sort() };
}

function getMonthGrid(year: number, monthIndex: number) {
  const firstDay = new Date(year, monthIndex, 1);
  const startOffset = firstDay.getDay();
  const totalDays = new Date(year, monthIndex + 1, 0).getDate();
  const cells: { dayNum: number | null; dateStr: string | null }[] = [];
  
  for (let i = 0; i < startOffset; i++) {
    cells.push({ dayNum: null, dateStr: null });
  }
  
  for (let d = 1; d <= totalDays; d++) {
    const dateStr = `${year}-${String(monthIndex + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    cells.push({ dayNum: d, dateStr });
  }
  
  while (cells.length % 7 !== 0) {
    cells.push({ dayNum: null, dateStr: null });
  }
  
  return cells;
}

function Card({ label, val, color, tooltip }: { label: string; val: string; color: string; tooltip?: string }) {
  return (
    <div className="bg-gray-900 rounded-xl p-4 border border-gray-800 hover:border-gray-700 transition-all duration-200 shadow-lg" title={tooltip}>
      <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1 font-medium">{label}</div>
      <div className={`text-lg font-bold leading-tight ${color}`}>{val}</div>
    </div>
  );
}

function MCell({ val }: { val: number | undefined }) {
  if (val === undefined) return <td className="px-2 py-1.5 text-center text-gray-700 text-xs font-mono">—</td>;
  return <td className={`px-2 py-1.5 text-center text-xs font-mono font-medium ${val >= 0 ? "text-green-400 bg-green-400/5" : "text-red-400 bg-red-400/5"}`}>{INR(val)}</td>;
}

const hm = (iso?: string | null) => (iso ? iso.slice(11, 16) : "—");

export default function ResultsPanel({ result }: Props) {
  const { trades: raw, run_id: runId } = result;
  const executed = useMemo(() => raw.filter((t) => !t.skip_reason), [raw]);
  const [selectedTrade, setSelectedTrade] = useState<TradeResult | null>(null);
  
  // Tabs: report, risk, monte_carlo, logs
  const [tab, setTab] = useState<"report" | "risk" | "monte_carlo" | "logs">("report");
  
  // API states
  const [analytics, setAnalytics] = useState<any>(null);
  const [slippageData, setSlippageData] = useState<any[]>([]);
  const [loadingAnalytics, setLoadingAnalytics] = useState(false);
  const [loadingSlippage, setLoadingSlippage] = useState(false);

  useEffect(() => {
    if (runId) {
      setLoadingAnalytics(true);
      getBacktestAnalytics(runId)
        .then(setAnalytics)
        .catch(() => setAnalytics(null))
        .finally(() => setLoadingAnalytics(false));

      setLoadingSlippage(true);
      getSlippageSensitivity(runId, [0, 0.01, 0.03, 0.05, 0.10])
        .then((res) => setSlippageData(res.rows || []))
        .catch(() => setSlippageData([]))
        .finally(() => setLoadingSlippage(false));
    }
  }, [runId]);

  const nets = useMemo(() => executed.map((t) => t.net), [executed]);
  const wins = useMemo(() => nets.filter((n) => n > 0), [nets]);
  const losses = useMemo(() => nets.filter((n) => n <= 0), [nets]);
  const net_pnl = useMemo(() => nets.reduce((a, b) => a + b, 0), [nets]);
  
  const wr = useMemo(() => nets.length ? wins.length / nets.length : 0, [nets, wins]);
  const aw = useMemo(() => wins.length ? wins.reduce((a, b) => a + b, 0) / wins.length : 0, [wins]);
  const al = useMemo(() => losses.length ? Math.abs(losses.reduce((a, b) => a + b, 0)) / losses.length : 0, [losses]);
  const rr = useMemo(() => al > 0 ? aw / al : 0, [aw, al]);
  const expectancy = useMemo(() => nets.length ? net_pnl / nets.length : 0, [nets, net_pnl]);

  const mdd = useMemo(() => {
    let eq = 0, pk = 0, d = 0;
    for (const n of nets) { eq += n; pk = Math.max(pk, eq); d = Math.min(d, eq - pk); }
    return d;
  }, [nets]);

  const rmdd = useMemo(() => mdd !== 0 ? net_pnl / Math.abs(mdd) : 0, [net_pnl, mdd]);

  const sharpe = useMemo(() => {
    if (nets.length < 2) return 0;
    const mean = net_pnl / nets.length;
    const sd = Math.sqrt(nets.reduce((s, n) => s + (n - mean) ** 2, 0) / (nets.length - 1));
    return sd ? (mean / sd) * Math.sqrt(252) : 0;
  }, [nets, net_pnl]);

  const ec = useMemo(() => executed.reduce<number[]>((a, t) => [...a, (a[a.length - 1] ?? 0) + t.net], [0]), [executed]);
  const chartData = useMemo(() => ec.map((v, i) => ({ i, pnl: v, date: i > 0 ? executed[i - 1]?.day : "Start" })), [ec, executed]);
  
  const { g, ym, years } = useMemo(() => buildGrid(executed), [executed]);

  const [hoverCell, setHoverCell] = useState<{ x: number; y: number; date: string; pnl: number | undefined } | null>(null);
  const [monthDetail, setMonthDetail] = useState<{ y: number; m: number } | null>(null);

  const dailyPnlMap = useMemo(() => {
    const map: Record<string, number> = {};
    for (const t of executed) {
      const dStr = t.day;
      map[dStr] = (map[dStr] ?? 0) + t.net;
    }
    return map;
  }, [executed]);

  const weekdayChartData = useMemo(() => {
    const days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];
    const pnlByDay = [0, 0, 0, 0, 0];
    for (const t of executed) {
      const wd = parseDate(t.day).getDay(); 
      if (wd >= 1 && wd <= 5) {
        pnlByDay[wd - 1] += t.net;
      }
    }
    return days.map((name, i) => ({
      name,
      pnl: pnlByDay[i],
    }));
  }, [executed]);

  const handleCsvExport = () => {
    if (runId) {
      window.open(exportBacktestUrl(runId), "_blank");
    }
  };

  return (
    <div className="space-y-6">
      
      {/* Top action and tab bar */}
      <div className="flex items-center justify-between border-b border-gray-800 pb-3 flex-wrap gap-3">
        <div className="flex bg-gray-900 rounded-xl p-0.5 border border-gray-800">
          {(["report", "risk", "monte_carlo", "logs"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-1.5 rounded-lg text-xs font-bold uppercase transition-all ${
                tab === t ? "bg-blue-600 text-white shadow-md shadow-blue-900/30" : "text-gray-400 hover:text-gray-200"
              }`}
            >
              {t === "report" ? "📈 Report" : t === "risk" ? "⚠️ Overfitting & Risk" : t === "monte_carlo" ? "🎲 Monte Carlo" : "📋 Execution Logs"}
            </button>
          ))}
        </div>
        
        {runId && (
          <button
            onClick={handleCsvExport}
            className="px-3.5 py-1.5 bg-gray-900 hover:bg-gray-850 border border-gray-800 rounded-xl text-xs font-bold text-gray-300 transition-all flex items-center gap-1.5"
          >
            📥 Export CSV Logs
          </button>
        )}
      </div>

      {tab === "report" && (
        <div className="space-y-6">
          {/* Stats 4×4 Grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3.5">
            <Card label="Total Trades" val={String(nets.length)} color="text-white" />
            <Card label="Win Rate" val={`${(wr*100).toFixed(1)}%`} color={wr >= 0.5 ? "text-green-400" : "text-red-400"} />
            <Card label="Net PnL" val={INR(net_pnl)} color={net_pnl >= 0 ? "text-green-400" : "text-red-400"} />
            <Card label="Expectancy" val={INR(expectancy)+"/trade"} color={expectancy >= 0 ? "text-green-400" : "text-red-400"} tooltip="Average P&L per executed trade" />
            
            <Card label="Avg Win" val={INR(aw)} color="text-green-400" />
            <Card label="Avg Loss" val={INR(al)} color="text-red-400" />
            <Card label="Risk Reward" val={`1 : ${fmt2(rr)}`} color={rr >= 1.0 ? "text-green-400" : "text-yellow-400"} />
            <Card label="Profit Factor" val={isFinite(net_pnl) ? fmt2(wins.reduce((a,b)=>a+b,0) / Math.max(1, Math.abs(losses.reduce((a,b)=>a+b,0)))) : "—"} color="text-green-400" />
            
            <Card label="Max Drawdown" val={INR(mdd)} color="text-red-400" />
            <Card label="Return / MaxDD" val={isFinite(rmdd) ? fmt2(rmdd) : "—"} color={rmdd >= 2 ? "text-green-400" : rmdd >= 1 ? "text-yellow-400" : "text-red-400"} />
            <Card label="Sharpe Ratio" val={fmt2(sharpe)} color={sharpe >= 1.5 ? "text-green-400" : sharpe >= 0.8 ? "text-yellow-400" : "text-red-400"} />
            <Card label="Streak (Win/Loss)" val={`${wins.length}W / ${losses.length}L`} color="text-gray-300" />
          </div>

          {/* Double Column Charts */}
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
            {/* Equity Curve */}
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 lg:col-span-3">
              <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-4">Equity Curve</h3>
              <ResponsiveContainer width="100%" height={240}>
                <AreaChart data={chartData} margin={{ top: 5, right: 10, bottom: 0, left: 10 }}>
                  <defs>
                    <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                  <XAxis dataKey="i" stroke="#374151" tick={{ fill: "#6b7280", fontSize: 10 }} tickLine={false} />
                  <YAxis stroke="#374151" tick={{ fill: "#6b7280", fontSize: 10 }}
                    tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}k`} width={48} tickLine={false} />
                  <Tooltip
                    contentStyle={{ background: "#111827", border: "1px solid #374151", borderRadius: "8px", fontSize: "12px" }}
                    labelStyle={{ color: "#9ca3af" }}
                    formatter={(v: number) => [INR(v), "Cum. PnL"]}
                    labelFormatter={(_l: unknown, p) => (p?.[0]?.payload as { date?: string } | undefined)?.date ?? ""}
                  />
                  <ReferenceLine y={0} stroke="#374151" strokeDasharray="4 2" />
                  <Area type="monotone" dataKey="pnl" stroke="#3b82f6" fill="url(#pnlGrad)"
                    strokeWidth={2} dot={false} activeDot={{ r: 3, fill: "#3b82f6" }} />
                </AreaChart>
              </ResponsiveContainer>
            </div>

            {/* Weekday Performance */}
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 lg:col-span-2">
              <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-4">Weekday Net P&L</h3>
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={weekdayChartData} margin={{ top: 5, right: 10, bottom: 0, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                  <XAxis dataKey="name" stroke="#374151" tick={{ fill: "#6b7280", fontSize: 10 }} tickLine={false} />
                  <YAxis stroke="#374151" tick={{ fill: "#6b7280", fontSize: 10 }}
                    tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}k`} width={40} tickLine={false} />
                  <Tooltip
                    contentStyle={{ background: "#111827", border: "1px solid #374151", borderRadius: "8px", fontSize: "12px" }}
                    labelStyle={{ color: "#9ca3af" }}
                    formatter={(v: number) => [INR(v), "Net PnL"]}
                  />
                  <ReferenceLine y={0} stroke="#374151" strokeDasharray="4 2" />
                  <Bar dataKey="pnl">
                    {weekdayChartData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.pnl >= 0 ? "#10b981" : "#ef4444"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Monthly grid table */}
          {years.length > 0 && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden shadow-lg">
              <div className="px-5 py-4 border-b border-gray-800">
                <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider">Monthly Returns Summary</h3>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs border-collapse">
                  <thead>
                    <tr className="border-b border-gray-800 text-gray-500">
                      <th className="px-4 py-3 text-left font-semibold">Year</th>
                      {MONTHS.map((m) => <th key={m} className="px-2 py-3 text-center font-semibold w-16">{m}</th>)}
                      <th className="px-4 py-3 text-right font-semibold">Total</th>
                      <th className="px-4 py-3 text-right font-semibold">Max DD</th>
                    </tr>
                  </thead>
                  <tbody>
                    {years.map((y) => {
                      const yt = Object.values(g[y] ?? {}).reduce((a, b) => a + b, 0);
                      const md = ym[y] ?? 0;
                      return (
                        <tr key={y} className="border-b border-gray-800/50 hover:bg-gray-800/20 transition-colors">
                          <td className="px-4 py-2 font-bold text-gray-300">{y}</td>
                          {MONTHS.map((_, mi) => <MCell key={mi} val={g[y]?.[mi]} />)}
                          <td className={`px-4 py-2 text-right font-mono font-bold ${yt >= 0 ? "text-green-400" : "text-red-400"}`}>{INR(yt)}</td>
                          <td className="px-4 py-2 text-right font-mono text-red-400">{INR(md)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Heatmap Grid */}
          {years.length > 0 && (() => {
            const vals = years.flatMap((y) => MONTHS.map((_, m) => g[y]?.[m])).filter((v): v is number => v !== undefined);
            const maxAbs = Math.max(1, ...vals.map((v) => Math.abs(v)));
            const bg = (v: number | undefined) => {
              if (v === undefined) return "rgba(31,41,55,0.4)";
              const a = 0.18 + 0.72 * Math.min(1, Math.abs(v) / maxAbs);
              return v >= 0 ? `rgba(16,185,129,${a})` : `rgba(239,68,68,${a})`;
            };
            return (
              <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 shadow-lg">
                <div className="flex items-center justify-between border-b border-gray-800 pb-3 mb-4 flex-wrap gap-2">
                  <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider">Profit / Loss Heatmap</h3>
                  <span className="text-[10px] text-gray-500">Click a cell to review daily detail</span>
                </div>
                <div className="overflow-x-auto">
                  <table className="border-collapse w-full">
                    <thead>
                      <tr>
                        <th className="px-2 py-1 text-[10px] text-gray-500 text-left">Year</th>
                        {MONTHS.map((m) => <th key={m} className="px-1 py-1 text-[10px] text-gray-500 text-center">{m}</th>)}
                        <th className="px-2 py-1 text-[10px] text-gray-500 text-right">Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {years.map((y) => {
                        const yt = Object.values(g[y] ?? {}).reduce((a, b) => a + b, 0);
                        return (
                          <tr key={y}>
                            <td className="px-2 py-1 text-[11px] font-bold text-gray-300">{y}</td>
                            {MONTHS.map((_, mi) => {
                              const v = g[y]?.[mi];
                              const active = monthDetail?.y === y && monthDetail?.m === mi;
                              return (
                                <td key={mi} className="p-0.5 animate-fade-in">
                                  <div
                                    className={`h-8 rounded cursor-pointer flex items-center justify-center text-[8px] font-mono text-white/95 hover:ring-1 hover:ring-white/45 ${active ? "ring-2 ring-blue-500" : ""}`}
                                    style={{ backgroundColor: bg(v) }}
                                    onClick={() => v !== undefined && setMonthDetail({ y, m: mi })}
                                    onMouseEnter={(e) => { const r = e.currentTarget.getBoundingClientRect(); setHoverCell({ x: r.left + r.width / 2, y: r.top, date: `${MONTH_NAMES[mi]} ${y}`, pnl: v }); }}
                                    onMouseLeave={() => setHoverCell(null)}
                                  >
                                    {v !== undefined ? (Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(0)}k` : v.toFixed(0)) : ""}
                                  </div>
                                </td>
                              );
                            })}
                            <td className={`px-2 py-1 text-[11px] text-right font-mono font-bold ${yt >= 0 ? "text-green-400" : "text-red-400"}`}>{INR(yt)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {monthDetail && (
                  <div className="mt-4 pt-3 border-t border-gray-800">
                    <div className="flex items-center justify-between mb-2">
                      <h4 className="text-xs font-bold text-gray-300">
                        {MONTH_NAMES[monthDetail.m]} {monthDetail.y} Daily Breakdown
                      </h4>
                      <button onClick={() => setMonthDetail(null)} className="text-[10px] text-gray-500 hover:text-gray-300">✕ close</button>
                    </div>
                    <div className="max-w-sm">
                      <div className="grid grid-cols-7 gap-px text-center mb-0.5">
                        {WEEKDAYS_SHORT.map((w, i) => <div key={i} className="text-[8px] font-bold text-gray-600">{w}</div>)}
                      </div>
                      <div className="grid grid-cols-7 gap-0.5">
                        {getMonthGrid(monthDetail.y, monthDetail.m).map((c, ci) => {
                          if (c.dayNum === null) return <div key={ci} className="aspect-square" />;
                          const pnl = dailyPnlMap[c.dateStr!];
                          const has = pnl !== undefined;
                          return (
                            <div key={ci}
                              className={`aspect-square rounded-sm flex items-center justify-center text-[8px] font-mono select-none ${has ? "text-white cursor-default" : "bg-gray-950/40 text-gray-800"}`}
                              style={has ? { backgroundColor: pnl >= 0 ? "rgba(16,185,129,0.85)" : "rgba(239,68,68,0.85)" } : undefined}
                              onMouseEnter={(e) => { const r = e.currentTarget.getBoundingClientRect(); setHoverCell({ x: r.left + r.width / 2, y: r.top, date: c.dateStr!, pnl }); }}
                              onMouseLeave={() => setHoverCell(null)}
                            >{c.dayNum}</div>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })()}
        </div>
      )}

      {tab === "risk" && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            
            {/* Overfitting checklist */}
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 shadow-lg space-y-4">
              <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider border-b border-gray-800 pb-2">
                ⚠️ Overfitting Risk Review
              </h3>
              
              {loadingAnalytics ? (
                <div className="text-xs text-gray-500 py-6 text-center animate-pulse">Running overfitting check...</div>
              ) : analytics?.overfitting_warnings?.length === 0 ? (
                <div className="bg-emerald-950/20 border border-emerald-900/40 text-emerald-400 text-xs rounded-xl p-3 flex items-center gap-2">
                  <span>✓</span>
                  <span>No overfitting warnings triggered. The strategy backtest sample size and metrics are stable.</span>
                </div>
              ) : (
                <div className="space-y-2">
                  {analytics?.overfitting_warnings?.map((warn: any, idx: number) => (
                    <div
                      key={idx}
                      className={`p-3 rounded-xl border text-xs flex gap-2.5 ${
                        warn.severity === "HIGH" ? "bg-rose-950/20 border-rose-900/40 text-rose-300" : "bg-amber-950/20 border-amber-900/40 text-amber-300"
                      }`}
                    >
                      <span className="text-sm">⚠️</span>
                      <div>
                        <div className="font-extrabold uppercase text-[10px] tracking-wide">{warn.code} ({warn.severity})</div>
                        <p className="mt-0.5 text-gray-300">{warn.message}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Slippage sensitivity */}
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 shadow-lg space-y-4">
              <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider border-b border-gray-800 pb-2">
                ⚡ Slippage Sensitivity Test
              </h3>
              
              {loadingSlippage ? (
                <div className="text-xs text-gray-500 py-6 text-center animate-pulse">Simulating slippage penalty...</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs text-left">
                    <thead>
                      <tr className="border-b border-gray-800 text-gray-500 font-semibold">
                        <th className="py-2.5">Slippage %</th>
                        <th className="py-2.5 text-right">Net P&L</th>
                        <th className="py-2.5 text-right">Max Drawdown</th>
                        <th className="py-2.5 text-right">Profit Factor</th>
                      </tr>
                    </thead>
                    <tbody>
                      {slippageData.map((row: any, idx: number) => (
                        <tr key={idx} className="border-b border-gray-850 hover:bg-gray-850/20">
                          <td className="py-2 font-mono font-bold text-gray-300">{(row.slippage_pct * 100).toFixed(2)}%</td>
                          <td className={`py-2 text-right font-mono font-bold ${row.net_pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                            {INR(row.net_pnl)}
                          </td>
                          <td className="py-2 text-right font-mono text-red-400">{INR(row.max_drawdown)}</td>
                          <td className="py-2 text-right font-mono text-gray-300">{row.profit_factor.toFixed(2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {tab === "monte_carlo" && (
        <div className="space-y-6">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 shadow-lg space-y-4">
            <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider border-b border-gray-800 pb-2">
              🎲 Monte Carlo Simulation Summary
            </h3>
            
            {loadingAnalytics ? (
              <div className="text-xs text-gray-500 py-6 text-center animate-pulse">Running Monte Carlo shuffles...</div>
            ) : analytics?.monte_carlo ? (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <Card label="Confidence Level" val={`${(analytics.monte_carlo.confidence * 100).toFixed(0)}%`} color="text-blue-400" />
                <Card label="Median Net P&L" val={INR(analytics.monte_carlo.median_pnl)} color={analytics.monte_carlo.median_pnl >= 0 ? "text-green-400" : "text-red-400"} />
                <Card
                  label="Worst Case Drawdown (95% CL)"
                  val={INR(analytics.monte_carlo.worst_case_drawdown_95)}
                  color="text-red-400"
                  tooltip="We are 95% confident that maximum drawdown will not exceed this value."
                />
              </div>
            ) : (
              <div className="text-xs text-gray-500 py-6 text-center">No Monte Carlo simulation statistics available.</div>
            )}
          </div>
        </div>
      )}

      {tab === "logs" && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden shadow-lg">
          <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800">
            <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider">Backtest Execution Log</h3>
            <span className="text-xs text-gray-500 font-mono font-medium">{executed.length} Trades Executed</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-800 text-gray-500">
                  <th className="px-4 py-3 text-left font-semibold">Date</th>
                  <th className="px-4 py-3 text-left font-semibold">Entry → Exit</th>
                  <th className="px-4 py-3 text-right font-semibold">Gross P&L</th>
                  <th className="px-4 py-3 text-right font-semibold">Total Cost</th>
                  <th className="px-4 py-3 text-right font-semibold">Net P&L</th>
                  <th className="px-4 py-3 text-left font-semibold">Exit Reason</th>
                  <th className="px-4 py-3 text-right font-semibold">VIX</th>
                  <th className="px-4 py-3 text-right font-semibold">DTE</th>
                  <th className="px-4 py-3 text-left font-semibold">Position Breakdown</th>
                </tr>
              </thead>
              <tbody>
                {executed.map((t) => {
                  const dte = getDte(t);
                  return (
                    <tr key={t.day} onClick={() => setSelectedTrade(t)}
                      className="border-b border-gray-800/40 hover:bg-gray-850/40 transition-colors cursor-pointer">
                      <td className="px-4 py-2.5 font-mono text-gray-300">{t.day}</td>
                      <td className="px-4 py-2.5 font-mono text-gray-500 text-[11px] whitespace-nowrap">
                        {hm(t.entry_time)} → {hm(t.legs.map((l) => l.exit_time).filter(Boolean).sort().pop() as string | undefined)}
                      </td>
                      <td className={`px-4 py-2.5 text-right font-mono ${t.gross >= 0 ? "text-green-400" : "text-red-400"}`}>{INR(t.gross)}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-gray-500">{INR(t.cost)}</td>
                      <td className={`px-4 py-2.5 text-right font-mono font-bold ${t.net >= 0 ? "text-green-400" : "text-red-400"}`}>{INR(t.net)}</td>
                      <td className={`px-4 py-2.5 font-semibold ${EXIT_COLOR[t.exit_reason] ?? "text-gray-400"}`}>{t.exit_reason}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-gray-400">{t.vix.toFixed(1)}%</td>
                      <td className="px-4 py-2.5 text-right font-mono text-gray-400">{dte}</td>
                      <td className="px-4 py-2.5 text-gray-400 font-mono text-[11px]">
                        {t.legs.map((l, i) => (
                          <span key={i} className="mr-2 whitespace-nowrap bg-gray-950/60 px-2 py-0.5 rounded border border-gray-850">
                            {EXIT_DOT[l.exit_reason] && <span className={`mr-0.5 ${EXIT_DOT[l.exit_reason]}`}>●</span>}
                            {l.action === "BUY" ? "B" : "S"} {l.strike}{l.opt_type ?? ""}@{l.entry.toFixed(0)}→{l.exit.toFixed(0)}
                            <span className="text-gray-600 ml-1">{l.exit_reason}{l.exit_time ? ` ${hm(l.exit_time)}` : ""}</span>
                          </span>
                        ))}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Calendar hover tooltip */}
      {hoverCell && (
        <div
          className="fixed z-50 pointer-events-none -translate-x-1/2 -translate-y-full mb-1"
          style={{ left: hoverCell.x, top: hoverCell.y - 6 }}
        >
          <div className="bg-gray-950 border border-gray-700 rounded-lg px-2.5 py-1.5 shadow-xl whitespace-nowrap">
            <div className="text-[10px] text-gray-400 font-mono">{hoverCell.date}</div>
            <div className={`text-xs font-bold font-mono ${
              hoverCell.pnl === undefined ? "text-gray-500"
                : hoverCell.pnl >= 0 ? "text-emerald-400" : "text-rose-400"
            }`}>
              {hoverCell.pnl === undefined ? "No trades" : INR(hoverCell.pnl)}
            </div>
          </div>
        </div>
      )}

      <TradeDrawer trade={selectedTrade} onClose={() => setSelectedTrade(null)} />
    </div>
  );
}

import { useMemo, useState, useEffect, type ReactNode } from "react";
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
const asNum = (value: unknown, fallback = 0) => {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
};
const fmtMetric = (value: unknown, digits = 2) => asNum(value).toFixed(digits);
const fmtPct = (value: unknown, digits = 1) => `${asNum(value).toFixed(digits)}%`;

function HelpBox({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="text-xs leading-relaxed text-slate-300 bg-slate-950/70 border border-slate-800 rounded-lg px-3 py-2">
      <span className="font-bold text-slate-100">{title}: </span>
      {children}
    </div>
  );
}

function MiniMetric({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "good" | "bad" | "warn" | "neutral" }) {
  const color = tone === "good" ? "text-green-400" : tone === "bad" ? "text-red-400" : tone === "warn" ? "text-amber-300" : "text-gray-100";
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-950/60 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-gray-500 font-bold">{label}</div>
      <div className={`text-sm font-bold mt-1 ${color}`}>{value}</div>
    </div>
  );
}

function DistributionList({ items, empty = "No rows" }: { items: Record<string, unknown>; empty?: string }) {
  const entries = Object.entries(items || {});
  if (!entries.length) return <div className="text-xs text-gray-500">{empty}</div>;
  return (
    <div className="space-y-1.5">
      {entries.slice(0, 8).map(([name, value]) => (
        <div key={name} className="flex items-center justify-between gap-3 text-xs rounded border border-gray-800 bg-gray-950/50 px-2.5 py-1.5">
          <span className="text-gray-300 truncate">{name}</span>
          <span className="font-mono text-gray-100">{String(value)}</span>
        </div>
      ))}
    </div>
  );
}

function GateBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-bold ${ok ? "bg-green-950 text-green-300 border border-green-800" : "bg-red-950 text-red-300 border border-red-800"}`}>
      {label}
    </span>
  );
}

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

  const oiAnalytics = result.oi_analytics ?? {};
  const hasOiAnalytics = result.strategy_type === "OI" && Object.keys(oiAnalytics).length > 0;
  const oiStats = (oiAnalytics.stats ?? result.stats ?? {}) as Record<string, any>;
  const oiTradesCount = asNum(oiStats.trades ?? result.stats?.trades ?? nets.length, nets.length);
  const oiNetPnl = asNum(oiStats.net_pnl ?? result.stats?.net_pnl);
  const oiWinRatePct = oiAnalytics.stats ? asNum(oiStats.win_rate) : asNum(result.stats?.win_rate) * 100;
  const baseline = (oiAnalytics.baseline_comparison?.stats ?? {}) as Record<string, any>;
  const baselinePerTrade = (oiAnalytics.baseline_comparison?.per_trade ?? []) as Record<string, any>[];
  const sampleWarning = (oiAnalytics.sample_size_warning ?? {}) as Record<string, any>;
  const factorSummary = (oiAnalytics.factor_summary ?? []) as Record<string, any>[];
  const tradeJournal = (oiAnalytics.trade_journal ?? []) as Record<string, any>[];
  const drawdownAnalysis = (oiAnalytics.drawdown_analysis ?? {}) as Record<string, any>;
  const tradeQuality = (oiAnalytics.trade_quality ?? {}) as Record<string, any>;
  const timingAnalysis = (oiAnalytics.timing_analysis ?? {}) as Record<string, any>;
  const monteCarlo = (oiAnalytics.monte_carlo ?? {}) as Record<string, any>;
  const statisticalSignificance = (oiAnalytics.statistical_significance ?? {}) as Record<string, any>;
  const costSensitivity = (oiAnalytics.cost_sensitivity ?? []) as Record<string, any>[];
  const regimeSummary = (oiAnalytics.regime_summary ?? []) as Record<string, any>[];
  const dataQuality = (oiAnalytics.data_quality ?? {}) as Record<string, any>;
  const ablationStudy = (oiAnalytics.ablation_study ?? []) as Record<string, any>[];
  const trailingSlStudy = (oiAnalytics.trailing_sl_study ?? []) as Record<string, any>[];
  const marginalContribution = (oiAnalytics.oi_marginal_contribution ?? {}) as Record<string, any>;
  const pairedComparison = (oiAnalytics.paired_comparison ?? {}) as Record<string, any>;
  const researchVerdict = (oiAnalytics.research_verdict ?? {}) as Record<string, any>;
  const ablationGates = (oiAnalytics.ablation_gates ?? {}) as Record<string, any>;
  const strategyMinusBaseline = oiNetPnl - asNum(baseline.net_pnl);

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

          {hasOiAnalytics && (
            <div className="bg-gray-900 border border-cyan-900/50 rounded-xl p-5 space-y-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-xs font-bold text-cyan-300 uppercase tracking-wider">OI Strategy Analytics</h3>
                  <p className="text-xs text-gray-500 mt-1">
                    OI factors generated the dynamic BUY CE/PE entries. Indicators were optional confirmation filters when configured.
                  </p>
                </div>
                <span className="text-[10px] px-2 py-1 rounded bg-cyan-950 text-cyan-200 font-bold">
                  {String(oiAnalytics.interval ?? 5)} min OI scan
                </span>
              </div>

              <HelpBox title="How to read this">
                These outputs are research diagnostics, not profit probability. The OI score measures how many rule confirmations aligned before taking a long-premium CE/PE trade.
              </HelpBox>

              {sampleWarning.message && (
                <div className="text-xs leading-relaxed text-amber-200 bg-amber-950/30 border border-amber-800 rounded-lg px-3 py-2">
                  <span className="font-bold text-amber-300">Sample size warning: </span>
                  {String(sampleWarning.message)}
                </div>
              )}

              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <Card label="OI Trades" val={String(oiTradesCount.toFixed(0))} color="text-white" />
                <Card label="OI Win Rate" val={`${oiWinRatePct.toFixed(1)}%`} color={oiWinRatePct >= 50 ? "text-green-400" : "text-red-400"} />
                <Card label="Net P&L" val={INR(oiNetPnl)} color={oiNetPnl >= 0 ? "text-green-400" : "text-red-400"} />
                <Card label="Vs Baseline" val={INR(strategyMinusBaseline)} color={strategyMinusBaseline >= 0 ? "text-green-400" : "text-red-400"} />
              </div>

              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <div className="rounded-xl border border-gray-800 bg-gray-950/30 p-4 space-y-3">
                  <div>
                    <h4 className="text-xs font-bold text-gray-300 uppercase tracking-wider">Baseline Comparison</h4>
                    <p className="text-[11px] text-gray-500 mt-1">Compares OI-filtered trades against a naive same-time ATM CE/PE baseline.</p>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <MiniMetric label="Baseline P&L" value={INR(asNum(baseline.net_pnl))} tone={asNum(baseline.net_pnl) >= 0 ? "good" : "bad"} />
                    <MiniMetric label="Baseline MDD" value={INR(asNum(baseline.max_drawdown))} tone="bad" />
                    <MiniMetric label="Baseline Sharpe" value={fmtMetric(baseline.sharpe)} tone={asNum(baseline.sharpe) >= 1 ? "good" : "warn"} />
                    <MiniMetric label="Baseline Sortino" value={fmtMetric(baseline.sortino)} tone={asNum(baseline.sortino) >= 1 ? "good" : "warn"} />
                    <MiniMetric label="Baseline Win Rate" value={fmtPct(baseline.win_rate)} tone={asNum(baseline.win_rate) >= 50 ? "good" : "bad"} />
                    <MiniMetric label="Per-Trade Rows" value={String(baselinePerTrade.length)} />
                  </div>
                  <HelpBox title="Why it matters">
                    The filter only adds value if it improves P&L, drawdown, or risk-adjusted return versus taking the same directional option at each candidate time.
                  </HelpBox>
                </div>

                <div className="rounded-xl border border-gray-800 bg-gray-950/30 p-4 space-y-3">
                  <div>
                    <h4 className="text-xs font-bold text-gray-300 uppercase tracking-wider">Drawdown Quality</h4>
                    <p className="text-[11px] text-gray-500 mt-1">Shows depth and duration of pain, not only final profit.</p>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <MiniMetric label="Recovery Factor" value={fmtMetric(drawdownAnalysis.recovery_factor)} tone={asNum(drawdownAnalysis.recovery_factor) >= 1 ? "good" : "bad"} />
                    <MiniMetric label="Avg Drawdown" value={INR(asNum(drawdownAnalysis.average_drawdown))} tone="warn" />
                    <MiniMetric label="MDD Duration" value={`${asNum(drawdownAnalysis.max_drawdown_duration_trades, 0).toFixed(0)} trades`} tone={asNum(drawdownAnalysis.max_drawdown_duration_trades) <= 3 ? "good" : "warn"} />
                    <MiniMetric label="Calmar Proxy" value={fmtMetric(drawdownAnalysis.calmar_proxy)} tone={asNum(drawdownAnalysis.calmar_proxy) >= 1 ? "good" : "bad"} />
                  </div>
                  <HelpBox title="Why it matters">
                    A profitable strategy can still be hard to trade if drawdowns are deep or take many trades to recover.
                  </HelpBox>
                </div>
              </div>

              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <div className="rounded-xl border border-gray-800 bg-gray-950/30 p-4 space-y-3">
                  <div>
                    <h4 className="text-xs font-bold text-gray-300 uppercase tracking-wider">Trade Quality</h4>
                    <p className="text-[11px] text-gray-500 mt-1">Breaks down whether exits and payoff shape support the edge.</p>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <MiniMetric label="Profit Factor" value={fmtMetric(tradeQuality.profit_factor)} tone={asNum(tradeQuality.profit_factor) >= 1.5 ? "good" : asNum(tradeQuality.profit_factor) >= 1 ? "warn" : "bad"} />
                    <MiniMetric label="Payoff Ratio" value={fmtMetric(tradeQuality.payoff_ratio)} tone={asNum(tradeQuality.payoff_ratio) >= 1 ? "good" : "bad"} />
                    <MiniMetric label="Winner Hold" value={`${fmtMetric(tradeQuality.avg_winner_holding_minutes, 0)} min`} />
                    <MiniMetric label="Loser Hold" value={`${fmtMetric(tradeQuality.avg_loser_holding_minutes, 0)} min`} />
                    <MiniMetric label="Avg MAE" value={INR(asNum(tradeQuality.avg_mae))} tone="warn" />
                    <MiniMetric label="Avg MFE" value={INR(asNum(tradeQuality.avg_mfe))} tone="good" />
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-gray-500 font-bold mb-2">Exit Reasons</div>
                    <DistributionList items={(tradeQuality.exit_reason_distribution ?? {}) as Record<string, unknown>} empty="No exit reasons yet" />
                  </div>
                </div>

                <div className="rounded-xl border border-gray-800 bg-gray-950/30 p-4 space-y-3">
                  <div>
                    <h4 className="text-xs font-bold text-gray-300 uppercase tracking-wider">Skipped / No-Trade Review</h4>
                    <p className="text-[11px] text-gray-500 mt-1">Shows what the OI filter rejected and whether skipped baseline candidates would have worked.</p>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <MiniMetric label="Skipped Candidates" value={String(asNum(tradeQuality.skipped_baseline?.candidates, 0).toFixed(0))} />
                    <MiniMetric label="Skipped Win Rate" value={fmtPct(tradeQuality.skipped_baseline?.win_rate)} />
                    <MiniMetric label="Skipped P&L" value={INR(asNum(tradeQuality.skipped_baseline?.net_pnl))} tone={asNum(tradeQuality.skipped_baseline?.net_pnl) >= 0 ? "warn" : "good"} />
                    <MiniMetric label="Journal Rows" value={String(tradeJournal.length)} />
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-gray-500 font-bold mb-2">No-Trade Reasons</div>
                    <DistributionList items={(tradeQuality.skipped_reason_counts ?? {}) as Record<string, unknown>} empty="No skipped reason counts yet" />
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <div className="rounded-xl border border-gray-800 bg-gray-950/30 p-4 space-y-3">
                  <div>
                    <h4 className="text-xs font-bold text-gray-300 uppercase tracking-wider">Regime And Timing</h4>
                    <p className="text-[11px] text-gray-500 mt-1">Segments results by market regime, weekday, expiry bucket, entry time, and holding time.</p>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div>
                      <div className="text-[10px] uppercase tracking-wider text-gray-500 font-bold mb-2">Regime Split</div>
                      <DistributionList items={Object.fromEntries(regimeSummary.slice(0, 6).map((r) => [String(r.name), `${INR(asNum(r.net_pnl))} / ${asNum(r.trades, 0).toFixed(0)} trades`]))} empty="No regime rows yet" />
                    </div>
                    <div>
                      <div className="text-[10px] uppercase tracking-wider text-gray-500 font-bold mb-2">Entry Time Buckets</div>
                      <DistributionList items={Object.fromEntries(((timingAnalysis.entry_time ?? []) as Record<string, any>[]).slice(0, 6).map((r) => [String(r.name), `${INR(asNum(r.net_pnl))} / ${asNum(r.trades, 0).toFixed(0)}`]))} empty="No entry-time rows yet" />
                    </div>
                  </div>
                  <HelpBox title="Why it matters">
                    OI option buying often behaves differently on expiry days, late entries, and range-bound sessions. Segmenting prevents one average from hiding fragile behavior.
                  </HelpBox>
                </div>

                <div className="rounded-xl border border-gray-800 bg-gray-950/30 p-4 space-y-3">
                  <div>
                    <h4 className="text-xs font-bold text-gray-300 uppercase tracking-wider">Cost Sensitivity</h4>
                    <p className="text-[11px] text-gray-500 mt-1">Reprices the same trades at 0x, 1x, and 2x configured slippage/cost assumptions.</p>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                    {costSensitivity.slice(0, 3).map((row) => (
                      <MiniMetric
                        key={String(row.cost_multiplier)}
                        label={`${fmtMetric(row.cost_multiplier, 0)}x Costs`}
                        value={`${INR(asNum(row.net_pnl))} / DD ${INR(asNum(row.max_drawdown))}`}
                        tone={asNum(row.net_pnl) >= 0 ? "good" : "bad"}
                      />
                    ))}
                    {costSensitivity.length === 0 && <div className="text-xs text-gray-500">No cost sensitivity rows yet</div>}
                  </div>
                  <HelpBox title="Why it matters">
                    Long-premium intraday systems can look fine before friction. A robust signal should not disappear when slippage is doubled.
                  </HelpBox>
                </div>
              </div>

              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <div className="rounded-xl border border-gray-800 bg-gray-950/30 p-4 space-y-3">
                  <div>
                    <h4 className="text-xs font-bold text-gray-300 uppercase tracking-wider">Monte Carlo And Significance</h4>
                    <p className="text-[11px] text-gray-500 mt-1">Bootstraps trade returns to show sequence risk and whether the mean return is statistically reliable.</p>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <MiniMetric label="Historical MDD" value={INR(asNum(monteCarlo.historical_mdd))} tone="bad" />
                    <MiniMetric label="MC MDD 95%" value={INR(asNum(monteCarlo.mdd_95))} tone="bad" />
                    <MiniMetric label="MC MDD 99%" value={INR(asNum(monteCarlo.mdd_99))} tone="bad" />
                    <MiniMetric label="MC Median P&L" value={INR(asNum(monteCarlo.median_pnl))} tone={asNum(monteCarlo.median_pnl) >= 0 ? "good" : "bad"} />
                    <MiniMetric label="t-Statistic" value={fmtMetric(statisticalSignificance.t_statistic, 2)} tone={Math.abs(asNum(statisticalSignificance.t_statistic)) >= 2 ? "good" : "warn"} />
                    <MiniMetric label="p-Value" value={fmtMetric(statisticalSignificance.p_value, 3)} tone={asNum(statisticalSignificance.p_value, 1) < 0.05 ? "good" : "warn"} />
                  </div>
                  <HelpBox title="Customer reading">
                    With fewer than 100 trades, treat the result as early evidence. The confidence interval can be wide even when the P&L looks attractive.
                  </HelpBox>
                </div>

                {ablationStudy.length > 0 && (
                  <div className="rounded-xl border border-cyan-900/60 bg-cyan-950/10 p-4 space-y-3">
                    <div>
                      <h4 className="text-xs font-bold text-cyan-300 uppercase tracking-wider">Ablation Study Verdict</h4>
                      <p className="text-[11px] text-gray-500 mt-1">Tests whether OI wall adds edge versus the same confirmation stack without OI wall.</p>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <MiniMetric label="Verdict" value={String(researchVerdict.verdict ?? "not run")} tone={String(researchVerdict.verdict ?? "").includes("hurts") ? "bad" : String(researchVerdict.verdict ?? "").includes("improves") ? "good" : "warn"} />
                      <MiniMetric label="Full - No OI" value={marginalContribution.delta_net_pnl == null ? "-" : INR(asNum(marginalContribution.delta_net_pnl))} tone={asNum(marginalContribution.delta_net_pnl) >= 0 ? "good" : "bad"} />
                      <MiniMetric label="Full Stack Trades" value={String(marginalContribution.full_stack_trades ?? "-")} />
                      <MiniMetric label="No-OI Trades" value={String(marginalContribution.no_oi_wall_trades ?? "-")} />
                    </div>
                    {researchVerdict.detail && (
                      <HelpBox title="Interpretation">{String(researchVerdict.detail)}</HelpBox>
                    )}
                    <div className="text-[10px] text-gray-500">
                      Gates: p &lt; {fmtMetric(ablationGates.max_p_value ?? 0.05, 2)}, PF &gt; {fmtMetric(ablationGates.min_profit_factor ?? 1.3, 1)}, trades &gt;= {String(ablationGates.min_trades ?? 200)}.
                      Overlap: {String(pairedComparison.overlap_trades ?? 0)} trades, overlap delta {INR(asNum(pairedComparison.overlap_delta_net_pnl))}.
                    </div>
                  </div>
                )}
              </div>

              {ablationStudy.length > 0 && (
                <div className="rounded-xl border border-gray-800 bg-gray-950/30 p-4 space-y-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h4 className="text-xs font-bold text-gray-300 uppercase tracking-wider">Ablation Study</h4>
                      <p className="text-[11px] text-gray-500 mt-1">Ranked by research qualification first, then p-value, profit factor, drawdown, and P&L. Raw P&L alone should not decide the winner.</p>
                    </div>
                    <span className="text-[10px] rounded bg-gray-900 border border-gray-800 px-2 py-1 text-gray-400">{ablationStudy.length} configs</span>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead className="text-gray-500 uppercase tracking-wider">
                        <tr>
                          <th className="text-left py-2 pr-3">Config</th>
                          <th className="text-right py-2 pr-3">Trades</th>
                          <th className="text-right py-2 pr-3">Net</th>
                          <th className="text-right py-2 pr-3">PF</th>
                          <th className="text-right py-2 pr-3">p</th>
                          <th className="text-right py-2 pr-3">MDD</th>
                          <th className="text-left py-2">Gates</th>
                        </tr>
                      </thead>
                      <tbody>
                        {ablationStudy.slice(0, 12).map((row) => {
                          const checks = row.qualification?.checks ?? {};
                          return (
                            <tr key={String(row.config_id)} className="border-t border-gray-800/70">
                              <td className="py-2 pr-3">
                                <div className="font-bold text-gray-200">{String(row.label ?? row.config_id)}</div>
                                <div className="text-[10px] text-gray-500 max-w-[260px] truncate">{((row.active_factors ?? []) as string[]).join(", ")}</div>
                              </td>
                              <td className="py-2 pr-3 text-right font-mono text-gray-300">{String(row.trades ?? 0)}</td>
                              <td className={`py-2 pr-3 text-right font-mono ${asNum(row.net_pnl) >= 0 ? "text-green-400" : "text-red-400"}`}>{INR(asNum(row.net_pnl))}</td>
                              <td className="py-2 pr-3 text-right font-mono text-gray-300">{fmtMetric(row.profit_factor)}</td>
                              <td className={asNum(row.p_value, 1) < asNum(ablationGates.max_p_value ?? 0.05) ? "py-2 pr-3 text-right font-mono text-green-400" : "py-2 pr-3 text-right font-mono text-red-400"}>{fmtMetric(row.p_value, 3)}</td>
                              <td className="py-2 pr-3 text-right font-mono text-red-300">{INR(asNum(row.max_drawdown))}</td>
                              <td className="py-2">
                                <div className="flex flex-wrap gap-1">
                                  <GateBadge ok={Boolean(checks.p_value)} label="p" />
                                  <GateBadge ok={Boolean(checks.profit_factor)} label="PF" />
                                  <GateBadge ok={Boolean(checks.trade_count)} label="N" />
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <HelpBox title="Decision rule">
                    Treat configs failing p-value or trade-count gates as research leads only. A bigger P&L with p &gt; 0.05 can still be noise.
                  </HelpBox>
                </div>
              )}

              {trailingSlStudy.length > 0 && (
                <div className="rounded-xl border border-gray-800 bg-gray-950/30 p-4 space-y-3">
                  <div>
                    <h4 className="text-xs font-bold text-gray-300 uppercase tracking-wider">Trailing SL Research</h4>
                    <p className="text-[11px] text-gray-500 mt-1">Exit tuning is shown separately so it does not contaminate the factor ablation result.</p>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
                    {trailingSlStudy.slice(0, 4).map((row) => (
                      <MiniMetric
                        key={String(row.config_id)}
                        label={`${fmtMetric(row.trailing_sl_percent, 0)}% Trail`}
                        value={`${INR(asNum(row.net_pnl))} / p ${fmtMetric(row.p_value, 3)}`}
                        tone={asNum(row.net_pnl) >= 0 ? "good" : "bad"}
                      />
                    ))}
                  </div>
                </div>
              )}

              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <div className="rounded-xl border border-gray-800 bg-gray-950/30 p-4 space-y-3">
                  <div>
                    <h4 className="text-xs font-bold text-gray-300 uppercase tracking-wider">Factor Summary And Data Quality</h4>
                    <p className="text-[11px] text-gray-500 mt-1">Shows which factor combinations carried P&L and which institutional inputs are unavailable in the current DB.</p>
                  </div>
                  <div className="space-y-1.5">
                    {factorSummary.slice(0, 5).map((f) => (
                      <div key={String(f.name)} className="flex items-center justify-between gap-3 text-xs bg-gray-950/60 border border-gray-800 rounded-lg px-3 py-2">
                        <span className="text-gray-300 truncate">{String(f.name)}</span>
                        <span className={(f.net_pnl ?? 0) >= 0 ? "text-green-400 font-mono" : "text-red-400 font-mono"}>{INR(Number(f.net_pnl ?? 0))}</span>
                      </div>
                    ))}
                    {factorSummary.length === 0 && <div className="text-xs text-gray-500">No factor summary rows yet</div>}
                  </div>
                  <div className="text-[11px] text-gray-500">
                    IV rank/skew, real bid/ask, futures OI, event calendar, and F&O ban filters remain marked unavailable unless vendor-backed data is added.
                    <span className="block mt-1 text-gray-400">Current data quality fields: {Object.keys(dataQuality).length}</span>
                  </div>
                </div>
              </div>

              {tradeJournal.length > 0 && (
                <div className="rounded-xl border border-gray-800 bg-gray-950/30 p-4 space-y-3">
                  <div>
                    <h4 className="text-xs font-bold text-gray-300 uppercase tracking-wider">Trade Journal Preview</h4>
                    <p className="text-[11px] text-gray-500 mt-1">Each row records the signal rationale, trade decision, score, costs, exit reason, and no-trade explanations.</p>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead className="text-gray-500 uppercase tracking-wider">
                        <tr>
                          <th className="text-left py-2 pr-3">Time</th>
                          <th className="text-left py-2 pr-3">Action</th>
                          <th className="text-left py-2 pr-3">Signal</th>
                          <th className="text-right py-2 pr-3">Score</th>
                          <th className="text-right py-2 pr-3">Net</th>
                          <th className="text-left py-2">Reason</th>
                        </tr>
                      </thead>
                      <tbody>
                        {tradeJournal.slice(0, 8).map((row, idx) => (
                          <tr key={`${row.timestamp ?? row.entry_time ?? idx}`} className="border-t border-gray-800/70">
                            <td className="py-2 pr-3 text-gray-400 whitespace-nowrap">{hm(String(row.timestamp ?? row.entry_time ?? ""))}</td>
                            <td className="py-2 pr-3 text-gray-200">{String(row.action ?? "-")}</td>
                            <td className="py-2 pr-3 text-gray-300">{String(row.signal_type ?? row.opt_type ?? "-")}</td>
                            <td className="py-2 pr-3 text-right font-mono text-cyan-300">{fmtMetric(row.score, 0)}</td>
                            <td className={`py-2 pr-3 text-right font-mono ${asNum(row.net_pnl) >= 0 ? "text-green-400" : "text-red-400"}`}>{row.net_pnl == null ? "-" : INR(asNum(row.net_pnl))}</td>
                            <td className="py-2 text-gray-500 max-w-[240px] truncate">{Array.isArray(row.no_trade_reasons) ? row.no_trade_reasons.join(", ") : String(row.exit_reason ?? row.reason ?? "-")}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}

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

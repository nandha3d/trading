import { useMemo, useState, useCallback } from "react";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
  BarChart, Bar, Cell,
} from "recharts";
import type { BacktestResponse, TradeResult } from "../types";
import TradeDrawer from "./TradeDrawer";

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
const WD = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"
];
const WEEKDAYS_SHORT = ["S", "M", "T", "W", "T", "F", "S"];

interface CP { brokerage: number; slippage_pct: number; use_taxes: boolean }

const parseDate = (dStr: string) => {
  const [y, m, d] = dStr.split("-").map(Number);
  return new Date(y, m - 1, d);
};

function legCost(entry: number, exit_: number, qty: number, action: string, p: CP): number {
  const sell = action === "SELL";
  const bv = sell ? exit_ * qty : entry * qty;
  const sv = sell ? entry * qty : exit_ * qty;
  
  // Flat brokerage: p.brokerage on entry, p.brokerage on exit (round trip = p.brokerage * 2)
  const brokerage = p.brokerage * 2;
  
  if (!p.use_taxes) return brokerage;
  
  // STT: 0.0625% on option selling premium
  const stt = sv * 0.000625;
  
  // Exchange transaction charges (NSE option txn charge is 0.0505% of premium)
  const exchangeCharges = (bv + sv) * 0.000505;
  
  // SEBI turnover fee: 0.0001% of premium
  const sebiFee = (bv + sv) * 0.000001;
  
  // Stamp duty: 0.003% of buy premium
  const stampDuty = bv * 0.00003;
  
  // GST: 18% of (Brokerage + Exchange transaction charges + SEBI fee)
  const gst = (brokerage + exchangeCharges + sebiFee) * 0.18;
  
  return brokerage + stt + exchangeCharges + sebiFee + stampDuty + gst;
}

function applyCharges(trades: TradeResult[], p: CP): TradeResult[] {
  return trades.map((t) => {
    // Slippage is applied to entry and exit premium for each leg
    const slip = t.legs.reduce((s, l) => s + (l.entry + l.exit) * (p.slippage_pct / 100) * l.qty, 0);
    const cost = t.legs.reduce((s, l) => s + legCost(l.entry, l.exit, l.qty, l.action ?? "SELL", p), 0);
    return {
      ...t,
      cost: Math.round(cost),
      net: Math.round(t.gross - slip - cost)
    };
  });
}

function getDte(t: TradeResult) {
  if (!t.expiry) return 0;
  const d1 = parseDate(t.day);
  const d2 = parseDate(t.expiry);
  return Math.round((d2.getTime() - d1.getTime()) / (1000 * 60 * 60 * 24));
}

function monteCarloMDD(nets: number[], iters: number, conf: number): number {
  const arr = [...nets];
  const mdds: number[] = [];
  for (let i = 0; i < iters; i++) {
    for (let j = arr.length - 1; j > 0; j--) {
      const k = Math.floor(Math.random() * (j + 1));
      [arr[j], arr[k]] = [arr[k], arr[j]];
    }
    let eq = 0, pk = 0, mdd = 0;
    for (const n of arr) {
      eq += n;
      pk = Math.max(pk, eq);
      mdd = Math.min(mdd, eq - pk);
    }
    mdds.push(mdd);
  }
  mdds.sort((a, b) => a - b);
  return mdds[Math.floor((1 - conf / 100) * iters)];
}

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

function exportCSV(trades: TradeResult[]) {
  const ml = Math.max(...trades.map((t) => t.legs.length));
  const lh = Array.from({ length: ml }, (_, i) => [`L${i+1}_Stk`,`L${i+1}_Act`,`L${i+1}_Entry`,`L${i+1}_Exit`,`L${i+1}_ExitRsn`]).flat();
  const rows = [
    ["Date","Gross","Cost","Net","ExitReason","Spot","VIX","Expiry","DTE",...lh],
    ...trades.map((t) => {
      const d1 = parseDate(t.day);
      const d2 = t.expiry ? parseDate(t.expiry) : d1;
      const dte = Math.round((d2.getTime() - d1.getTime()) / (1000 * 60 * 60 * 24));
      return [
        t.day, t.gross, t.cost, t.net, t.exit_reason, t.entry_spot, t.vix, t.expiry || "", dte,
        ...t.legs.flatMap((l) => [l.strike, l.action, l.entry, l.exit, l.exit_reason])
      ];
    })
  ];
  const a = document.createElement("a");
  a.href = "data:text/csv;charset=utf-8," + encodeURIComponent(rows.map((r) => r.join(",")).join("\n"));
  a.download = `backtest_report_${new Date().toISOString().slice(0,10)}.csv`;
  a.click();
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

const inp = "bg-gray-950 border border-gray-700 rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500 w-full";

const hm = (iso?: string | null) => (iso ? iso.slice(11, 16) : "—");

type AnalRow = [string, { hit: number; miss: number; profit: number; loss: number }];
function AnalyticsBlock({ title, rows }: { title: string; rows: AnalRow[] }) {
  return (
    <div className="space-y-2">
      <div className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider">{title}</div>
      <div className="space-y-2">
        {rows.map(([k, r]) => {
          const tot = r.hit + r.miss || 1;
          const hp = (r.hit / tot) * 100;
          const pl = r.profit + Math.abs(r.loss) || 1;
          const pp = (r.profit / pl) * 100;
          return (
            <div key={k} className="grid grid-cols-[110px_1fr_1fr] gap-3 items-center">
              <div className="text-[11px] text-gray-300 font-medium truncate">{k}</div>
              <div>
                <div className="flex justify-between text-[9px] mb-0.5"><span className="text-teal-400">Hit {r.hit}</span><span className="text-amber-400">Miss {r.miss}</span></div>
                <div className="h-2 rounded bg-gray-800 overflow-hidden flex">
                  <div className="bg-teal-500" style={{ width: `${hp}%` }} /><div className="bg-amber-500" style={{ width: `${100 - hp}%` }} />
                </div>
              </div>
              <div>
                <div className="flex justify-between text-[9px] mb-0.5"><span className="text-green-400">{INR(r.profit)}</span><span className="text-red-400">{INR(r.loss)}</span></div>
                <div className="h-2 rounded bg-gray-800 overflow-hidden flex">
                  <div className="bg-green-500" style={{ width: `${pp}%` }} /><div className="bg-red-500" style={{ width: `${100 - pp}%` }} />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function ResultsPanel({ result }: Props) {
  const { trades: raw } = result;
  const executed = useMemo(() => raw.filter((t) => !t.skip_reason), [raw]);
  const skipped = useMemo(() => raw.filter((t) => !!t.skip_reason), [raw]);
  const [selectedTrade, setSelectedTrade] = useState<TradeResult | null>(null);
  
  // Costs & charges state
  const [brok, setBrok] = useState(20);
  const [slip, setSlip] = useState(0);
  const [taxes, setTaxes] = useState(true);
  const [cp, setCp] = useState<CP>({ brokerage: 20, slippage_pct: 0, use_taxes: true });

  // Dynamic filter state
  const [wdf, setWdf] = useState<Set<number>>(new Set([1,2,3,4,5])); // Mon-Fri
  const [minVixInput, setMinVixInput] = useState<number>(0);
  const [maxVixInput, setMaxVixInput] = useState<number>(100);
  const [minDteInput, setMinDteInput] = useState<number>(0);
  const [maxDteInput, setMaxDteInput] = useState<number>(30);

  // Monte Carlo state
  const [mcConf, setMcConf] = useState(95);
  const [mcRes, setMcRes] = useState<number | null>(null);
  const [mcBusy, setMcBusy] = useState(false);

  // Process adjusted net prices
  const adj = useMemo(() => applyCharges(executed, cp), [executed, cp]);

  // Apply filters on trades list
  const trades = useMemo(() => {
    return adj.filter((t) => {
      const wd = parseDate(t.day).getDay();
      const wOk = wdf.has(wd);
      const vixOk = t.vix >= minVixInput && t.vix <= maxVixInput;
      const dteVal = getDte(t);
      const dteOk = dteVal >= minDteInput && dteVal <= maxDteInput;
      return wOk && vixOk && dteOk;
    });
  }, [adj, wdf, minVixInput, maxVixInput, minDteInput, maxDteInput]);

  const nets = useMemo(() => trades.map((t) => t.net), [trades]);
  const wins = useMemo(() => nets.filter((n) => n > 0), [nets]);
  const losses = useMemo(() => nets.filter((n) => n <= 0), [nets]);
  const net_pnl = useMemo(() => nets.reduce((a, b) => a + b, 0), [nets]);
  
  const wr = useMemo(() => nets.length ? wins.length / nets.length : 0, [nets, wins]);
  const aw = useMemo(() => wins.length ? wins.reduce((a, b) => a + b, 0) / wins.length : 0, [wins]);
  const al = useMemo(() => losses.length ? Math.abs(losses.reduce((a, b) => a + b, 0)) / losses.length : 0, [losses]);
  const rr = useMemo(() => al > 0 ? aw / al : 0, [aw, al]);
  const expectancy = useMemo(() => nets.length ? net_pnl / nets.length : 0, [nets, net_pnl]);
  const kelly = useMemo(() => aw > 0 && al > 0 ? (wr - (1 - wr) / (aw / al)) * 100 : 0, [wr, aw, al]);

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

  const adv = useMemo(() => {
    let mw = 0, ml = 0, cw = 0, cl = 0;
    for (const n of nets) {
      if (n > 0) { cw++; cl = 0; mw = Math.max(mw, cw); } else { cl++; cw = 0; ml = Math.max(ml, cl); }
    }
    let maxTradesInDd = 0;
    let currentTradesInDd = 0;
    let peakVal = 0;
    let currentEq = 0;
    let maxDDuration = 0;
    let peakTime = trades.length > 0 ? parseDate(trades[0].day).getTime() : 0;

    for (const t of trades) {
      currentEq += t.net;
      if (currentEq >= peakVal) {
        peakVal = currentEq;
        currentTradesInDd = 0;
        peakTime = parseDate(t.day).getTime();
      } else {
        currentTradesInDd++;
        maxTradesInDd = Math.max(maxTradesInDd, currentTradesInDd);
        const duration = (parseDate(t.day).getTime() - peakTime) / (1000 * 60 * 60 * 24);
        maxDDuration = Math.max(maxDDuration, duration);
      }
    }

    const gp = wins.reduce((a, b) => a + b, 0);
    const gl = Math.abs(losses.reduce((a, b) => a + b, 0));
    const pf = gl > 0 ? gp / gl : Infinity;
    const rf = mdd !== 0 ? net_pnl / Math.abs(mdd) : Infinity;

    return { pf, rf, mw, ml, maxTradesInDd, maxDDuration: Math.round(maxDDuration) };
  }, [nets, trades, wins, losses, mdd, net_pnl]);

  const ec = useMemo(() => trades.reduce<number[]>((a, t) => [...a, (a[a.length - 1] ?? 0) + t.net], [0]), [trades]);
  const chartData = useMemo(() => ec.map((v, i) => ({ i, pnl: v, date: i > 0 ? trades[i - 1]?.day : "Start" })), [ec, trades]);
  
  // Year-wise Monthly grid data
  const { g, ym, years } = useMemo(() => buildGrid(trades), [trades]);

  // Selected year for Calendar Heatmap
  const [hoverCell, setHoverCell] = useState<{ x: number; y: number; date: string; pnl: number | undefined } | null>(null);
  const [monthDetail, setMonthDetail] = useState<{ y: number; m: number } | null>(null);

  // Map of date string -> net PnL for Calendar Heatmap
  const dailyPnlMap = useMemo(() => {
    const map: Record<string, number> = {};
    for (const t of trades) {
      const dStr = t.day;
      map[dStr] = (map[dStr] ?? 0) + t.net;
    }
    return map;
  }, [trades]);

  // Transactions Analytics: hit/miss + profit/loss grouped by a key fn
  const analytics = useMemo(() => {
    const tradeType = (t: TradeResult): string => {
      if (!t.legs.length) return "—";
      const a = new Set(t.legs.map((l) => l.action));
      const o = new Set(t.legs.map((l) => l.opt_type ?? "CE"));
      if (t.legs.length === 1 || (a.size === 1 && o.size === 1)) {
        const act = [...a][0] === "BUY" ? "Long" : "Short";
        return `${[...o][0] === "CE" ? "Call" : "Put"} ${act}`;
      }
      return "Multi-leg";
    };
    const group = (keyOf: (t: TradeResult) => string) => {
      const m: Record<string, { hit: number; miss: number; profit: number; loss: number }> = {};
      for (const t of trades) {
        const k = keyOf(t);
        const r = (m[k] = m[k] ?? { hit: 0, miss: 0, profit: 0, loss: 0 });
        if (t.net > 0) { r.hit++; r.profit += t.net; } else { r.miss++; r.loss += t.net; }
      }
      return Object.entries(m).sort((a, b) => a[0].localeCompare(b[0]));
    };
    return {
      byType: group(tradeType),
      byYear: group((t) => String(parseDate(t.day).getFullYear())),
    };
  }, [trades]);

  // Weekday data for Recharts Bar Chart
  const weekdayChartData = useMemo(() => {
    const days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];
    const pnlByDay = [0, 0, 0, 0, 0];
    for (const t of trades) {
      const wd = parseDate(t.day).getDay(); // 1=Mon, 5=Fri
      if (wd >= 1 && wd <= 5) {
        pnlByDay[wd - 1] += t.net;
      }
    }
    return days.map((name, i) => ({
      name,
      pnl: pnlByDay[i],
    }));
  }, [trades]);

  const runMC = useCallback(() => {
    setMcBusy(true);
    setTimeout(() => { 
      setMcRes(monteCarloMDD(nets, 10000, mcConf)); 
      setMcBusy(false); 
    }, 50);
  }, [nets, mcConf]);

  return (
    <div className="space-y-6">

      {/* Simulator & Filters Panel */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        
        {/* Cost & Charges Simulator */}
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider">Costs & Charges Simulator</h3>
              <span className="text-[10px] bg-blue-900/40 text-blue-300 font-mono px-2 py-0.5 rounded border border-blue-800">Indian Option Tax Model</span>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-4">
              <div className="space-y-1">
                <label className="text-[10px] text-gray-500 font-medium">Flat Brokerage (₹/leg)</label>
                <input type="number" min="0" value={brok} onChange={(e) => setBrok(Number(e.target.value))} className={inp} />
              </div>
              <div className="space-y-1">
                <label className="text-[10px] text-gray-500 font-medium">Slippage % (per side)</label>
                <input type="number" min="0" step="0.05" value={slip} onChange={(e) => setSlip(Number(e.target.value))} className={inp} />
              </div>
              <div className="col-span-2 sm:col-span-1 flex items-center justify-start h-full pt-4">
                <label className="flex items-center gap-2 cursor-pointer select-none">
                  <input type="checkbox" checked={taxes} onChange={(e) => setTaxes(e.target.checked)} className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-blue-500 accent-blue-500" />
                  <span className="text-xs text-gray-400">Apply Taxes</span>
                </label>
              </div>
            </div>
            <p className="text-[9px] text-gray-500 leading-normal mb-4">
              Taxes include: **STT** (0.0625% on sell premium), **Txn Charge** (0.0505% on NSE premium), **GST** (18% of brokerage + txn fee), **Stamp Duty** (0.003% on buy premium), and **SEBI Fee** (0.0001%).
            </p>
          </div>
          <div className="flex gap-3 mt-auto">
            <button onClick={() => setCp({ brokerage: brok, slippage_pct: slip, use_taxes: taxes })}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold rounded-lg transition-colors flex-1 shadow-md shadow-blue-900/20">
              Apply Costs
            </button>
            <button onClick={() => exportCSV(trades)} className="px-4 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 text-xs font-semibold rounded-lg transition-all">
              Export CSV
            </button>
          </div>
        </div>

        {/* Dynamic Filters Panel */}
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-5 flex flex-col justify-between">
          <div>
            <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-4">Interactive Performance Filters</h3>
            <div className="grid grid-cols-2 gap-3 mb-4">
              <div className="space-y-1">
                <label className="text-[10px] text-gray-500 font-medium">Min VIX (ATM IV %)</label>
                <input type="number" min="0" max="100" value={minVixInput} onChange={(e) => setMinVixInput(Number(e.target.value))} className={inp} />
              </div>
              <div className="space-y-1">
                <label className="text-[10px] text-gray-500 font-medium">Max VIX (ATM IV %)</label>
                <input type="number" min="0" max="100" value={maxVixInput} onChange={(e) => setMaxVixInput(Number(e.target.value))} className={inp} />
              </div>
              <div className="space-y-1">
                <label className="text-[10px] text-gray-500 font-medium">Min DTE at Entry</label>
                <input type="number" min="0" max="100" value={minDteInput} onChange={(e) => setMinDteInput(Number(e.target.value))} className={inp} />
              </div>
              <div className="space-y-1">
                <label className="text-[10px] text-gray-500 font-medium">Max DTE at Entry</label>
                <input type="number" min="0" max="100" value={maxDteInput} onChange={(e) => setMaxDteInput(Number(e.target.value))} className={inp} />
              </div>
            </div>
            
            {/* Weekday selector */}
            <div className="space-y-2">
              <label className="text-[10px] text-gray-500 font-medium block">Filter Weekdays</label>
              <div className="flex gap-1.5 flex-wrap">
                {[1,2,3,4,5].map((d) => (
                  <button key={d} onClick={() => setWdf((p) => { const s = new Set(p); s.has(d) ? s.delete(d) : s.add(d); return s; })}
                    className={`px-3 py-1 rounded-lg text-xs font-semibold border transition-all ${wdf.has(d) ? "bg-blue-600/20 border-blue-500/40 text-blue-300" : "bg-gray-800 border-gray-700 text-gray-500"}`}>
                    {WD[d]}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <div className="text-[10px] text-gray-400 mt-4 font-mono flex items-center justify-between border-t border-gray-800 pt-3">
            <span>Filtered: <strong className="text-white">{trades.length}</strong> / {executed.length} trades</span>
            <span>Skipped days: <strong className="text-yellow-500">{result.skipped_days}</strong></span>
          </div>
        </div>
      </div>

      {/* Stats 4×4 Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card label="Total Trades" val={String(nets.length)} color="text-white" />
        <Card label="Win Rate" val={`${(wr*100).toFixed(1)}%`} color={wr >= 0.5 ? "text-green-400" : "text-red-400"} />
        <Card label="Net PnL" val={INR(net_pnl)} color={net_pnl >= 0 ? "text-green-400" : "text-red-400"} />
        <Card label="Expectancy" val={INR(expectancy)+"/trade"} color={expectancy >= 0 ? "text-green-400" : "text-red-400"} tooltip="Average P&L per executed trade" />
        
        <Card label="Avg Win" val={INR(aw)} color="text-green-400" />
        <Card label="Avg Loss" val={INR(al)} color="text-red-400" />
        <Card label="Risk Reward (RR)" val={`1 : ${fmt2(rr)}`} color={rr >= 1.0 ? "text-green-400" : "text-yellow-400"} tooltip="Ratio of Average Win to Average Loss" />
        <Card label="Profit Factor" val={isFinite(adv.pf) ? fmt2(adv.pf) : "∞"} color={adv.pf >= 1.5 ? "text-green-400" : adv.pf >= 1 ? "text-yellow-400" : "text-red-400"} tooltip="Gross Profit / Gross Loss" />
        
        <Card label="Max Drawdown" val={INR(mdd)} color="text-red-400" />
        <Card label="Drawdown Days" val={`${adv.maxDDuration} days`} color="text-red-400" tooltip="Max calendar days spent from peak equity to recovery" />
        <Card label="Return / MaxDD" val={isFinite(rmdd) ? fmt2(rmdd) : "—"} color={rmdd >= 2 ? "text-green-400" : rmdd >= 1 ? "text-yellow-400" : "text-red-400"} tooltip="Ratio of Net PnL to Max Drawdown" />
        <Card label="Sharpe Ratio" val={fmt2(sharpe)} color={sharpe >= 1.5 ? "text-green-400" : sharpe >= 0.8 ? "text-yellow-400" : "text-red-400"} tooltip="Annualized risk-adjusted return (Sharpe)" />
        
        <Card label="Kelly Criterion" val={`${kelly.toFixed(1)}%`} color={kelly > 0 ? "text-green-400" : "text-gray-500"} tooltip="Optimal position size percent of capital according to Kelly" />
        <Card label="Max Win Streak" val={String(adv.mw)} color="text-green-400" />
        <Card label="Max Loss Streak" val={String(adv.ml)} color="text-red-400" />
        <Card label="Max Trades in DD" val={String(adv.maxTradesInDd)} color="text-red-400" tooltip="Maximum consecutive trades executed while below equity peak" />
      </div>

      {/* Double Column Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        
        {/* Equity Curve */}
        <div className="bg-gray-900 rounded-xl p-5 border border-gray-800 lg:col-span-3">
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
        <div className="bg-gray-900 rounded-xl p-5 border border-gray-800 lg:col-span-2">
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

      {/* Monthly grid */}
      {years.length > 0 && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden shadow-lg">
          <div className="px-5 py-4 border-b border-gray-800">
            <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider">Year-wise Monthly Returns Grid</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr className="border-b border-gray-800 text-gray-500">
                  <th className="px-4 py-3 text-left font-semibold">Year</th>
                  {MONTHS.map((m) => <th key={m} className="px-2 py-3 text-center font-semibold w-16">{m}</th>)}
                  <th className="px-4 py-3 text-right font-semibold">Total</th>
                  <th className="px-4 py-3 text-right font-semibold">Max DD</th>
                  <th className="px-4 py-3 text-right font-semibold">Ret/MaxDD</th>
                </tr>
              </thead>
              <tbody>
                {years.map((y) => {
                  const yt = Object.values(g[y] ?? {}).reduce((a, b) => a + b, 0);
                  const md = ym[y] ?? 0;
                  const rm = md !== 0 ? yt / Math.abs(md) : null;
                  return (
                    <tr key={y} className="border-b border-gray-800/50 hover:bg-gray-800/20 transition-colors">
                      <td className="px-4 py-2 font-bold text-gray-250">{y}</td>
                      {MONTHS.map((_, mi) => <MCell key={mi} val={g[y]?.[mi]} />)}
                      <td className={`px-4 py-2 text-right font-mono font-bold ${yt >= 0 ? "text-green-400" : "text-red-400"}`}>{INR(yt)}</td>
                      <td className="px-4 py-2 text-right font-mono text-red-400">{INR(md)}</td>
                      <td className={`px-4 py-2 text-right font-mono font-semibold ${rm !== null && rm >= 1 ? "text-green-400" : "text-yellow-400"}`}>{rm !== null ? fmt2(rm) : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Monthly P&L Heatmap (year × month) — click a month to drill into days */}
      {years.length > 0 && (() => {
        const vals = years.flatMap((y) => MONTHS.map((_, m) => g[y]?.[m])).filter((v): v is number => v !== undefined);
        const maxAbs = Math.max(1, ...vals.map((v) => Math.abs(v)));
        const bg = (v: number | undefined) => {
          if (v === undefined) return "rgba(31,41,55,0.4)";
          const a = 0.18 + 0.72 * Math.min(1, Math.abs(v) / maxAbs);
          return v >= 0 ? `rgba(16,185,129,${a})` : `rgba(239,68,68,${a})`;
        };
        return (
          <div className="bg-gray-900 rounded-xl border border-gray-800 p-4 shadow-lg">
            <div className="flex items-center justify-between gap-3 mb-3 pb-2 border-b border-gray-800">
              <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider">Profit / Loss — Monthly Heatmap</h3>
              <div className="flex items-center gap-1 text-[9px] text-gray-500">
                <span className="w-2.5 h-2.5 rounded-sm bg-emerald-600 inline-block" /> Profit
                <span className="w-2.5 h-2.5 rounded-sm bg-rose-600 inline-block ml-1.5" /> Loss
                <span className="ml-2 text-gray-600">· click a month for daily detail</span>
              </div>
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
                            <td key={mi} className="p-0.5">
                              <div
                                className={`h-8 rounded cursor-pointer flex items-center justify-center text-[8px] font-mono text-white/90 hover:ring-1 hover:ring-white/40 ${active ? "ring-2 ring-blue-400" : ""}`}
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

            {/* Month → daily drilldown */}
            {monthDetail && (
              <div className="mt-4 pt-3 border-t border-gray-800">
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-[11px] font-bold text-gray-300">
                    {MONTH_NAMES[monthDetail.m]} {monthDetail.y}
                    <span className={`ml-2 font-mono ${(g[monthDetail.y]?.[monthDetail.m] ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {INR(g[monthDetail.y]?.[monthDetail.m] ?? 0)}
                    </span>
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
                          className={`aspect-square rounded-sm flex items-center justify-center text-[8px] font-mono select-none ${has ? "text-white cursor-default" : "bg-gray-900/40 text-gray-700"}`}
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

      {/* Transactions Analytics */}
      {trades.length > 0 && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-5 shadow-lg space-y-5">
          <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider">Transactions Analytics</h3>
          <AnalyticsBlock title="By Trade Type" rows={analytics.byType} />
          <AnalyticsBlock title="By Year" rows={analytics.byYear} />
        </div>
      )}

      {/* Monte Carlo Simulation */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-5 shadow-lg">
        <div className="border-b border-gray-800 pb-3 mb-4">
          <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider">Monte Carlo Drawdown Simulator</h3>
          <p className="text-[10px] text-gray-500 mt-0.5">Shuffles trade execution sequences 10,000 times to calculate probabilistic max drawdown risk.</p>
        </div>
        <div className="flex items-center gap-6 flex-wrap">
          <div className="flex items-center gap-3">
            <label className="text-xs text-gray-400 font-medium">Confidence Interval</label>
            <input type="range" min={90} max={99} value={mcConf}
              onChange={(e) => setMcConf(Number(e.target.value))} className="accent-blue-500 w-32 cursor-pointer" />
            <span className="text-sm font-bold text-blue-400 w-10">{mcConf}%</span>
          </div>
          <button onClick={runMC} disabled={mcBusy || nets.length === 0}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-800 disabled:text-gray-500 text-white text-xs font-semibold rounded-lg transition-colors shadow-md shadow-blue-900/10">
            {mcBusy ? "Running Simulations…" : "Run 10,000 Shuffles"}
          </button>
          {mcRes !== null && (
            <div className="text-xs text-gray-400 font-mono">
              Projected Drawdown at {mcConf}% confidence:{" "}
              <strong className="text-red-400 text-sm">{INR(mcRes)}</strong>
            </div>
          )}
        </div>
      </div>

      {/* Skip breakdown */}
      {skipped.length > 0 && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden shadow-lg">
          <div className="px-5 py-4 border-b border-gray-800 flex items-center justify-between">
            <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider">
              Skipped Days Log
            </h3>
            <span className="text-xs bg-yellow-900/30 text-yellow-400 border border-yellow-800 px-2 py-0.5 rounded font-mono font-medium">{skipped.length} days skipped</span>
          </div>
          <div className="px-5 py-3 overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800">
                  <th className="py-2 text-left font-semibold">Reason for Skip</th>
                  <th className="py-2 text-right font-semibold">Count</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(
                  skipped.reduce<Record<string, number>>((acc, t) => {
                    acc[t.skip_reason] = (acc[t.skip_reason] ?? 0) + 1; return acc;
                  }, {})
                ).sort((a, b) => b[1] - a[1]).map(([reason, count]) => (
                  <tr key={reason} className="border-b border-gray-800/40 font-mono">
                    <td className="py-2 text-yellow-450">{reason}</td>
                    <td className="py-2 text-right text-gray-400">{count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Trade log */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden shadow-lg">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800">
          <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider">Backtest Execution Log</h3>
          <span className="text-xs text-gray-500 font-mono font-medium">{trades.length} Trades Executed</span>
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
              {trades.map((t) => {
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

      <TradeDrawer trade={selectedTrade} onClose={() => setSelectedTrade(null)} />
    </div>
  );
}

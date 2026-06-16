import { useState, useEffect, useCallback, useRef } from "react";
import {
  getFlowDates, getDots, getOiExpiries, getOiStrikes, getOiAnalysis, getOiTools, getFlowLive,
} from "../api";
import LWChart from "./LWChart";
import type {
  DotsResponse, OiAnalysisResponse, OiToolsResponse, OiContract, FlowLiveResponse,
} from "../types";

type Sub = "dots" | "oi" | "stats" | "spurt" | "bigmove" | "trending" | "active" | "risk";
type Mode = "live" | "historical";

const SUBS: [Sub, string][] = [
  ["dots", "Connecting Dots"],
  ["oi", "OI Analysis"],
  ["stats", "OI Statistics"],
  ["spurt", "OI Spurt"],
  ["bigmove", "Big OI Move"],
  ["trending", "Trending OI"],
  ["active", "Active Strikes"],
  ["risk", "Risk Calc"],
];

const TOOL_SUBS: Sub[] = ["stats", "spurt", "bigmove", "trending", "active"];
const needsExpiry = (s: Sub) => s === "oi" || TOOL_SUBS.includes(s);

// Live mode collapses to the institutional dashboard + risk calc.
const LIVE_SUBS: [Sub, string][] = [["dots", "Live OI Flow"], ["risk", "Risk Calc"]];

// Current NSE lot sizes (revised 1 Jan 2026): NIFTY 65, BANKNIFTY 30
const LOT: Record<string, number> = { NIFTY: 65, BANKNIFTY: 30, FINNIFTY: 60, MIDCPNIFTY: 120 };

const inp =
  "bg-gray-900 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-blue-500";
const INTERVALS = [1, 3, 5, 15, 30, 60];
const fmtN = (n: number | null) => (n == null ? "—" : n.toLocaleString("en-IN"));

function Chip({ v }: { v: number }) {
  if (v > 0) return <span className="inline-flex items-center justify-center w-7 h-6 rounded bg-emerald-600/20 text-emerald-400 border border-emerald-600/30 text-xs font-bold">▲</span>;
  if (v < 0) return <span className="inline-flex items-center justify-center w-7 h-6 rounded bg-red-600/20 text-red-400 border border-red-600/30 text-xs font-bold">▼</span>;
  return <span className="inline-flex items-center justify-center w-7 h-6 rounded bg-gray-800 text-gray-600 border border-gray-700 text-xs">—</span>;
}

function trendPill(t: string) {
  const map: Record<string, string> = {
    "Extreme Bullish": "bg-emerald-600 text-white",
    Bullish: "bg-emerald-600/30 text-emerald-300 border border-emerald-600/40",
    Bearish: "bg-red-600/30 text-red-300 border border-red-600/40",
    "Extreme Bearish": "bg-red-600 text-white",
  };
  return <span className={`px-2.5 py-1 rounded-md text-xs font-bold whitespace-nowrap ${map[t] ?? "bg-gray-800 text-gray-400"}`}>{t} {t.includes("Bullish") ? "↑" : "↓"}</span>;
}

const INTERP_COLOR: Record<string, string> = {
  "Long Buildup": "bg-emerald-600/25 text-emerald-300 border-emerald-600/40",
  "Short Covering": "bg-blue-600/25 text-blue-300 border-blue-600/40",
  "Short Buildup": "bg-red-600/25 text-red-300 border-red-600/40",
  "Long Unwinding": "bg-amber-600/25 text-amber-300 border-amber-600/40",
  Neutral: "bg-gray-800 text-gray-500 border-gray-700",
};
function InterpBadge({ v }: { v: string }) {
  return <span className={`px-2 py-0.5 rounded text-[11px] font-semibold border whitespace-nowrap ${INTERP_COLOR[v] ?? INTERP_COLOR.Neutral}`}>{v}</span>;
}
function chg(n: number) {
  return <span className={n > 0 ? "text-emerald-400" : n < 0 ? "text-red-400" : "text-gray-500"}>{n > 0 ? "+" : ""}{n.toLocaleString("en-IN")}</span>;
}

export default function FlowMatrix() {
  const [sub, setSub] = useState<Sub>("dots");
  const [mode, setMode] = useState<Mode>("historical");
  const [underlying, setUnderlying] = useState("BANKNIFTY");
  const [dates, setDates] = useState<string[]>([]);
  const [date, setDate] = useState("");
  const [interval, setIntv] = useState(15);

  const [dots, setDots] = useState<DotsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [expiries, setExpiries] = useState<string[]>([]);
  const [expiry, setExpiry] = useState("");
  const [strikes, setStrikes] = useState<number[]>([]);
  const [strike, setStrike] = useState<number | "">("");
  const [oi, setOi] = useState<OiAnalysisResponse | null>(null);
  const [tools, setTools] = useState<OiToolsResponse | null>(null);
  const [showChart, setShowChart] = useState(true);

  // Live OI-flow (institutional dashboard) — polls /flow/live while mode=live
  const [liveFlow, setLiveFlow] = useState<FlowLiveResponse | null>(null);
  const [liveErr, setLiveErr] = useState<string | null>(null);
  const livePoll = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (mode !== "live") {
      if (livePoll.current) { clearInterval(livePoll.current); livePoll.current = null; }
      return;
    }
    let cancelled = false;
    const tick = () => {
      getFlowLive(underlying)
        .then((d) => { if (!cancelled) { setLiveFlow(d); setLiveErr(null); } })
        .catch((e) => { if (!cancelled) setLiveErr(e.message); });
    };
    tick();
    livePoll.current = setInterval(tick, 4000);
    return () => { cancelled = true; if (livePoll.current) { clearInterval(livePoll.current); livePoll.current = null; } };
  }, [mode, underlying]);

  useEffect(() => {
    getFlowDates(underlying).then((d) => { setDates(d); if (d.length && !d.includes(date)) setDate(d[0]); }).catch(() => setDates([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [underlying]);

  useEffect(() => {
    if (!needsExpiry(sub) || !date) return;
    getOiExpiries(underlying, date).then((e) => { setExpiries(e); setExpiry((p) => (e.includes(p) ? p : e[0] ?? "")); }).catch(() => setExpiries([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sub, underlying, date]);

  useEffect(() => {
    if (sub !== "oi" || !date || !expiry) return;
    getOiStrikes(underlying, date, expiry).then((s) => { setStrikes(s); setStrike((p) => (typeof p === "number" && s.includes(p) ? p : s[Math.floor(s.length / 2)] ?? "")); }).catch(() => setStrikes([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sub, underlying, date, expiry]);

  const go = useCallback(() => {
    if (sub === "risk") return;
    if (!date) return;
    setLoading(true); setErr(null);
    const done = () => setLoading(false);
    const fail = (e: Error) => { setErr(e.message); setLoading(false); };
    if (sub === "dots") getDots(underlying, date, interval, mode).then((d) => { setDots(d); done(); }).catch(fail);
    else if (sub === "oi") {
      if (!expiry || strike === "") { done(); return; }
      getOiAnalysis(underlying, date, expiry, Number(strike), interval, mode).then((d) => { setOi(d); done(); }).catch(fail);
    } else {
      if (!expiry) { done(); return; }
      getOiTools(underlying, date, expiry, interval).then((d) => { setTools(d); done(); }).catch(fail);
    }
  }, [sub, underlying, date, interval, mode, expiry, strike]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-bold tracking-tight"><span className="text-blue-400">Flow</span>Matrix</h2>
          <span className="text-xs text-gray-500">OI confluence &amp; interpretation engine</span>
        </div>
        <div className="flex flex-wrap bg-gray-950 rounded-lg p-0.5 border border-gray-800">
          {/* Live mode = single institutional OI-flow dashboard; the per-tool tabs
              are historical-OI tools that need intraday OI the platform lacks. */}
          {(mode === "live" ? LIVE_SUBS : SUBS).map(([id, label]) => (
            <button key={id} onClick={() => setSub(id)}
              className={`px-3 py-1 rounded-md text-xs font-semibold transition-colors ${(mode === "live" ? (id === "risk" ? sub === "risk" : sub !== "risk") : sub === id) ? "bg-blue-600 text-white" : "text-gray-400 hover:text-gray-200"}`}>
              {label}
            </button>
          ))}
        </div>
      </div>

      {sub !== "risk" && (
        <div className="flex items-end gap-4 flex-wrap bg-gray-900 border border-gray-800 rounded-xl p-3">
          <div className="flex flex-col gap-1">
            <label className="text-[10px] uppercase tracking-wider text-gray-500">Mode</label>
            <div className="flex gap-1 text-xs">
              {(["live", "historical"] as Mode[]).map((m) => (
                <button key={m} onClick={() => setMode(m)} className={`px-2.5 py-1.5 rounded-lg ${mode === m ? "bg-blue-600 text-white" : "bg-gray-800 text-gray-400"}`}>{m === "live" ? "Live data" : "Historical"}</button>
              ))}
            </div>
          </div>
          <Field label="Name"><select className={inp} value={underlying} onChange={(e) => setUnderlying(e.target.value)}><option>BANKNIFTY</option><option>NIFTY</option></select></Field>
          {mode === "historical" && <>
            <Field label="Date"><select className={inp} value={date} onChange={(e) => setDate(e.target.value)}>{dates.length === 0 && <option>—</option>}{dates.map((d) => <option key={d}>{d}</option>)}</select></Field>
            {needsExpiry(sub) && <Field label="Expiry"><select className={inp} value={expiry} onChange={(e) => setExpiry(e.target.value)}>{expiries.length === 0 && <option>—</option>}{expiries.map((x) => <option key={x}>{x}</option>)}</select></Field>}
            {sub === "oi" && <Field label="Strike"><select className={inp} value={strike} onChange={(e) => setStrike(Number(e.target.value))}>{strikes.length === 0 && <option>—</option>}{strikes.map((s) => <option key={s} value={s}>{s}</option>)}</select></Field>}
            <Field label="Interval"><select className={inp} value={interval} onChange={(e) => setIntv(Number(e.target.value))}>{INTERVALS.map((m) => <option key={m} value={m}>{m} min</option>)}</select></Field>
            <button onClick={go} disabled={loading || !date} className="px-5 py-2 rounded-lg bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white text-sm font-bold">{loading ? "Loading…" : "Go"}</button>
          </>}
          {mode === "live" && (
            <div className="flex items-center gap-2 px-2 py-2 self-center">
              <span className="relative flex h-2.5 w-2.5"><span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" /><span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500" /></span>
              <span className="text-xs text-emerald-400 font-semibold">LIVE · auto-refresh 4s · nearest expiry</span>
            </div>
          )}
        </div>
      )}

      {sub !== "risk" && mode === "historical" && (
        <div className="space-y-2">
          <button onClick={() => setShowChart((s) => !s)}
            className="text-xs text-gray-400 hover:text-gray-200 flex items-center gap-1">
            <span>{showChart ? "▾" : "▸"}</span> {underlying} price chart
          </button>
          {showChart && date && (
            <LWChart underlying={underlying} date={date} interval={interval} height={320} />
          )}
        </div>
      )}

      {err && <div className="text-sm text-red-400 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">{err}</div>}

      {/* LIVE mode: institutional OI-flow dashboard (real-time, polls /flow/live) */}
      {mode === "live" && sub !== "risk" && <LiveFlow data={liveFlow} err={liveErr} />}

      {/* HISTORICAL mode: per-interval confluence + OI tools (DB-backed) */}
      {mode === "historical" && (
        <>
          {sub === "dots" && <DotsTable data={dots} />}
          {sub === "oi" && <OiTable data={oi} />}
          {sub === "stats" && <StatsView data={tools} />}
          {sub === "spurt" && <ContractTable data={tools} which="spurt" title="OI Spurt — biggest last-bucket OI jumps" col="oi_chg_bucket" colLabel="Bucket OI Chg" />}
          {sub === "bigmove" && <ContractTable data={tools} which="big_movement" title="Big OI Movement — largest day-cumulative OI change" col="oi_chg_day" colLabel="Day OI Chg" />}
          {sub === "trending" && <TrendingView data={tools} />}
          {sub === "active" && <ActiveView data={tools} />}
        </>
      )}

      {sub === "risk" && <RiskCalc lot={LOT[underlying] ?? 65} underlying={underlying} />}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="flex flex-col gap-1"><label className="text-[10px] uppercase tracking-wider text-gray-500">{label}</label>{children}</div>;
}

// Compact OI formatter: 650000 -> 6.50L, 8200 -> 8.2K
function fmtOi(n: number): string {
  const a = Math.abs(n);
  if (a >= 1e7) return (n / 1e7).toFixed(2) + "Cr";
  if (a >= 1e5) return (n / 1e5).toFixed(2) + "L";
  if (a >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return String(n);
}

function Kpi({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: "bull" | "bear" | "neutral" }) {
  const c = tone === "bull" ? "text-emerald-400" : tone === "bear" ? "text-red-400" : "text-gray-200";
  return (
    <div className="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 min-w-[110px]">
      <div className="text-[10px] uppercase tracking-wider text-gray-500">{label}</div>
      <div className={`text-base font-bold font-mono ${c}`}>{value}</div>
      {sub != null && <div className="text-[10px] text-gray-500 font-mono">{sub}</div>}
    </div>
  );
}

function LiveFlow({ data, err }: { data: FlowLiveResponse | null; err: string | null }) {
  if (err) return <div className="text-sm text-red-400 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">{err}</div>;
  if (!data) return <Empty text="Connecting to live feed…" />;

  const basis = data.future_price != null ? data.future_price - data.spot_price : null;
  const ceChgTone = data.total_ce_oi_chg >= 0 ? "bear" : "bull";   // CE writing = bearish
  const peChgTone = data.total_pe_oi_chg >= 0 ? "bull" : "bear";   // PE writing = bullish
  const maxCeOi = Math.max(1, ...data.rows.map((r) => r.ce_oi));
  const maxPeOi = Math.max(1, ...data.rows.map((r) => r.pe_oi));

  return (
    <div className="space-y-3">
      {data.stale && (
        <div className="text-[11px] text-amber-400/80 bg-amber-950/20 px-3 py-1.5 rounded-lg border border-amber-900/40">
          Feed offline / market closed — last snapshot {String(data.timestamp).slice(11, 19)}
        </div>
      )}

      {/* KPI strip */}
      <div className="flex flex-wrap gap-2 items-stretch">
        <div className="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 flex flex-col justify-center">
          <div className="text-[10px] uppercase tracking-wider text-gray-500">Bias</div>
          {trendPill(data.verdict)}
        </div>
        <Kpi label="Spot" value={data.spot_price.toLocaleString("en-IN")} />
        {data.future_price != null && (
          <Kpi label="Future" value={data.future_price.toLocaleString("en-IN")}
            sub={basis != null ? `${basis >= 0 ? "+" : ""}${basis.toFixed(1)} basis` : undefined}
            tone={basis != null && basis >= 0 ? "bull" : "bear"} />
        )}
        <Kpi label="PCR" value={data.pcr.toFixed(2)} tone={data.pcr > 1.1 ? "bull" : data.pcr < 0.9 ? "bear" : "neutral"} />
        <Kpi label="Max Pain" value={data.max_pain.toLocaleString("en-IN")}
          sub={data.max_pain_dist != null ? `${data.max_pain_dist >= 0 ? "+" : ""}${data.max_pain_dist.toFixed(0)} vs spot` : undefined} />
        <Kpi label="Support" value={data.support.toLocaleString("en-IN")} tone="bull" sub="max PE OI" />
        <Kpi label="Resistance" value={data.resistance.toLocaleString("en-IN")} tone="bear" sub="max CE OI" />
        {data.expected_range && (
          <Kpi label="Expected Range" value={`${data.expected_range.low.toFixed(0)}–${data.expected_range.high.toFixed(0)}`}
            sub={`±${data.expected_range.straddle.toFixed(0)} (ATM straddle)`} />
        )}
      </div>

      {/* Net OI change CE vs PE */}
      <div className="grid grid-cols-2 gap-2">
        <Kpi label="Total CE OI Δ (resistance side)" value={`${data.total_ce_oi_chg >= 0 ? "+" : ""}${fmtOi(data.total_ce_oi_chg)}`} tone={ceChgTone} sub={`CE OI ${fmtOi(data.total_ce_oi)}`} />
        <Kpi label="Total PE OI Δ (support side)" value={`${data.total_pe_oi_chg >= 0 ? "+" : ""}${fmtOi(data.total_pe_oi_chg)}`} tone={peChgTone} sub={`PE OI ${fmtOi(data.total_pe_oi)}`} />
      </div>

      {/* Top buildups */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="border border-gray-800 rounded-xl overflow-hidden">
          <div className="bg-gray-900 px-3 py-2 text-xs font-bold text-red-300">Top CE OI Buildup (resistance forming)</div>
          <table className="w-full text-sm"><tbody>
            {data.top_ce_buildup.map((r) => (
              <tr key={r.strike} className="border-t border-gray-800/70">
                <td className="px-3 py-1.5 font-mono text-gray-300">{r.strike}</td>
                <td className="px-3 py-1.5 text-right font-mono">{chg(r.ce_oi_chg)}</td>
              </tr>
            ))}
          </tbody></table>
        </div>
        <div className="border border-gray-800 rounded-xl overflow-hidden">
          <div className="bg-gray-900 px-3 py-2 text-xs font-bold text-emerald-300">Top PE OI Buildup (support forming)</div>
          <table className="w-full text-sm"><tbody>
            {data.top_pe_buildup.map((r) => (
              <tr key={r.strike} className="border-t border-gray-800/70">
                <td className="px-3 py-1.5 font-mono text-gray-300">{r.strike}</td>
                <td className="px-3 py-1.5 text-right font-mono">{chg(r.pe_oi_chg)}</td>
              </tr>
            ))}
          </tbody></table>
        </div>
      </div>

      {/* Full per-strike OI flow table */}
      <div className="border border-gray-800 rounded-xl overflow-hidden">
        <div className="bg-gray-900 px-3 py-2 text-xs font-bold text-gray-300">Live OI Flow · {data.underlying} {data.expiry} · {String(data.timestamp).slice(11, 19)}</div>
        <div className="overflow-x-auto max-h-[520px] overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="bg-gray-900/80 sticky top-0 text-gray-400 uppercase tracking-wider">
              <tr>
                <th className="px-2 py-2 text-left">CE Interp</th>
                <th className="px-2 py-2 text-right">CE ΔOI</th>
                <th className="px-2 py-2 text-right">CE OI</th>
                <th className="px-2 py-2 text-center">Strike</th>
                <th className="px-2 py-2 text-left">PE OI</th>
                <th className="px-2 py-2 text-right">PE ΔOI</th>
                <th className="px-2 py-2 text-right">PE Interp</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => {
                const atm = data.expected_range && r.strike === data.expected_range.atm;
                return (
                  <tr key={r.strike} className={`border-t border-gray-800/60 ${atm ? "bg-blue-950/30" : ""}`}>
                    <td className="px-2 py-1"><InterpBadge v={r.ce_interp} /></td>
                    <td className="px-2 py-1 text-right font-mono">{chg(r.ce_oi_chg)}</td>
                    <td className="px-2 py-1 text-right font-mono text-gray-400 relative">
                      <span className="absolute right-0 top-0 h-full bg-red-600/15" style={{ width: `${(r.ce_oi / maxCeOi) * 100}%` }} />
                      <span className="relative">{fmtOi(r.ce_oi)}</span>
                    </td>
                    <td className="px-2 py-1 text-center font-mono font-bold text-gray-200">{r.strike}</td>
                    <td className="px-2 py-1 font-mono text-gray-400 relative">
                      <span className="absolute left-0 top-0 h-full bg-emerald-600/15" style={{ width: `${(r.pe_oi / maxPeOi) * 100}%` }} />
                      <span className="relative">{fmtOi(r.pe_oi)}</span>
                    </td>
                    <td className="px-2 py-1 text-right font-mono">{chg(r.pe_oi_chg)}</td>
                    <td className="px-2 py-1 text-right"><InterpBadge v={r.pe_interp} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function DotsTable({ data }: { data: DotsResponse | null }) {
  if (!data) return <Empty text="Pick a date and hit Go to load the confluence grid." />;
  if (data.message) return <Empty text={data.message} />;
  if (!data.rows.length) return <Empty text="No data for this selection." />;
  const cols = ["Trend", "Price", "OI Interp", "VIX", "VWAP", "Supertrend", "RSI"];
  return (
    <div className="border border-gray-800 rounded-xl overflow-hidden">
      {!data.has_vix && <div className="text-[11px] text-amber-400/80 bg-amber-950/20 px-3 py-1.5 border-b border-gray-800">VIX feed not wired yet — column neutral. VWAP neutral on index (no spot volume).</div>}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-900 text-gray-400 text-xs uppercase tracking-wider"><tr><th className="px-3 py-2 text-left">#</th><th className="px-3 py-2 text-left">Date Time</th>{cols.map((c) => <th key={c} className="px-3 py-2 text-center">{c}</th>)}</tr></thead>
          <tbody>
            {data.rows.map((r, i) => {
              const tint = r.trend.startsWith("Extreme") ? (r.trend.includes("Bullish") ? "bg-emerald-950/20" : "bg-red-950/20") : "";
              return (
                <tr key={r.time} className={`border-t border-gray-800/70 ${tint}`}>
                  <td className="px-3 py-2 text-gray-500">{i + 1}</td>
                  <td className="px-3 py-2 font-mono text-gray-300 whitespace-nowrap">{r.time}</td>
                  <td className="px-3 py-2 text-center">{trendPill(r.trend)}</td>
                  <td className="px-3 py-2 text-center"><Chip v={r.price} /></td>
                  <td className="px-3 py-2 text-center"><Chip v={r.oi} /></td>
                  <td className="px-3 py-2 text-center"><Chip v={r.vix} /></td>
                  <td className="px-3 py-2 text-center"><Chip v={r.vwap} /></td>
                  <td className="px-3 py-2 text-center"><Chip v={r.supertrend} /></td>
                  <td className="px-3 py-2 text-center"><Chip v={r.rsi} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function OiTable({ data }: { data: OiAnalysisResponse | null }) {
  if (!data) return <Empty text="Pick date / expiry / strike and hit Go." />;
  if (data.message) return <Empty text={data.message} />;
  if (!data.rows.length) return <Empty text="No data for this selection." />;
  const brk = (b: { type: string; level: number } | null) => b ? <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${b.type === "D.H.B" ? "bg-emerald-600/30 text-emerald-300" : "bg-red-600/30 text-red-300"}`}>{b.type} ({b.level})</span> : <span className="text-gray-700">—</span>;
  return (
    <div className="border border-gray-800 rounded-xl overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="bg-gray-900 text-gray-400 uppercase tracking-wider"><tr>
          <th className="px-2 py-2 text-left">Time</th><th className="px-2 py-2 text-right">Call OI</th><th className="px-2 py-2 text-right">Call OI Chg</th><th className="px-2 py-2 text-center">Call D.H/L</th><th className="px-2 py-2 text-right">Call LTP</th><th className="px-2 py-2 text-right">Call Chg</th><th className="px-2 py-2 text-center">Call Interp</th><th className="px-2 py-2 text-center bg-gray-950 text-blue-300">Strike</th><th className="px-2 py-2 text-center">Put Interp</th><th className="px-2 py-2 text-right">Put Chg</th><th className="px-2 py-2 text-right">Put LTP</th><th className="px-2 py-2 text-center">Put D.H/L</th><th className="px-2 py-2 text-right">Put OI Chg</th><th className="px-2 py-2 text-right">Put OI</th>
        </tr></thead>
        <tbody>
          {data.rows.map((r) => (
            <tr key={r.time} className="border-t border-gray-800/70 hover:bg-gray-900/40">
              <td className="px-2 py-2 font-mono text-gray-300 whitespace-nowrap">{r.time}</td>
              <td className="px-2 py-2 text-right text-gray-300">{fmtN(r.call_oi)}</td>
              <td className="px-2 py-2 text-right">{chg(r.call_oi_chg)}</td>
              <td className="px-2 py-2 text-center">{brk(r.call_break)}</td>
              <td className="px-2 py-2 text-right text-gray-300">{r.call_ltp ?? "—"}</td>
              <td className="px-2 py-2 text-right">{chg(r.call_ltp_chg)}</td>
              <td className="px-2 py-2 text-center"><InterpBadge v={r.call_interp} /></td>
              <td className="px-2 py-2 text-center font-bold text-blue-300 bg-gray-950">{r.strike}</td>
              <td className="px-2 py-2 text-center"><InterpBadge v={r.put_interp} /></td>
              <td className="px-2 py-2 text-right">{chg(r.put_ltp_chg)}</td>
              <td className="px-2 py-2 text-right text-gray-300">{r.put_ltp ?? "—"}</td>
              <td className="px-2 py-2 text-center">{brk(r.put_break)}</td>
              <td className="px-2 py-2 text-right">{chg(r.put_oi_chg)}</td>
              <td className="px-2 py-2 text-right text-gray-300">{fmtN(r.put_oi)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StatsView({ data }: { data: OiToolsResponse | null }) {
  if (!data) return <Empty text="Pick date / expiry and hit Go." />;
  if (data.message) return <Empty text={data.message} />;
  const s = data.statistics;
  if (!s) return <Empty text="No data." />;
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Total CE OI" v={fmtN(s.total_ce_oi)} tone="red" />
        <Stat label="Total PE OI" v={fmtN(s.total_pe_oi)} tone="emerald" />
        <Stat label="PCR" v={s.pcr == null ? "—" : String(s.pcr)} tone={(s.pcr ?? 1) >= 1 ? "emerald" : "red"} />
        <Stat label="Max Pain" v={String(s.max_pain)} tone="blue" />
      </div>
      <div className="border border-gray-800 rounded-xl overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="bg-gray-900 text-gray-400 uppercase tracking-wider"><tr><th className="px-3 py-2 text-right">CE OI Chg</th><th className="px-3 py-2 text-right">CE OI</th><th className="px-3 py-2 text-center bg-gray-950 text-blue-300">Strike</th><th className="px-3 py-2 text-right">PE OI</th><th className="px-3 py-2 text-right">PE OI Chg</th></tr></thead>
          <tbody>
            {s.rows.map((r) => (
              <tr key={r.strike} className={`border-t border-gray-800/70 ${r.strike === s.max_pain ? "bg-blue-950/30" : ""}`}>
                <td className="px-3 py-2 text-right">{chg(r.ce_oi_chg)}</td>
                <td className="px-3 py-2 text-right text-gray-300">{fmtN(r.ce_oi)}</td>
                <td className="px-3 py-2 text-center font-bold text-blue-300 bg-gray-950">{r.strike}</td>
                <td className="px-3 py-2 text-right text-gray-300">{fmtN(r.pe_oi)}</td>
                <td className="px-3 py-2 text-right">{chg(r.pe_oi_chg)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ContractTable({ data, which, title, col, colLabel }: { data: OiToolsResponse | null; which: "spurt" | "big_movement"; title: string; col: keyof OiContract; colLabel: string }) {
  if (!data) return <Empty text="Pick date / expiry and hit Go." />;
  if (data.message) return <Empty text={data.message} />;
  const rows = data[which];
  if (!rows.length) return <Empty text="No data." />;
  return (
    <div className="border border-gray-800 rounded-xl overflow-x-auto">
      <div className="text-xs text-gray-400 px-3 py-2 border-b border-gray-800 bg-gray-900">{title}</div>
      <table className="w-full text-xs">
        <thead className="bg-gray-900 text-gray-400 uppercase tracking-wider"><tr><th className="px-3 py-2 text-left">#</th><th className="px-3 py-2 text-center">Strike</th><th className="px-3 py-2 text-center">Type</th><th className="px-3 py-2 text-right">{colLabel}</th><th className="px-3 py-2 text-right">OI</th><th className="px-3 py-2 text-right">LTP</th><th className="px-3 py-2 text-center">Interp</th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.strike}-${r.type}`} className="border-t border-gray-800/70">
              <td className="px-3 py-2 text-gray-500">{i + 1}</td>
              <td className="px-3 py-2 text-center font-bold text-blue-300">{r.strike}</td>
              <td className="px-3 py-2 text-center"><span className={r.type === "CE" ? "text-red-400" : "text-emerald-400"}>{r.type}</span></td>
              <td className="px-3 py-2 text-right">{chg(Number(r[col]))}</td>
              <td className="px-3 py-2 text-right text-gray-300">{fmtN(r.oi)}</td>
              <td className="px-3 py-2 text-right text-gray-300">{r.ltp ?? "—"}</td>
              <td className="px-3 py-2 text-center"><InterpBadge v={r.interp} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TrendingView({ data }: { data: OiToolsResponse | null }) {
  if (!data) return <Empty text="Pick date / expiry and hit Go." />;
  if (data.message) return <Empty text={data.message} />;
  const t = data.trending;
  if (!t) return <Empty text="No data." />;
  const bullish = t.verdict === "Bullish";
  return (
    <div className="space-y-4">
      <div className={`rounded-xl p-5 border ${bullish ? "bg-emerald-950/30 border-emerald-700/40" : t.verdict === "Bearish" ? "bg-red-950/30 border-red-700/40" : "bg-gray-900 border-gray-800"}`}>
        <div className="text-xs uppercase tracking-wider text-gray-400 mb-1">Net Writing Verdict</div>
        <div className={`text-3xl font-extrabold ${bullish ? "text-emerald-400" : t.verdict === "Bearish" ? "text-red-400" : "text-gray-300"}`}>{t.verdict} {bullish ? "↑" : t.verdict === "Bearish" ? "↓" : "→"}</div>
      </div>
      <div className="h-6 rounded-full overflow-hidden flex border border-gray-800">
        <div className="bg-emerald-600 flex items-center justify-center text-[11px] font-bold text-white" style={{ width: `${t.bull_pct}%` }}>{t.bull_pct}% Bull</div>
        <div className="bg-red-600 flex items-center justify-center text-[11px] font-bold text-white" style={{ width: `${t.bear_pct}%` }}>{t.bear_pct}% Bear</div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Stat label="CE OI Change (Call writing)" v={chg(t.ce_oi_chg)} tone="red" />
        <Stat label="PE OI Change (Put writing)" v={chg(t.pe_oi_chg)} tone="emerald" />
      </div>
      <p className="text-xs text-gray-500">Put writing (PE OI ↑) = support / bullish. Call writing (CE OI ↑) = resistance / bearish.</p>
    </div>
  );
}

function ActiveView({ data }: { data: OiToolsResponse | null }) {
  if (!data) return <Empty text="Pick date / expiry and hit Go." />;
  if (data.message) return <Empty text={data.message} />;
  const rows = data.active_strikes;
  if (!rows.length) return <Empty text="No data." />;
  const maxTot = Math.max(...rows.map((r) => r.total_oi), 1);
  return (
    <div className="border border-gray-800 rounded-xl overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="bg-gray-900 text-gray-400 uppercase tracking-wider"><tr><th className="px-3 py-2 text-left">#</th><th className="px-3 py-2 text-center">Strike</th><th className="px-3 py-2 text-right">CE OI</th><th className="px-3 py-2 text-right">PE OI</th><th className="px-3 py-2 text-right">Total OI</th><th className="px-3 py-2 text-left">Concentration</th><th className="px-3 py-2 text-center">Bias</th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.strike} className="border-t border-gray-800/70">
              <td className="px-3 py-2 text-gray-500">{i + 1}</td>
              <td className="px-3 py-2 text-center font-bold text-blue-300">{r.strike}</td>
              <td className="px-3 py-2 text-right text-red-300">{fmtN(r.ce_oi)}</td>
              <td className="px-3 py-2 text-right text-emerald-300">{fmtN(r.pe_oi)}</td>
              <td className="px-3 py-2 text-right text-gray-200 font-semibold">{fmtN(r.total_oi)}</td>
              <td className="px-3 py-2"><div className="h-2.5 rounded bg-gray-800 overflow-hidden w-40"><div className="h-full bg-blue-500" style={{ width: `${(r.total_oi / maxTot) * 100}%` }} /></div></td>
              <td className="px-3 py-2 text-center"><span className={`px-2 py-0.5 rounded text-[10px] font-bold ${r.bias === "Put-heavy" ? "bg-emerald-600/25 text-emerald-300" : "bg-red-600/25 text-red-300"}`}>{r.bias}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RiskCalc({ lot, underlying }: { lot: number; underlying: string }) {
  const [capital, setCapital] = useState(100000);
  const [riskPct, setRiskPct] = useState(2);
  const [entry, setEntry] = useState(200);
  const [sl, setSl] = useState(150);
  const perUnit = Math.abs(entry - sl);
  const riskAmt = capital * (riskPct / 100);
  const qty = perUnit > 0 ? Math.floor(riskAmt / perUnit) : 0;
  const lots = Math.floor(qty / lot);
  const actualQty = lots * lot;
  const actualRisk = actualQty * perUnit;
  const f = "bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 w-full focus:outline-none focus:border-blue-500";
  return (
    <div className="grid md:grid-cols-2 gap-6 max-w-3xl">
      <div className="space-y-3">
        <h3 className="font-bold text-sm text-gray-300">Risk Calculator · {underlying} (lot {lot})</h3>
        <NumF label="Capital (₹)" v={capital} set={setCapital} cls={f} />
        <NumF label="Risk per trade (%)" v={riskPct} set={setRiskPct} cls={f} step={0.5} />
        <NumF label="Entry premium (₹)" v={entry} set={setEntry} cls={f} />
        <NumF label="Stop-loss premium (₹)" v={sl} set={setSl} cls={f} />
      </div>
      <div className="space-y-3">
        <Stat label="Risk Amount" v={`₹${riskAmt.toLocaleString("en-IN")}`} tone="amber" />
        <Stat label="Risk / unit" v={`₹${perUnit}`} tone="blue" />
        <Stat label="Position Size" v={`${lots} lots · ${actualQty.toLocaleString("en-IN")} qty`} tone="emerald" />
        <Stat label="Actual ₹ at risk" v={`₹${actualRisk.toLocaleString("en-IN")}`} tone={actualRisk > riskAmt ? "red" : "emerald"} />
        <p className="text-xs text-gray-500">Position rounded down to whole lots. Actual risk = lots × lot-size × (entry − SL).</p>
      </div>
    </div>
  );
}

function NumF({ label, v, set, cls, step }: { label: string; v: number; set: (n: number) => void; cls: string; step?: number }) {
  return <div><label className="text-[10px] uppercase tracking-wider text-gray-500 block mb-1">{label}</label><input type="number" step={step} value={v} onChange={(e) => set(Number(e.target.value))} className={cls} /></div>;
}

function Stat({ label, v, tone }: { label: string; v: React.ReactNode; tone: string }) {
  const c: Record<string, string> = {
    red: "text-red-400", emerald: "text-emerald-400", blue: "text-blue-400", amber: "text-amber-400",
  };
  return <div className="bg-gray-900 border border-gray-800 rounded-xl p-3"><div className="text-[10px] uppercase tracking-wider text-gray-500">{label}</div><div className={`text-xl font-extrabold mt-1 ${c[tone] ?? "text-gray-200"}`}>{v}</div></div>;
}

function Empty({ text }: { text: string }) {
  return <div className="h-64 flex items-center justify-center text-gray-600 text-sm border border-dashed border-gray-800 rounded-xl">{text}</div>;
}

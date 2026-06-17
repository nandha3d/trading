import { useState, useEffect } from "react";
import LWChart from "./LWChart";
import MarketRegimeCard from "./MarketRegimeCard";
import SupportResistancePanel from "./SupportResistancePanel";
import MarketAlertsPanel from "./MarketAlertsPanel";
import { getStatus, getFlowDates, getMarketSnapshot, getMarketLevels, getMarketAlerts, getExpiries } from "../api";
import type { DbStatus } from "../types";

const fmtM = (n: number) =>
  n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1_000 ? `${(n / 1_000).toFixed(0)}K` : String(n);

const INTERVALS = [1, 3, 5, 15, 30, 60];

export default function Dashboard() {
  const [symbol, setSymbol] = useState("NIFTY");
  const [interval, setIntv] = useState(5);
  const [dates, setDates] = useState<string[]>([]);
  const [date, setDate] = useState("");
  const [status, setStatus] = useState<DbStatus | null>(null);
  
  // New State
  const [snapshot, setSnapshot] = useState<any>(null);
  const [levels, setLevels] = useState<any[]>([]);
  const [alerts, setAlerts] = useState<any[]>([]);
  const [expiries, setExpiries] = useState<string[]>([]);
  const [selectedExpiry, setSelectedExpiry] = useState("");

  useEffect(() => { getStatus().then(setStatus).catch(() => null); }, []);
  
  useEffect(() => {
    getFlowDates(symbol).then((d) => { 
      setDates(d); 
      setDate((p) => (d.includes(p) ? p : d[0] ?? "")); 
    }).catch(() => setDates([]));
    
    getExpiries(symbol).then((exps) => {
      setExpiries(exps);
      setSelectedExpiry(exps[0] ?? "");
    }).catch(() => setExpiries([]));
  }, [symbol]);

  useEffect(() => {
    if (symbol) {
      getMarketSnapshot(symbol).then(setSnapshot).catch(() => setSnapshot(null));
      getMarketAlerts(symbol).then((a) => setAlerts(a.alerts)).catch(() => setAlerts([]));
    }
  }, [symbol, date]);

  useEffect(() => {
    if (symbol && selectedExpiry) {
      getMarketLevels(symbol, selectedExpiry).then((l) => setLevels(l.levels)).catch(() => setLevels([]));
    }
  }, [symbol, selectedExpiry, date]);

  const spot = status?.spot_1m;
  const spotData = snapshot?.spot;

  return (
    <div className="space-y-6 max-w-[1400px] mx-auto">
      {/* Header bar */}
      <div className="flex items-center justify-between flex-wrap gap-4 border-b border-gray-800 pb-4">
        <div>
          <h2 className="text-2xl font-extrabold tracking-tight text-white flex items-center gap-2">
            📊 Market Dashboard
          </h2>
          <p className="text-xs text-gray-400 mt-1">Live market snapshots, automated regime classification, and support/resistance detection</p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex bg-gray-900 rounded-xl p-0.5 border border-gray-800">
            {["NIFTY", "BANKNIFTY", "FINNIFTY"].map((s) => (
              <button key={s} onClick={() => setSymbol(s)}
                className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${symbol === s ? "bg-blue-600 text-white shadow-md shadow-blue-900/30" : "text-gray-400 hover:text-gray-200"}`}>{s}</button>
            ))}
          </div>
          
          <select value={date} onChange={(e) => setDate(e.target.value)}
            className="bg-gray-900 border border-gray-800 hover:border-gray-700 rounded-xl px-3 py-1.5 text-xs text-gray-200 focus:outline-none transition-colors">
            {dates.length === 0 && <option>No dates available</option>}
            {dates.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
          
          <div className="flex bg-gray-900 rounded-xl p-0.5 border border-gray-800">
            {INTERVALS.map((v) => (
              <button key={v} onClick={() => setIntv(v)}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${interval === v ? "bg-blue-600 text-white shadow-md shadow-blue-900/30" : "text-gray-400 hover:text-gray-200"}`}>{v}m</button>
            ))}
          </div>
        </div>
      </div>

      {/* Index live cards */}
      {spotData ? (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3.5">
          <Card label={`${symbol} LTP`} v={spotData.ltp.toLocaleString()} color={spotData.change >= 0 ? "text-emerald-400" : "text-rose-400"} />
          <Card label="Day Change" v={`${spotData.change >= 0 ? "+" : ""}${spotData.change} (${spotData.change_pct.toFixed(2)}%)`} color={spotData.change >= 0 ? "text-emerald-400" : "text-rose-400"} />
          <Card label="Day Open" v={spotData.open.toLocaleString()} />
          <Card label="Day High" v={spotData.high.toLocaleString()} color="text-emerald-400/80" />
          <Card label="Day Low" v={spotData.low.toLocaleString()} color="text-rose-400/80" />
        </div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3.5 animate-pulse">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="bg-gray-900/50 border border-gray-800/80 rounded-xl h-[70px]" />
          ))}
        </div>
      )}

      {/* India VIX & FINNIFTY metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3.5">
        {snapshot?.vix != null ? (
          <>
            <Card label="India VIX" v={snapshot.vix.toFixed(2)} color={
              snapshot.vix > 20 ? "text-rose-400" : snapshot.vix > 14 ? "text-amber-400" : "text-emerald-400"
            } />
            <Card label="VIX Regime" v={
              snapshot.vix > 25 ? "HIGH VOL" : snapshot.vix > 18 ? "ELEVATED" : snapshot.vix > 12 ? "NORMAL" : "LOW VOL"
            } color={
              snapshot.vix > 25 ? "text-rose-400" : snapshot.vix > 18 ? "text-amber-400" : "text-emerald-400"
            } />
          </>
        ) : (
          <>
            <Card label="India VIX" v="—" color="text-gray-500" />
            <Card label="VIX Regime" v="—" color="text-gray-500" />
          </>
        )}
        {snapshot?.finnifty != null ? (
          <>
            <Card label="FINNIFTY LTP" v={snapshot.finnifty.ltp?.toLocaleString() ?? "—"} color={
              (snapshot.finnifty.change ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"
            } />
            <Card label="FINNIFTY Chg" v={
              snapshot.finnifty.change != null
                ? `${snapshot.finnifty.change >= 0 ? "+" : ""}${snapshot.finnifty.change.toFixed(1)} (${(snapshot.finnifty.change_pct ?? 0).toFixed(2)}%)`
                : "—"
            } color={
              (snapshot.finnifty.change ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"
            } />
          </>
        ) : (
          <>
            <Card label="FINNIFTY LTP" v="—" color="text-gray-500" />
            <Card label="FINNIFTY Chg" v="—" color="text-gray-500" />
          </>
        )}
      </div>

      {/* Regime, Levels & Alerts Panels */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div>
          <MarketRegimeCard regime={snapshot?.regime ?? "LOW_VOLATILITY"} />
        </div>
        <div>
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[10px] uppercase font-bold text-gray-500">Filter Expiry</span>
            <select
              value={selectedExpiry}
              onChange={(e) => setSelectedExpiry(e.target.value)}
              className="bg-gray-900 border border-gray-800 rounded-lg px-2.5 py-1 text-[10px] text-gray-300 focus:outline-none"
            >
              {expiries.map((exp) => (
                <option key={exp} value={exp}>{exp}</option>
              ))}
            </select>
          </div>
          <SupportResistancePanel levels={levels} />
        </div>
        <div>
          <MarketAlertsPanel alerts={alerts} />
        </div>
      </div>

      {/* Main chart */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-4 shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-800 pb-3 mb-4">
          <span className="text-xs uppercase font-extrabold tracking-wider text-gray-400">
            📊 Chart: {symbol} · {date || "—"}
          </span>
          <span className="text-xs text-gray-500 font-mono">Candles loaded: {spot ? fmtM(spot.rows) : "…"}</span>
        </div>
        {date ? (
          <div className="rounded-xl overflow-hidden border border-gray-850">
            <LWChart underlying={symbol} date={date} interval={interval} height={460} />
          </div>
        ) : (
          <div className="h-[460px] flex flex-col items-center justify-center text-gray-600 border border-dashed border-gray-800 rounded-2xl bg-gray-950/20 select-none">
            <span className="text-5xl mb-3 opacity-30">📉</span>
            <p className="text-sm font-semibold text-gray-500">No trading dates available for chart</p>
          </div>
        )}
      </div>
    </div>
  );
}

function Card({ label, v, color }: { label: string; v: string; color?: string }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-3.5 hover:border-gray-750 transition-all duration-300">
      <div className="text-[10px] uppercase font-bold tracking-wider text-gray-500">{label}</div>
      <div className={`text-lg font-extrabold mt-1.5 tracking-tight ${color ?? "text-gray-100"}`}>{v}</div>
    </div>
  );
}

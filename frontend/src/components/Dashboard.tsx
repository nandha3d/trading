import { useState, useEffect } from "react";
import LWChart from "./LWChart";
import { getStatus, getFlowDates } from "../api";
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

  useEffect(() => { getStatus().then(setStatus).catch(() => null); }, []);
  useEffect(() => {
    getFlowDates(symbol).then((d) => { setDates(d); setDate((p) => (d.includes(p) ? p : d[0] ?? "")); }).catch(() => setDates([]));
  }, [symbol]);

  const opt = status?.options_1m;
  const spot = status?.spot_1m;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-xl font-bold tracking-tight">Market Dashboard</h2>
          <p className="text-xs text-gray-500">Candlestick charts from this platform's validated data store</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex bg-gray-950 rounded-lg p-0.5 border border-gray-800">
            {["NIFTY", "BANKNIFTY"].map((s) => (
              <button key={s} onClick={() => setSymbol(s)}
                className={`px-3 py-1 rounded-md text-xs font-semibold ${symbol === s ? "bg-blue-600 text-white" : "text-gray-400 hover:text-gray-200"}`}>{s}</button>
            ))}
          </div>
          <select value={date} onChange={(e) => setDate(e.target.value)}
            className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200">
            {dates.length === 0 && <option>—</option>}
            {dates.map((d) => <option key={d}>{d}</option>)}
          </select>
          <div className="flex bg-gray-950 rounded-lg p-0.5 border border-gray-800">
            {INTERVALS.map((v) => (
              <button key={v} onClick={() => setIntv(v)}
                className={`px-2.5 py-1 rounded-md text-xs font-semibold ${interval === v ? "bg-blue-600 text-white" : "text-gray-400 hover:text-gray-200"}`}>{v}m</button>
            ))}
          </div>
        </div>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card label="Option Rows" v={opt ? fmtM(opt.rows) : "…"} tone="blue" />
        <Card label="Spot Rows" v={spot ? fmtM(spot.rows) : "…"} tone="emerald" />
        <Card label="Options Coverage" v={opt?.ts_max?.slice(0, 10) ?? "…"} sub={`from ${opt?.ts_min?.slice(0, 10) ?? "…"}`} tone="amber" />
        <Card label="Spot Coverage" v={spot?.ts_max?.slice(0, 10) ?? "…"} sub={`from ${spot?.ts_min?.slice(0, 10) ?? "…"}`} tone="violet" />
      </div>

      {/* Main chart */}
      <div>
        <div className="text-xs uppercase tracking-wider text-gray-500 mb-2">{symbol} · {date || "—"}</div>
        {date ? <LWChart underlying={symbol} date={date} interval={interval} height={520} />
              : <div className="h-[520px] flex items-center justify-center text-gray-600 border border-dashed border-gray-800 rounded-xl">No trading dates</div>}
      </div>

      <p className="text-[11px] text-gray-600">
        Charts: TradingView Lightweight-Charts rendering this platform's DuckDB
        candles (validated vs NSE bhavcopy). Note: live NSE index data on the
        TradingView <em>embed</em> widget is gated by TradingView (paid), so we
        render our own stored data instead.
      </p>
    </div>
  );
}

function Card({ label, v, sub, tone }: { label: string; v: string; sub?: string; tone: string }) {
  const c: Record<string, string> = {
    blue: "text-blue-400", emerald: "text-emerald-400", amber: "text-amber-400", violet: "text-violet-400",
  };
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-3">
      <div className="text-[10px] uppercase tracking-wider text-gray-500">{label}</div>
      <div className={`text-xl font-extrabold mt-1 ${c[tone] ?? "text-gray-200"}`}>{v}</div>
      {sub && <div className="text-[10px] text-gray-600 mt-0.5">{sub}</div>}
    </div>
  );
}

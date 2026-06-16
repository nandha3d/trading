import { useState, useEffect, useMemo, useRef } from "react";
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, Legend, ResponsiveContainer
} from "recharts";
import { getExpiries } from "../api";
import type { LiveTelemetryResponse } from "../types";

const INR = (n: number) => {
  const abs = Math.abs(n);
  const s = abs >= 100000 ? (abs / 100000).toFixed(2) + " L" : abs.toLocaleString("en-IN", { maximumFractionDigits: 0 });
  return `₹${s}`;
};

export default function InstitutionalAnalytics() {
  const [underlying, setUnderlying] = useState<"NIFTY" | "BANKNIFTY">("NIFTY");
  const [expiries, setExpiries] = useState<string[]>([]);
  const [selectedExpiry, setSelectedExpiry] = useState<string>("");
  const [telemetry, setTelemetry] = useState<LiveTelemetryResponse | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // 1. Fetch expiries on mount or underlying change
  useEffect(() => {
    getExpiries(underlying)
      .then((exps) => {
        setExpiries(exps);
        if (exps.length > 0) {
          setSelectedExpiry(exps[0]);
        } else {
          setSelectedExpiry("");
        }
      })
      .catch((e) => setError(`Failed to fetch expiries: ${e.message}`));
  }, [underlying]);

  // 2. Setup WebSocket connection for live telemetry stream
  useEffect(() => {
    if (!selectedExpiry) return;
    
    // Close existing connection if any
    if (wsRef.current) {
      wsRef.current.close();
    }
    
    setConnected(false);
    setTelemetry(null);
    
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const wsUrl = `${proto}//${host}/api/live/stream`;
    
    logger_info(`Connecting to live data stream: ${wsUrl}`);
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;
    
    ws.onopen = () => {
      setConnected(true);
      setError(null);
      // Send subscription packet
      ws.send(JSON.stringify({
        action: "subscribe",
        underlying,
        expiry: selectedExpiry
      }));
    };
    
    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.error) {
          setError(payload.error);
        } else {
          setTelemetry(payload);
        }
      } catch (err) {
        console.error("Error parsing WebSocket payload:", err);
      }
    };
    
    ws.onerror = () => {
      setError("Live telemetry connection error. Retrying...");
      setConnected(false);
    };
    
    ws.onclose = () => {
      setConnected(false);
      logger_info("Live data stream disconnected");
    };
    
    return () => {
      if (ws) {
        ws.close();
      }
    };
  }, [underlying, selectedExpiry]);

  // Helper logger
  function logger_info(msg: string) {
    console.log(`[InstitutionalAnalytics] ${msg}`);
  }

  // Filter nearest strikes to ATM for cleaner visualization
  const filteredChain = useMemo(() => {
    if (!telemetry || !telemetry.chain || telemetry.chain.length === 0) return [];
    const spot = telemetry.spot_price;
    
    // Sort by absolute distance from ATM
    const sortedByDist = [...telemetry.chain].sort(
      (a, b) => Math.abs(a.strike - spot) - Math.abs(b.strike - spot)
    );
    
    // Take the 10 closest strikes and sort them by strike value
    const nearest = sortedByDist.slice(0, 10).sort((a, b) => a.strike - b.strike);
    
    return nearest.map((row) => ({
      strike: row.strike,
      ce_oi: row.ce?.oi ?? 0,
      pe_oi: row.pe?.oi ?? 0,
      ce_oi_change: row.ce?.oi_change ?? 0,
      pe_oi_change: row.pe?.oi_change ?? 0,
      ce_iv: row.ce?.iv ?? 0,
      pe_iv: row.pe?.iv ?? 0
    }));
  }, [telemetry]);

  return (
    <div className="flex flex-col h-full gap-6">
      
      {/* Expiry & Underlying selector */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 flex flex-wrap items-center gap-6 shadow-lg">
        {/* Toggle Underlying */}
        <div className="flex bg-gray-950 rounded-lg p-1 border border-gray-700">
          {(["NIFTY", "BANKNIFTY"] as const).map((u) => (
            <button
              key={u}
              type="button"
              onClick={() => setUnderlying(u)}
              className={`px-4 py-1.5 rounded-md text-xs font-bold transition-all ${
                underlying === u ? "bg-blue-600 text-white shadow-md shadow-blue-900/20" : "text-gray-400 hover:text-gray-250"
              }`}
            >
              {u}
            </button>
          ))}
        </div>

        {/* Expiry Select */}
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-gray-500 font-bold uppercase tracking-wider">Expiry</span>
          <select
            value={selectedExpiry}
            onChange={(e) => setSelectedExpiry(e.target.value)}
            className="bg-gray-950 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500 min-w-[140px] font-semibold"
          >
            {expiries.map((exp) => (
              <option key={exp} value={exp}>{exp}</option>
            ))}
          </select>
        </div>

        {/* Connection status */}
        <div className="flex items-center gap-2 ml-auto">
          {connected ? (
            <span className="flex items-center gap-1.5 text-[10px] text-green-400 font-semibold bg-green-950/40 border border-green-800/40 px-2.5 py-1 rounded-full font-mono">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400 inline-block animate-ping" />
              LIVE TELEMETRY ACTIVE (2S Ticks)
            </span>
          ) : (
            <span className="flex items-center gap-1.5 text-[10px] text-yellow-400 font-semibold bg-yellow-950/40 border border-yellow-800/40 px-2.5 py-1 rounded-full font-mono">
              <span className="w-1.5 h-1.5 rounded-full bg-yellow-400 inline-block" />
              CONNECTING TO REAL-TIME DATA STREAM...
            </span>
          )}
        </div>
      </div>

      {error && (
        <div className="bg-red-950/30 border border-red-800/50 rounded-lg px-4 py-3 text-xs text-red-400">
          ⚠️ {error}
        </div>
      )}

      {/* Main summary row */}
      {telemetry && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div className="bg-gray-900 border border-gray-800 p-4 rounded-xl shadow">
            <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1 font-bold">Spot Price</div>
            <div className="text-xl font-black text-green-400 font-mono">
              {telemetry.spot_price.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
            </div>
          </div>
          <div className="bg-gray-900 border border-gray-800 p-4 rounded-xl shadow">
            <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1 font-bold">Put-Call Ratio (PCR)</div>
            <div className={`text-xl font-black font-mono ${telemetry.pcr >= 1.0 ? "text-green-400" : "text-yellow-400"}`}>
              {telemetry.pcr}
            </div>
          </div>
          <div className="bg-gray-900 border border-gray-800 p-4 rounded-xl shadow">
            <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1 font-bold">Max Pain Strike</div>
            <div className="text-xl font-black text-blue-400 font-mono">
              {telemetry.max_pain.toLocaleString("en-IN")}
            </div>
          </div>
          <div className="bg-gray-900 border border-gray-800 p-4 rounded-xl shadow">
            <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1 font-bold">Total Put OI</div>
            <div className="text-xl font-black text-gray-250 font-mono">
              {(telemetry.total_pe_oi).toLocaleString("en-IN")}
            </div>
          </div>
          <div className="bg-gray-900 border border-gray-800 p-4 rounded-xl shadow">
            <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1 font-bold">Total Call OI</div>
            <div className="text-xl font-black text-gray-250 font-mono">
              {(telemetry.total_ce_oi).toLocaleString("en-IN")}
            </div>
          </div>
        </div>
      )}

      {/* Analytics Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        
        {/* Chart 1: Live Multi-Strike OI */}
        <div className="bg-gray-900 rounded-xl p-5 border border-gray-800 shadow-lg">
          <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-4">Live Multi-Strike Open Interest</h3>
          <div className="h-[260px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={filteredChain} margin={{ top: 5, right: 5, left: 10, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                <XAxis dataKey="strike" stroke="#9ca3af" fontSize={10} />
                <YAxis stroke="#9ca3af" fontSize={10} tickFormatter={(v) => (v / 100000).toFixed(1) + "L"} />
                <Tooltip
                  contentStyle={{ backgroundColor: "#090d16", borderColor: "#1f2937" }}
                  labelStyle={{ color: "#9ca3af", fontWeight: "bold" }}
                  formatter={(val: number) => [val.toLocaleString("en-IN") + " contracts", ""]}
                />
                <Legend verticalAlign="top" height={36} iconType="circle" />
                <Bar dataKey="ce_oi" name="Call OI (Resistance)" fill="#ef4444" radius={[4, 4, 0, 0]} />
                <Bar dataKey="pe_oi" name="Put OI (Support)" fill="#10b981" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Chart 2: Volatility Smile / Skew */}
        <div className="bg-gray-900 rounded-xl p-5 border border-gray-800 shadow-lg">
          <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-4">Implied Volatility Smile (IV Skew)</h3>
          <div className="h-[260px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={filteredChain} margin={{ top: 5, right: 5, left: 10, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                <XAxis dataKey="strike" stroke="#9ca3af" fontSize={10} />
                <YAxis stroke="#9ca3af" fontSize={10} tickFormatter={(v) => `${v}%`} />
                <Tooltip
                  contentStyle={{ backgroundColor: "#090d16", borderColor: "#1f2937" }}
                  labelStyle={{ color: "#9ca3af", fontWeight: "bold" }}
                  formatter={(val: number) => [`${val.toFixed(2)}%`, ""]}
                />
                <Legend verticalAlign="top" height={36} iconType="circle" />
                <Line type="monotone" dataKey="ce_iv" name="Call IV" stroke="#ef4444" strokeWidth={2.5} dot={false} />
                <Line type="monotone" dataKey="pe_iv" name="Put IV" stroke="#10b981" strokeWidth={2.5} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Chart 3: PCR Trend Tracker */}
        <div className="bg-gray-900 rounded-xl p-5 border border-gray-800 shadow-lg">
          <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-4">Put-Call Ratio (PCR) Velocity</h3>
          <div className="h-[260px]">
            {telemetry && telemetry.pcr_trend.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={telemetry.pcr_trend} margin={{ top: 5, right: 5, left: 10, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                  <XAxis dataKey="time" stroke="#9ca3af" fontSize={9} />
                  <YAxis stroke="#9ca3af" fontSize={10} domain={["auto", "auto"]} />
                  <Tooltip
                    contentStyle={{ backgroundColor: "#090d16", borderColor: "#1f2937" }}
                    labelStyle={{ color: "#9ca3af", fontWeight: "bold" }}
                  />
                  <Legend verticalAlign="top" height={36} iconType="circle" />
                  <Line type="monotone" dataKey="pcr" name="PCR Value" stroke="#3b82f6" strokeWidth={2.5} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-gray-500 text-xs font-medium">
                Accumulating session data points...
              </div>
            )}
          </div>
        </div>

        {/* Widget 4: Institutional Block Trade Spotter */}
        <div className="bg-gray-900 rounded-xl p-5 border border-gray-800 shadow-lg flex flex-col h-[325px]">
          <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-4 flex-shrink-0">
            Institutional Block Trade Spotter
          </h3>
          <div className="flex-1 overflow-y-auto pr-1">
            {telemetry && telemetry.block_trades.length > 0 ? (
              <table className="w-full text-xs text-left border-collapse">
                <thead>
                  <tr className="text-gray-500 border-b border-gray-800 pb-2">
                    <th className="py-2 font-semibold">Time</th>
                    <th className="py-2 font-semibold">Contract</th>
                    <th className="py-2 font-semibold">Action</th>
                    <th className="py-2 text-right font-semibold">Qty (Lots)</th>
                    <th className="py-2 text-right font-semibold">LTP</th>
                    <th className="py-2 text-right font-semibold">Trade Value</th>
                  </tr>
                </thead>
                <tbody>
                  {telemetry.block_trades.map((alert, idx) => {
                    const rowClass = idx === 0 ? "animate-pulse bg-blue-900/10 font-bold" : "";
                    const badgeClass = alert.action === "BUY" 
                      ? "bg-green-950 text-green-400 border-green-800/40" 
                      : "bg-red-950 text-red-400 border-red-800/40";
                    const lots = Math.round(alert.qty / telemetry.total_ce_oi * 100) || Math.round(alert.qty / (underlying === "NIFTY" ? 75 : 35));
                    
                    return (
                      <tr key={idx} className={`border-b border-gray-850/60 transition-colors font-mono hover:bg-gray-850/20 ${rowClass}`}>
                        <td className="py-2 text-gray-500 text-[11px]">{alert.timestamp}</td>
                        <td className="py-2 font-semibold text-gray-300">
                          {alert.strike} {alert.option_type}
                        </td>
                        <td className="py-2">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${badgeClass}`}>
                            {alert.action}
                          </span>
                        </td>
                        <td className="py-2 text-right text-gray-200">{alert.qty.toLocaleString("en-IN")} ({lots})</td>
                        <td className="py-2 text-right text-gray-400">₹{alert.price}</td>
                        <td className="py-2 text-right text-green-400 font-bold">{INR(alert.value)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <div className="h-full flex items-center justify-center text-gray-500 text-xs font-medium">
                Scanning options block trades (Alerts trigger when trade volumes {">"} 5,000 contracts)...
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

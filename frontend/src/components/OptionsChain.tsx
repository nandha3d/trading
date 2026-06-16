import React, { useState, useEffect, useMemo, useRef } from "react";
import {
  getExpiries, getTradeDates, getOptionsChainData, getPayoffCurve,
  saveStrategy, listStrategies, deleteStrategy
} from "../api";
import type { OptionsChainResponse, PayoffResponse, SavedStrategy, PayoffLegSpec } from "../types";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, ComposedChart, Line, Area, ReferenceLine, ReferenceDot
} from "recharts";

interface BuilderLeg extends PayoffLegSpec {
  id: string;
}

const LOT_SIZES: Record<string, number> = { NIFTY: 75, BANKNIFTY: 35 };

function getLegLtp(data: OptionsChainResponse | null, leg: BuilderLeg): number | null {
  const row = data?.chain.find(r => r.strike === leg.strike);
  if (!row) return null;
  return (leg.opt_type === "CE" ? row.ce?.close : row.pe?.close) ?? null;
}

function getLegPnl(data: OptionsChainResponse | null, leg: BuilderLeg): number | null {
  const ltp = getLegLtp(data, leg);
  if (ltp === null) return null;
  const sign = leg.action === "BUY" ? 1 : -1;
  const lotSize = LOT_SIZES[leg.underlying] ?? 25;
  return sign * (ltp - leg.entry_price) * leg.lots * lotSize;
}

// Utility to format large numbers
function fmtLargeNum(n: number | null): string {
  if (n === null) return "-";
  if (n >= 10_000_000) return `${(n / 10_000_000).toFixed(2)} Cr`;
  if (n >= 100_000) return `${(n / 100_000).toFixed(2)} L`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)} K`;
  return String(n);
}

function fmtPrice(p: number | null): string {
  if (p === null) return "-";
  return p.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Format slider minute (e.g. 555 -> 09:15)
function minuteToTimeString(m: number): string {
  const hours = Math.floor(m / 60);
  const minutes = m % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

// Format display time as 12-hour AM/PM
function formatDisplayTime(m: number): string {
  let hours = Math.floor(m / 60);
  const minutes = m % 60;
  const ampm = hours >= 12 ? "PM" : "AM";
  hours = hours % 12;
  hours = hours ? hours : 12; // the hour '0' should be '12'
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")} ${ampm}`;
}

function localDateStr(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function computeLiveExpiries(underlying: string): string[] {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const todayStr = localDateStr(today);
  const results: string[] = [];

  if (underlying === "NIFTY") {
    // Next 4 weekly Tuesdays (Tue = getDay() 2)
    const d = new Date(today);
    const dow = d.getDay();
    d.setDate(d.getDate() + (dow <= 2 ? 2 - dow : 9 - dow));
    for (let i = 0; i < 4; i++) {
      results.push(localDateStr(d));
      d.setDate(d.getDate() + 7);
    }
  } else {
    // BANKNIFTY: next 3 last Tuesdays of month
    for (let mo = 0; mo < 5 && results.length < 3; mo++) {
      const raw = today.getMonth() + mo;
      const year = today.getFullYear() + Math.floor(raw / 12);
      const month = raw % 12;
      const last = new Date(year, month + 1, 0);
      while (last.getDay() !== 2) last.setDate(last.getDate() - 1);
      const exp = localDateStr(last);
      if (exp >= todayStr) results.push(exp);
    }
  }
  return results;
}

export default function OptionsChain() {
  const [underlying, setUnderlying] = useState<"NIFTY" | "BANKNIFTY">(
    () => (localStorage.getItem("oc_underlying") as "NIFTY" | "BANKNIFTY") ?? "NIFTY"
  );
  
  // Dropdown options
  const [expiries, setExpiries] = useState<string[]>([]);
  const [tradeDates, setTradeDates] = useState<string[]>([]);
  
  // Selected filter states
  const [selectedExpiry, setSelectedExpiry] = useState<string>("");
  const [selectedDate, setSelectedDate] = useState<string>("");
  const [sliderVal, setSliderVal] = useState<number>(560); // Default to 09:20 AM (560m)
  
  // Live Feed toggle — default true; persisted across page loads
  const [isLive, setIsLive] = useState(
    () => localStorage.getItem("oc_isLive") !== "false"
  );
  const [liveExpiry, setLiveExpiry] = useState<string>(() => computeLiveExpiries(
    (localStorage.getItem("oc_underlying") as "NIFTY" | "BANKNIFTY") ?? "NIFTY"
  )[0] ?? "");
  const wsRef = useRef<WebSocket | null>(null);
  const [wsReconnect, setWsReconnect] = useState(0);
  
  // View options
  const [strikeFilter, setStrikeFilter] = useState<"ATM_5" | "ATM_10" | "ALL">("ATM_10");
  const [searchStrike, setSearchStrike] = useState<string>("");
  const [showGreeks, setShowGreeks] = useState(false);
  const [hideZeroOi, setHideZeroOi] = useState(false);

  // Data states
  const [data, setData] = useState<OptionsChainResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Strategy Builder Workspace State (Opstra)
  const [legs, setLegs] = useState<BuilderLeg[]>([]);
  const [payoff, setPayoff] = useState<PayoffResponse | null>(null);
  const [payoffLoading, setPayoffLoading] = useState(false);
  
  // Strategy Persistence state
  const [strategyName, setStrategyName] = useState("");
  const [savedStrategies, setSavedStrategies] = useState<SavedStrategy[]>([]);
  const [showSavedList, setShowSavedList] = useState(false);

  // Load saved strategies on mount
  const loadSaved = () => {
    listStrategies()
      .then(setSavedStrategies)
      .catch((e) => console.error("Failed to load saved strategies:", e));
  };
  
  useEffect(() => {
    loadSaved();
  }, []);

  // 1. Fetch expiries on mount or underlying change
  useEffect(() => {
    getExpiries(underlying)
      .then((exps) => {
        setExpiries(exps);
        if (exps.length > 0) {
          setSelectedExpiry(exps[0]);
        } else {
          setSelectedExpiry("");
          setTradeDates([]);
          setSelectedDate("");
        }
      })
      .catch((e) => setError(`Failed to load expiries: ${e.message}`));
  }, [underlying]);

  // 2. Fetch trade dates when expiry changes
  useEffect(() => {
    if (!selectedExpiry) return;
    getTradeDates(underlying, selectedExpiry)
      .then((dates) => {
        setTradeDates(dates);
        if (dates.length > 0) {
          setSelectedDate(dates[0]);
        } else {
          setSelectedDate("");
        }
      })
      .catch((e) => setError(`Failed to load trade dates: ${e.message}`));
  }, [underlying, selectedExpiry]);

  // 3. Fetch options chain data when Date/Time changes (in historical mode)
  useEffect(() => {
    if (isLive || !selectedExpiry || !selectedDate || selectedDate === "No dates") return;
    
    setLoading(true);
    setError(null);

    const timeStr = minuteToTimeString(sliderVal);
    const ts = `${selectedDate}T${timeStr}:00`;

    getOptionsChainData(underlying, selectedExpiry, ts)
      .then((res) => {
        setData(res);
        setLoading(false);
      })
      .catch((e) => {
        setError(e.message);
        setLoading(false);
      });
  }, [underlying, selectedExpiry, selectedDate, sliderVal, isLive]);

  // 4. Connect to Live WebSocket stream (when Go Live is toggled)
  useEffect(() => {
    if (!isLive || !liveExpiry) {
      wsRef.current?.close();
      return;
    }

    setLoading(true);
    setError(null);

    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${window.location.host}/api/live/stream`);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ action: "subscribe", underlying, expiry: liveExpiry }));
    };

    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.error) setError(payload.error);
        else { setData(payload); setLoading(false); }
      } catch { /* ignore parse errors */ }
    };

    ws.onerror = () => setError("Live feed connection error — retrying on next change.");
    ws.onclose = () => {
      if (isLive) setTimeout(() => setWsReconnect(n => n + 1), 3000);
    };

    return () => { ws.close(); };
  }, [isLive, underlying, liveExpiry, wsReconnect]);

  const spotPrice = data?.spot_price ?? null;
  
  // Calculate ATM Strike
  const atmStrike = useMemo(() => {
    if (!spotPrice || !data?.chain.length) return null;
    return data.chain.reduce((prev, curr) => {
      return Math.abs(curr.strike - spotPrice) < Math.abs(prev.strike - spotPrice)
        ? curr
        : prev;
    }).strike;
  }, [spotPrice, data]);

  // σ bands for payoff chart
  const daysToExpiry = useMemo(() => {
    const exp = isLive ? liveExpiry : selectedExpiry;
    if (!exp) return 30;
    return Math.max(1, (new Date(exp).getTime() - Date.now()) / (1000 * 60 * 60 * 24));
  }, [isLive, liveExpiry, selectedExpiry]);

  const atmIv = useMemo(() => {
    if (!data?.chain || !atmStrike) return null;
    const row = data.chain.find(r => r.strike === atmStrike);
    return row?.ce?.iv ?? row?.pe?.iv ?? null;
  }, [data, atmStrike]);

  const sigma1 = useMemo(() => {
    if (!spotPrice) return null;
    const iv = atmIv ?? 15;
    return spotPrice * (iv / 100) * Math.sqrt(daysToExpiry / 365);
  }, [spotPrice, atmIv, daysToExpiry]);

  const filteredCurve = useMemo(() => {
    if (!payoff?.curve || !spotPrice) return payoff?.curve ?? [];
    const spread = (sigma1 ?? spotPrice * 0.07) * 3.2;
    return payoff.curve.filter(p => p.spot >= spotPrice - spread && p.spot <= spotPrice + spread);
  }, [payoff, spotPrice, sigma1]);

  // IV simulator
  const [ivShift, setIvShift] = useState(0); // percentage points shift, e.g. +5 = IV increased by 5%
  const ivImpact = payoff ? Math.round(payoff.net_greeks.vega * ivShift) : 0;

  // today_pnl at current spot (for in-chart annotation)
  const spotPnl = useMemo(() => {
    if (!filteredCurve.length || !spotPrice) return null;
    const pt = filteredCurve.reduce((prev, curr) =>
      Math.abs(curr.spot - spotPrice) < Math.abs(prev.spot - spotPrice) ? curr : prev
    );
    return (pt as { today_pnl?: number }).today_pnl ?? null;
  }, [filteredCurve, spotPrice]);

  // Shift today_pnl by IV simulator impact (so the blue curve moves with IV slider)
  const simulatedCurve = useMemo(() => {
    if (ivShift === 0) return filteredCurve;
    return filteredCurve.map(pt => ({ ...pt, today_pnl: ((pt as { today_pnl?: number }).today_pnl ?? 0) + ivImpact }));
  }, [filteredCurve, ivShift, ivImpact]);

  // Payoff chart data: profit_fill/loss_fill follow exact curve shape for Area components
  const payoffChartData = useMemo(() =>
    simulatedCurve.map(pt => ({
      ...pt,
      profit_fill: Math.max(0, pt.expiry_pnl),
      loss_fill: Math.min(0, pt.expiry_pnl),
    })), [simulatedCurve]);

  // Filter chain rows based on selections
  const filteredChain = useMemo(() => {
    if (!data) return [];
    let rows = data.chain;

    // Filter by search term
    if (searchStrike.trim()) {
      const s = parseInt(searchStrike);
      if (!isNaN(s)) {
        rows = rows.filter((r) => String(r.strike).includes(searchStrike));
      }
    }

    // Filter by ATM (show 5 or 10 strikes above/below spot price)
    if (strikeFilter !== "ALL" && spotPrice && !searchStrike) {
      const limit = strikeFilter === "ATM_5" ? 5 : 10;
      const idx = rows.findIndex((r) => r.strike === atmStrike);
      if (idx !== -1) {
        const startIdx = Math.max(0, idx - limit);
        const endIdx = Math.min(rows.length - 1, idx + limit);
        rows = rows.slice(startIdx, endIdx + 1);
      }
    }

    // Hide zero OI strikes
    if (hideZeroOi) {
      rows = rows.filter((r) => {
        const ceOi = r.ce?.oi ?? 0;
        const peOi = r.pe?.oi ?? 0;
        return ceOi > 0 || peOi > 0;
      });
    }

    return rows;
  }, [data, strikeFilter, spotPrice, atmStrike, searchStrike, hideZeroOi]);

  // Strategy Payoff calculation hook
  useEffect(() => {
    const activeExpiry = isLive ? liveExpiry : selectedExpiry;
    if (legs.length === 0 || !spotPrice || !activeExpiry) {
      setPayoff(null);
      return;
    }

    setPayoffLoading(true);
    const now = new Date();
    const localToday = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,"0")}-${String(now.getDate()).padStart(2,"0")}`;
    const currentDateVal = isLive ? localToday : selectedDate;
    const expiryVal = activeExpiry;

    const req = {
      underlying,
      spot: spotPrice,
      expiry: expiryVal,
      current_date: currentDateVal,
      r: 0.065,
      legs: legs.map(({ action, opt_type, strike, lots, entry_price, underlying: u }) => ({
        action,
        opt_type,
        strike,
        lots,
        entry_price,
        underlying: u,
      })),
    };

    getPayoffCurve(req)
      .then((res) => {
        setPayoff(res);
        setPayoffLoading(false);
      })
      .catch((e) => {
        console.error("Payoff builder pricing error:", e);
        setPayoffLoading(false);
      });
  }, [legs, selectedExpiry, liveExpiry, selectedDate, underlying, isLive]);

  // Leg Builder triggers from Options Chain
  const addLeg = (strike: number, opt_type: "CE" | "PE", action: "BUY" | "SELL", entryPrice: number) => {
    const id = `leg-${Date.now()}-${strike}-${opt_type}-${action}`;
    const newLeg: BuilderLeg = {
      id,
      strike,
      opt_type,
      action,
      entry_price: entryPrice,
      lots: 1,
      underlying,
    };
    setLegs((prev) => [...prev, newLeg]);
  };

  const handleUpdateLeg = (id: string, updates: Partial<BuilderLeg>) => {
    setLegs((prev) =>
      prev.map((leg) => (leg.id === id ? { ...leg, ...updates } : leg))
    );
  };

  const handleRemoveLeg = (id: string) => {
    setLegs((prev) => prev.filter((leg) => leg.id !== id));
  };

  const handleClearLegs = () => {
    setLegs([]);
    setPayoff(null);
  };

  // Save Strategy persistence handlers
  const handleSaveStrategy = () => {
    if (!strategyName.trim()) {
      alert("Please enter a name for the strategy.");
      return;
    }
    if (legs.length === 0) {
      alert("Please add at least one leg first.");
      return;
    }

    saveStrategy(
      strategyName,
      underlying,
      selectedExpiry,
      legs.map(({ action, opt_type, strike, lots, entry_price, underlying: u }) => ({
        action,
        opt_type,
        strike,
        lots,
        entry_price,
        underlying: u
      }))
    )
      .then(() => {
        setStrategyName("");
        loadSaved();
        alert("Strategy saved successfully to database!");
      })
      .catch((e) => alert(`Failed to save strategy: ${e.message}`));
  };

  const handleLoadStrategy = (saved: SavedStrategy) => {
    setUnderlying(saved.underlying as "NIFTY" | "BANKNIFTY");
    setSelectedExpiry(saved.expiry);
    setLegs(
      saved.legs.map((l, i) => ({
        id: `saved-${Date.now()}-${i}`,
        ...l
      }))
    );
    setShowSavedList(false);
  };

  const handleDeleteSaved = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (confirm("Are you sure you want to delete this saved strategy?")) {
      deleteStrategy(id)
        .then(() => loadSaved())
        .catch((err) => console.error("Failed to delete strategy:", err));
    }
  };

  // Export CSV function
  const handleExportCSV = () => {
    if (!data || !data.chain.length) return;

    const headers = ["CE_OI", "CE_Volume", "CE_LTP", "Strike", "PE_LTP", "PE_Volume", "PE_OI"];
    const rows = data.chain.map((r) => [
      r.ce?.oi ?? 0,
      r.ce?.volume ?? 0,
      r.ce?.close ?? 0,
      r.strike,
      r.pe?.close ?? 0,
      r.pe?.volume ?? 0,
      r.pe?.oi ?? 0,
    ]);

    const csvContent = "data:text/csv;charset=utf-8," + [headers.join(","), ...rows.map((e) => e.join(","))].join("\n");
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute(
      "download",
      `options_chain_${underlying}_${selectedExpiry}_${isLive ? "LIVE" : selectedDate}.csv`
    );
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const chartData = useMemo(() => {
    return filteredChain.map((r) => ({
      strike: r.strike,
      "CE OI": r.ce?.oi ?? 0,
      "PE OI": r.pe?.oi ?? 0,
    }));
  }, [filteredChain]);

  const oiAnalysis = useMemo(() => {
    if (!data?.summary || !data?.chain?.length || !spotPrice) return null;
    const { pcr, max_pain, total_ce_oi, total_pe_oi } = data.summary;

    // PCR signal
    let pcrSignal: "BULLISH" | "BEARISH" | "NEUTRAL";
    let pcrNote: string;
    if (pcr > 1.3)       { pcrSignal = "BULLISH"; pcrNote = `PCR ${pcr.toFixed(2)} — heavy put writing, bulls in control`; }
    else if (pcr > 1.0)  { pcrSignal = "NEUTRAL";  pcrNote = `PCR ${pcr.toFixed(2)} — mild put dominance, slight bullish bias`; }
    else if (pcr > 0.8)  { pcrSignal = "NEUTRAL";  pcrNote = `PCR ${pcr.toFixed(2)} — balanced OI, range-bound likely`; }
    else                 { pcrSignal = "BEARISH"; pcrNote = `PCR ${pcr.toFixed(2)} — call writing dominates, bears in control`; }

    // Max Pain vs Spot
    const painPct = ((spotPrice - max_pain) / max_pain) * 100;
    let painSignal: "BULLISH" | "BEARISH" | "NEUTRAL";
    let painNote: string;
    if (painPct > 1.5)       { painSignal = "BEARISH"; painNote = `Spot ${painPct.toFixed(1)}% above Max Pain ${max_pain.toLocaleString("en-IN")} — gravity pull DOWN`; }
    else if (painPct < -1.5) { painSignal = "BULLISH"; painNote = `Spot ${Math.abs(painPct).toFixed(1)}% below Max Pain ${max_pain.toLocaleString("en-IN")} — gravity pull UP`; }
    else                     { painSignal = "NEUTRAL";  painNote = `Spot near Max Pain ${max_pain.toLocaleString("en-IN")} — market at equilibrium`; }

    // OI skew
    const skewPct = total_ce_oi + total_pe_oi > 0 ? ((total_pe_oi - total_ce_oi) / (total_pe_oi + total_ce_oi)) * 100 : 0;
    let skewNote: string;
    if (skewPct > 10)       skewNote = `PE OI ${skewPct.toFixed(0)}% heavier — strong put base, market supported`;
    else if (skewPct < -10) skewNote = `CE OI ${Math.abs(skewPct).toFixed(0)}% heavier — call wall overhead, market capped`;
    else                    skewNote = `CE/PE OI balanced (skew ${skewPct.toFixed(0)}%) — no directional bias from writing`;

    // Key levels from OI
    let maxCeOiStrike = 0, maxCeOi = 0, maxPeOiStrike = 0, maxPeOi = 0;
    for (const row of data.chain) {
      const ceOi = row.ce?.oi ?? 0;
      const peOi = row.pe?.oi ?? 0;
      if (ceOi > maxCeOi) { maxCeOi = ceOi; maxCeOiStrike = row.strike; }
      if (peOi > maxPeOi) { maxPeOi = peOi; maxPeOiStrike = row.strike; }
    }

    // Spot vs levels
    const aboveResistance = spotPrice > maxCeOiStrike;
    const belowSupport = spotPrice < maxPeOiStrike;

    // Overall verdict
    const bullPts = (pcrSignal === "BULLISH" ? 1 : 0) + (painSignal === "BULLISH" ? 1 : 0) + (skewPct > 10 ? 1 : 0);
    const bearPts = (pcrSignal === "BEARISH" ? 1 : 0) + (painSignal === "BEARISH" ? 1 : 0) + (skewPct < -10 ? 1 : 0);
    const verdict: "BULLISH" | "BEARISH" | "NEUTRAL" = bullPts > bearPts ? "BULLISH" : bearPts > bullPts ? "BEARISH" : "NEUTRAL";

    return { verdict, pcrSignal, pcrNote, painSignal, painNote, skewNote, maxCeOiStrike, maxCeOi, maxPeOiStrike, maxPeOi, aboveResistance, belowSupport };
  }, [data, spotPrice]);

  const inp =
    "bg-gray-950 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500 w-full sm:w-auto min-w-[140px]";

  const maxProfit = payoff?.max_profit !== undefined ? payoff.max_profit : null;
  const maxLoss = payoff?.max_loss !== undefined ? payoff.max_loss : null;

  return (
    <div className="flex flex-col h-full gap-6">
      {error && (
        <div className="bg-red-900/20 border border-red-500/40 text-red-300 px-4 py-3 rounded-xl text-xs flex justify-between items-center">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-300 font-bold ml-2">✕</button>
        </div>
      )}
      
      {/* Top Filter Panel */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-4 shadow-lg">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          
          {/* Left Controls */}
          <div className="flex flex-wrap items-center gap-4">
            
            {/* Toggle Underlying */}
            <div className="flex bg-gray-950 rounded-lg p-1 border border-gray-700">
              {(["NIFTY", "BANKNIFTY"] as const).map((u) => (
                <button
                  key={u}
                  type="button"
                  onClick={() => {
                    setUnderlying(u);
                    localStorage.setItem("oc_underlying", u);
                    setLiveExpiry(computeLiveExpiries(u)[0] ?? "");
                    setLegs([]);
                  }}
                  className={`px-3 py-1.5 rounded-md text-xs font-bold transition-all ${
                    underlying === u
                      ? "bg-blue-600 text-white shadow-md shadow-blue-900/10"
                      : "text-gray-400 hover:text-gray-250"
                  }`}
                >
                  {u}
                </button>
              ))}
            </div>

            {/* Expiry Select */}
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-gray-500">Expiry</span>
              {isLive ? (
                <select
                  value={liveExpiry}
                  onChange={(e) => { setLiveExpiry(e.target.value); setLegs([]); }}
                  className={`${inp} text-blue-300 font-semibold`}
                >
                  {computeLiveExpiries(underlying).map((exp) => (
                    <option key={exp} value={exp}>{exp}</option>
                  ))}
                </select>
              ) : (
                <select
                  value={selectedExpiry}
                  onChange={(e) => { setSelectedExpiry(e.target.value); setLegs([]); }}
                  className={inp}
                >
                  {expiries.map((exp) => (
                    <option key={exp} value={exp}>{exp}</option>
                  ))}
                </select>
              )}
            </div>

            {/* Date Select (disabled in Live mode) */}
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-gray-500">Date</span>
              <select
                value={selectedDate}
                onChange={(e) => setSelectedDate(e.target.value)}
                className={inp}
                disabled={tradeDates.length === 0 || isLive}
              >
                {isLive ? (
                  <option>LIVE SESSION</option>
                ) : tradeDates.length === 0 ? (
                  <option>No dates</option>
                ) : (
                  tradeDates.map((d) => (
                    <option key={d} value={d}>{d}</option>
                  ))
                )}
              </select>
            </div>

            {/* Live Today Toggle */}
            <button
              onClick={() => {
                const next = !isLive;
                setIsLive(next);
                localStorage.setItem("oc_isLive", String(next));
                setLegs([]);
              }}
              title="Stream today's live market session (real broker feed during market hours)"
              className={`px-4 py-1.5 rounded-lg text-xs font-extrabold flex items-center gap-2 border transition-all ${
                isLive
                  ? "bg-green-600/20 border-green-500/40 text-green-300 shadow-md shadow-green-950/40"
                  : "bg-red-600/10 border-red-500/20 text-red-400 hover:bg-red-600/20"
              }`}
            >
              <span className={`w-1.5 h-1.5 rounded-full inline-block ${isLive ? "bg-green-400 animate-ping" : "bg-red-500"}`} />
              {isLive ? "LIVE ACTIVE" : "LIVE TODAY"}
            </button>

            {/* Live source / status badge */}
            {isLive && (() => {
              const stale = data?.stale === true;
              const src = (data?.source ?? "upstox").toUpperCase();
              return (
                <div className={`px-2.5 py-1 rounded-lg text-[10px] font-bold flex items-center gap-1.5 border ${
                  stale ? "bg-amber-600/15 border-amber-500/40 text-amber-300"
                        : "bg-emerald-600/15 border-emerald-500/40 text-emerald-300"
                }`}>
                  <span className={`w-1.5 h-1.5 rounded-full inline-block ${stale ? "bg-amber-400" : "bg-emerald-400 animate-pulse"}`} />
                  {stale ? "LAST FETCHED" : `LIVE · ${src}`}
                  {data?.timestamp && (
                    <span className="text-gray-400 font-mono font-normal ml-1">
                      {new Date(data.timestamp).toLocaleTimeString("en-IN", { hour12: false })}
                    </span>
                  )}
                </div>
              );
            })()}
          </div>

          {/* Right Controls */}
          <div className="flex flex-wrap items-center gap-3 self-end lg:self-auto">
            
            {/* Saved Strategies Workspace Toggle */}
            <button
              onClick={() => setShowSavedList(!showSavedList)}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-gray-800 border border-gray-700 text-gray-300 hover:bg-gray-750 transition-all"
            >
              💼 Saved Workspaces ({savedStrategies.length})
            </button>

            <div className="flex bg-gray-950 rounded-lg p-1 border border-gray-700">
              {(["ATM_5", "ATM_10", "ALL"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setStrikeFilter(mode)}
                  className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                    strikeFilter === mode
                      ? "bg-gray-800 text-white"
                      : "text-gray-500 hover:text-gray-300"
                  }`}
                >
                  {mode === "ATM_5" ? "ATM ± 5" : mode === "ATM_10" ? "ATM ± 10" : "All"}
                </button>
              ))}
            </div>

            <label className="flex items-center gap-1.5 cursor-pointer text-xs text-gray-400 select-none">
              <input
                type="checkbox"
                checked={hideZeroOi}
                onChange={(e) => setHideZeroOi(e.target.checked)}
                className="rounded border-gray-700 bg-gray-950 text-blue-600 focus:ring-0 focus:ring-offset-0 h-3.5 w-3.5"
              />
              <span>Hide Zero OI</span>
            </label>

            <button
              type="button"
              onClick={() => setShowGreeks((v) => !v)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${
                showGreeks
                  ? "bg-purple-600/20 border-purple-500/40 text-purple-300"
                  : "bg-gray-950 border-gray-700 text-gray-400 hover:text-gray-200"
              }`}
            >
              Greeks
            </button>

            <input
              type="text"
              placeholder="Search Strike..."
              value={searchStrike}
              onChange={(e) => setSearchStrike(e.target.value)}
              className={`${inp} max-w-[110px]`}
            />

            <button
              onClick={handleExportCSV}
              disabled={!data || data.chain.length === 0}
              className="px-3 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-xs font-medium text-gray-200 border border-gray-700 transition-colors disabled:opacity-50"
            >
              Export
            </button>
          </div>
        </div>

        {/* Time Slider Panel (hidden in Live mode) */}
        {!isLive && (
          <div className="bg-gray-950 border border-gray-800/80 rounded-xl p-4 flex flex-col md:flex-row md:items-center gap-4">
            <div className="flex items-center gap-3">
              <span className="text-xs text-gray-500 uppercase tracking-widest font-semibold">Time:</span>
              <span className="text-sm font-bold text-blue-400 bg-blue-500/10 px-2.5 py-1 rounded-md border border-blue-500/20 w-[100px] text-center">
                {formatDisplayTime(sliderVal)}
              </span>
            </div>

            <div className="flex-1 flex items-center gap-3">
              <button
                onClick={() => setSliderVal((v) => Math.max(555, v - 1))}
                disabled={sliderVal <= 555}
                className="w-7 h-7 flex items-center justify-center bg-gray-900 border border-gray-800 hover:border-gray-700 rounded-lg text-xs text-gray-400 disabled:opacity-30"
              >
                ◀
              </button>
              <input
                type="range"
                min={555}
                max={930}
                value={sliderVal}
                onChange={(e) => setSliderVal(Number(e.target.value))}
                className="flex-1 accent-blue-500 h-1 bg-gray-800 rounded-lg cursor-pointer"
              />
              <button
                onClick={() => setSliderVal((v) => Math.min(930, v + 1))}
                disabled={sliderVal >= 930}
                className="w-7 h-7 flex items-center justify-center bg-gray-900 border border-gray-800 hover:border-gray-700 rounded-lg text-xs text-gray-400 disabled:opacity-30"
              >
                ▶
              </button>
            </div>

            <div className="flex gap-2">
              <button onClick={() => setSliderVal(555)} className="px-2 py-1 bg-gray-900 border border-gray-800 rounded text-[10px] text-gray-400 hover:text-white">Open</button>
              <button onClick={() => setSliderVal(720)} className="px-2 py-1 bg-gray-900 border border-gray-800 rounded text-[10px] text-gray-400 hover:text-white">12 PM</button>
              <button onClick={() => setSliderVal(930)} className="px-2 py-1 bg-gray-900 border border-gray-800 rounded text-[10px] text-gray-400 hover:text-white">Close</button>
            </div>
          </div>
        )}
      </div>

      {/* Saved Strategy list overlay panel */}
      {showSavedList && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 shadow-2xl relative">
          <button onClick={() => setShowSavedList(false)} className="absolute top-3 right-4 text-gray-450 hover:text-white text-xs font-semibold">✕ Close</button>
          <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-4">Saved Strategies Workspace</h3>
          {savedStrategies.length === 0 ? (
            <p className="text-xs text-gray-500">No saved strategy templates found in database. Build a strategy and save it below!</p>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {savedStrategies.map((saved) => (
                <div
                  key={saved.id}
                  onClick={() => handleLoadStrategy(saved)}
                  className="bg-gray-950 hover:bg-gray-850 border border-gray-800 rounded-xl p-4 cursor-pointer transition-all flex flex-col justify-between"
                >
                  <div>
                    <h4 className="text-sm font-bold text-blue-400">{saved.name}</h4>
                    <div className="text-[10px] text-gray-500 font-mono mt-1">
                      {saved.underlying} · Expiry: {saved.expiry}
                    </div>
                    <div className="mt-2.5 flex flex-wrap gap-1">
                      {saved.legs.map((l, idx) => (
                        <span key={idx} className={`text-[9px] font-mono px-1.5 py-0.5 rounded border ${
                          l.action === "BUY" ? "bg-green-950 text-green-400 border-green-900/35" : "bg-red-950 text-red-400 border-red-900/35"
                        }`}>
                          {l.action === "BUY" ? "Long" : "Short"} {l.strike} {l.opt_type}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="flex items-center justify-between border-t border-gray-800/80 pt-3 mt-3">
                    <span className="text-[9px] text-gray-600 font-mono">{saved.created_at.slice(0, 16).replace("T", " ")}</span>
                    <button
                      onClick={(e) => handleDeleteSaved(saved.id, e)}
                      className="text-[10px] text-red-500 hover:text-red-400 font-semibold"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* PCR / Max Pain summary cards */}
      {data?.summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: "Put-Call Ratio (OI)", val: data.summary.pcr.toFixed(3), color: data.summary.pcr > 1.2 ? "text-green-400" : data.summary.pcr < 0.8 ? "text-red-400" : "text-yellow-400" },
            { label: "Max Pain Strike", val: data.summary.max_pain.toLocaleString("en-IN"), color: "text-blue-450" },
            { label: "Total CE Open Interest", val: fmtLargeNum(data.summary.total_ce_oi), color: "text-red-400" },
            { label: "Total PE Open Interest", val: fmtLargeNum(data.summary.total_pe_oi), color: "text-green-400" },
          ].map((c) => (
            <div key={c.label} className="bg-gray-900 rounded-xl p-4 border border-gray-800 shadow">
              <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1 font-semibold">{c.label}</div>
              <div className={`text-base font-black ${c.color}`}>{c.val}</div>
            </div>
          ))}
        </div>
      )}

      {/* OI Intelligence Panel */}
      {oiAnalysis && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 shadow-lg">
          <div className="flex items-center gap-3 mb-3">
            <span className="text-xs font-bold text-gray-400 uppercase tracking-widest">OI Intelligence</span>
            <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-black uppercase tracking-wider border ${
              oiAnalysis.verdict === "BULLISH" ? "bg-green-900/50 text-green-400 border-green-700/50" :
              oiAnalysis.verdict === "BEARISH" ? "bg-red-900/50 text-red-400 border-red-700/50" :
              "bg-yellow-900/30 text-yellow-400 border-yellow-700/40"
            }`}>
              {oiAnalysis.verdict === "BULLISH" ? "↑ BULLISH" : oiAnalysis.verdict === "BEARISH" ? "↓ BEARISH" : "→ NEUTRAL"}
            </span>
            <span className="text-[10px] text-gray-600 italic">Based on live OI positioning</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-[11px]">
            <div className={`flex items-start gap-2 p-2.5 rounded-lg bg-gray-950/60 border ${oiAnalysis.pcrSignal === "BULLISH" ? "border-green-800/40" : oiAnalysis.pcrSignal === "BEARISH" ? "border-red-800/40" : "border-gray-800/60"}`}>
              <span>📊</span><span className="text-gray-300 leading-relaxed">{oiAnalysis.pcrNote}</span>
            </div>
            <div className={`flex items-start gap-2 p-2.5 rounded-lg bg-gray-950/60 border ${oiAnalysis.painSignal === "BULLISH" ? "border-green-800/40" : oiAnalysis.painSignal === "BEARISH" ? "border-red-800/40" : "border-gray-800/60"}`}>
              <span>🎯</span><span className="text-gray-300 leading-relaxed">{oiAnalysis.painNote}</span>
            </div>
            <div className="flex items-start gap-2 p-2.5 rounded-lg bg-gray-950/60 border border-gray-800/60">
              <span>⚖️</span><span className="text-gray-300 leading-relaxed">{oiAnalysis.skewNote}</span>
            </div>
            <div className="flex items-start gap-2 p-2.5 rounded-lg bg-gray-950/60 border border-gray-800/60">
              <span>📍</span>
              <span className="text-gray-300 leading-relaxed">
                Resistance: <span className="font-bold text-red-400">{oiAnalysis.maxCeOiStrike.toLocaleString("en-IN")}</span>
                {" "}({fmtLargeNum(oiAnalysis.maxCeOi)} CE OI)
                {"  ·  "}
                Support: <span className="font-bold text-green-400">{oiAnalysis.maxPeOiStrike.toLocaleString("en-IN")}</span>
                {" "}({fmtLargeNum(oiAnalysis.maxPeOi)} PE OI)
                {oiAnalysis.aboveResistance && <span className="text-orange-400 font-bold"> ⚠ Spot above resistance!</span>}
                {oiAnalysis.belowSupport && <span className="text-orange-400 font-bold"> ⚠ Spot below support!</span>}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Main Options Chain Table Grid */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6 flex-shrink-0 min-h-0">
        
        {/* Double sided Option Chain grid (2/3 width) */}
        <div className="xl:col-span-2 bg-gray-900 border border-gray-800 rounded-xl flex flex-col overflow-hidden min-h-[400px] shadow-lg">
          <div className="px-5 py-3.5 border-b border-gray-800 bg-gray-900/60 flex items-center justify-between">
            <span className="text-xs font-bold text-gray-400 uppercase tracking-widest">
              Double-Sided Option Chain & Opstra-Builder
            </span>
            {spotPrice && (
              <span className="text-sm font-black text-green-400 font-mono">
                SPOT: {fmtPrice(spotPrice)}
              </span>
            )}
          </div>

          <div className="flex-1 overflow-y-auto relative min-h-0">
            {loading && !data ? (
              <div className="absolute inset-0 bg-gray-900/60 backdrop-blur-sm flex items-center justify-center z-10">
                <span className="text-sm text-gray-400 font-medium animate-pulse">
                  Loading option chain quotes...
                </span>
              </div>
            ) : null}

            {!data ? (
              <div className="h-full flex items-center justify-center text-gray-500">
                Connecting to data feed...
              </div>
            ) : (
              <table className="w-full text-left border-collapse table-fixed">
                <thead className="bg-gray-950 text-[10px] text-gray-500 uppercase tracking-wider sticky top-0 z-10 border-b border-gray-800">
                  <tr>
                    {showGreeks && (
                      <>
                        <th className="py-2.5 px-2 text-right border-r border-gray-800 text-purple-400">IV</th>
                        <th className="py-2.5 px-2 text-right border-r border-gray-800 text-orange-400 font-medium">Theta</th>
                        <th className="py-2.5 px-2 text-right border-r border-gray-800 text-blue-400 font-medium">Delta</th>
                      </>
                    )}
                    <th className="py-2.5 px-3 border-r border-gray-800 text-right">CE OI</th>
                    <th className="py-2.5 px-3 border-r border-gray-800 text-right">Volume</th>
                    <th className="py-2.5 px-2 text-center w-[74px] border-r border-gray-800">Trade CE</th>
                    <th className="py-2.5 px-3 border-r border-gray-800 text-right">LTP (CE)</th>
                    
                    <th className="py-2.5 px-3 border-r border-gray-800 text-center bg-gray-950 w-24">Strike</th>
                    
                    <th className="py-2.5 px-3 border-r border-gray-800 text-left">LTP (PE)</th>
                    <th className="py-2.5 px-2 text-center w-[74px] border-r border-gray-800">Trade PE</th>
                    <th className="py-2.5 px-3 border-r border-gray-800 text-left">Volume</th>
                    <th className="py-2.5 px-3 border-r border-gray-800 text-left">PE OI</th>
                    {showGreeks && (
                      <>
                        <th className="py-2.5 px-2 text-left border-r border-gray-800 text-blue-400 font-medium">Delta</th>
                        <th className="py-2.5 px-2 text-left border-r border-gray-800 text-orange-400 font-medium">Theta</th>
                        <th className="py-2.5 px-2 text-purple-400">IV</th>
                      </>
                    )}
                  </tr>
                </thead>

                <tbody className="text-xs divide-y divide-gray-800/50">
                  {filteredChain.map((row, idx) => {
                    const isCeItm = spotPrice !== null && row.strike < spotPrice;
                    const isPeItm = spotPrice !== null && row.strike > spotPrice;
                    const isAtm = row.strike === atmStrike;

                    const nextRow = filteredChain[idx + 1];
                    const renderSpotLine =
                      spotPrice !== null &&
                      nextRow &&
                      row.strike < spotPrice &&
                      nextRow.strike > spotPrice;

                    return (
                      <React.Fragment key={row.strike}>
                        <tr className={`hover:bg-gray-850/40 transition-colors ${isAtm ? "bg-blue-500/5 font-semibold border-y border-blue-500/25" : ""}`}>
                          {/* Call Greeks */}
                          {showGreeks && (
                            <>
                              <td className={`py-2 px-2 text-right border-r border-gray-800 text-purple-400 font-mono text-[11px] ${isCeItm ? "bg-amber-500/[0.03]" : ""}`}>
                                {row.ce?.iv != null ? `${row.ce.iv.toFixed(1)}%` : "-"}
                              </td>
                              <td className={`py-2 px-2 text-right border-r border-gray-800 text-orange-400 font-mono text-[11px] ${isCeItm ? "bg-amber-500/[0.03]" : ""}`}>
                                {row.ce?.theta != null ? row.ce.theta.toFixed(2) : "-"}
                              </td>
                              <td className={`py-2 px-2 text-right border-r border-gray-800 text-blue-400 font-mono text-[11px] ${isCeItm ? "bg-amber-500/[0.03]" : ""}`}>
                                {row.ce?.delta != null ? row.ce.delta.toFixed(2) : "-"}
                              </td>
                            </>
                          )}

                          {/* Call Columns */}
                          <td className={`py-2 px-3 text-right border-r border-gray-800 text-gray-400 font-mono ${isCeItm ? "bg-amber-500/[0.03] text-amber-500/80" : ""}`}>
                            {fmtLargeNum(row.ce?.oi ?? null)}
                          </td>
                          <td className={`py-2 px-3 text-right border-r border-gray-800 text-gray-500 font-mono ${isCeItm ? "bg-amber-500/[0.03]" : ""}`}>
                            {row.ce?.volume?.toLocaleString() ?? "-"}
                          </td>
                          
                          {/* Buy/Sell Call builder buttons */}
                          <td className={`py-2 px-2 text-center border-r border-gray-800 whitespace-nowrap ${isCeItm ? "bg-amber-500/[0.03]" : ""}`}>
                            <button
                              onClick={() => addLeg(row.strike, "CE", "BUY", row.ce?.close ?? 100)}
                              className="px-1.5 py-0.5 rounded text-[9px] font-black border border-green-800 bg-green-950/20 text-green-400 hover:bg-green-600 hover:text-white transition-colors mr-1 shadow-sm"
                            >
                              B
                            </button>
                            <button
                              onClick={() => addLeg(row.strike, "CE", "SELL", row.ce?.close ?? 100)}
                              className="px-1.5 py-0.5 rounded text-[9px] font-black border border-red-800 bg-red-950/20 text-red-400 hover:bg-red-600 hover:text-white transition-colors shadow-sm"
                            >
                              S
                            </button>
                          </td>

                          <td className={`py-2 px-3 text-right border-r border-gray-800 text-green-400 font-bold font-mono ${isCeItm ? "bg-amber-500/[0.04]" : ""}`}>
                            {fmtPrice(row.ce?.close ?? null)}
                          </td>

                          {/* Strike */}
                          <td className={`py-2 px-3 text-center border-r border-gray-800 bg-gray-950 font-black font-mono text-gray-300 w-24 ${isAtm ? "text-blue-450 border-x border-blue-500/40" : ""}`}>
                            {row.strike}
                          </td>

                          {/* Put Columns */}
                          <td className={`py-2 px-3 text-left border-r border-gray-800 text-green-400 font-bold font-mono ${isPeItm ? "bg-amber-500/[0.04]" : ""}`}>
                            {fmtPrice(row.pe?.close ?? null)}
                          </td>
                          
                          {/* Buy/Sell Put builder buttons */}
                          <td className={`py-2 px-2 text-center border-r border-gray-800 whitespace-nowrap ${isPeItm ? "bg-amber-500/[0.03]" : ""}`}>
                            <button
                              onClick={() => addLeg(row.strike, "PE", "BUY", row.pe?.close ?? 100)}
                              className="px-1.5 py-0.5 rounded text-[9px] font-black border border-green-800 bg-green-950/20 text-green-400 hover:bg-green-600 hover:text-white transition-colors mr-1 shadow-sm"
                            >
                              B
                            </button>
                            <button
                              onClick={() => addLeg(row.strike, "PE", "SELL", row.pe?.close ?? 100)}
                              className="px-1.5 py-0.5 rounded text-[9px] font-black border border-red-800 bg-red-950/20 text-red-400 hover:bg-red-600 hover:text-white transition-colors shadow-sm"
                            >
                              S
                            </button>
                          </td>

                          <td className={`py-2 px-3 text-left border-r border-gray-800 text-gray-500 font-mono ${isPeItm ? "bg-amber-500/[0.03]" : ""}`}>
                            {row.pe?.volume?.toLocaleString() ?? "-"}
                          </td>
                          <td className={`py-2 px-3 text-left border-r border-gray-800 text-gray-400 font-mono ${isPeItm ? "bg-amber-500/[0.03] text-amber-500/80" : ""}`}>
                            {fmtLargeNum(row.pe?.oi ?? null)}
                          </td>

                          {/* Put Greeks */}
                          {showGreeks && (
                            <>
                              <td className={`py-2 px-2 text-left border-r border-gray-800 text-blue-400 font-mono text-[11px] ${isPeItm ? "bg-amber-500/[0.03]" : ""}`}>
                                {row.pe?.delta != null ? row.pe.delta.toFixed(2) : "-"}
                              </td>
                              <td className={`py-2 px-2 text-left border-r border-gray-800 text-orange-400 font-mono text-[11px] ${isPeItm ? "bg-amber-500/[0.03]" : ""}`}>
                                {row.pe?.theta != null ? row.pe.theta.toFixed(2) : "-"}
                              </td>
                              <td className={`py-2 px-2 text-left text-purple-400 font-mono text-[11px] ${isPeItm ? "bg-amber-500/[0.03]" : ""}`}>
                                {row.pe?.iv != null ? `${row.pe.iv.toFixed(1)}%` : "-"}
                              </td>
                            </>
                          )}
                        </tr>

                        {renderSpotLine && (
                          <tr className="bg-green-500/10 border-y border-green-500/20">
                            <td colSpan={showGreeks ? 7 : 4} className="py-1 px-3 border-r border-gray-800" />
                            <td className="py-1 text-center bg-green-500 text-gray-950 font-extrabold text-[10px] tracking-wider uppercase rounded-sm shadow-md">
                              Spot: {fmtPrice(spotPrice)}
                            </td>
                            <td colSpan={showGreeks ? 7 : 4} className="py-1 px-3" />
                          </tr>
                        )}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* OI Chart Panel (1/3 width) */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 flex flex-col gap-5 min-h-[400px] shadow-lg">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest">
            OI Strike Distribution
          </h3>

          <div className="flex-1 min-h-0">
            {loading ? (
              <div className="h-full flex items-center justify-center text-gray-500">Loading chart...</div>
            ) : chartData.length === 0 ? (
              <div className="h-full flex items-center justify-center text-gray-500">No chart data</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                  <XAxis dataKey="strike" stroke="#9ca3af" fontSize={10} tickLine={false} angle={-45} textAnchor="end" />
                  <YAxis stroke="#9ca3af" fontSize={10} tickLine={false} tickFormatter={(v) => fmtLargeNum(v)} />
                  <Tooltip
                    contentStyle={{ backgroundColor: "#030712", borderColor: "#374151", borderRadius: "8px", fontSize: "12px", color: "#f3f4f6" }}
                    formatter={(v: number) => [v.toLocaleString(), ""]}
                  />
                  <Legend verticalAlign="top" height={36} wrapperStyle={{ fontSize: "11px" }} />
                  <Bar dataKey="CE OI" fill="#ef4444" name="Call OI" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="PE OI" fill="#10b981" name="Put OI" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>

          <div className="bg-gray-950 border border-gray-850 rounded-lg p-3 text-[11px] text-gray-400 space-y-2 leading-relaxed">
            <h4 className="font-semibold text-gray-300">💡 Opstra Workspace Guide:</h4>
            <p>
              Click **B** (Buy) or **S** (Sell) buttons next to the CE/PE prices in the table to instantly add option legs into the Strategy Workspace below.
            </p>
          </div>
        </div>
      </div>

      {/* Embedded Strategy Workspace & Payoff Diagram (Opstra Style) */}
      {legs.length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 shadow-2xl space-y-6">
          <div className="flex items-center justify-between border-b border-gray-850 pb-3">
            <div>
              <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider">Strategy Builder Workspace (Opstra-Style)</h3>
              <p className="text-[10px] text-gray-500 mt-0.5">Customize your options profile, analyze the payoff, and save to database.</p>
            </div>
            <button
              onClick={handleClearLegs}
              className="px-3 py-1 bg-red-950 hover:bg-red-900 border border-red-800 text-red-400 text-xs font-semibold rounded-lg transition-colors"
            >
              Clear Workspace
            </button>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
            
            {/* Left Column: Active Legs Control Table (5 cols) */}
            <div className="xl:col-span-5 space-y-4 flex flex-col justify-between">
              
              {/* Compact Opstra-style leg table */}
              <div className="overflow-x-auto">
                <table className="w-full text-xs font-mono border-collapse">
                  <thead>
                    <tr className="text-[9px] text-gray-500 uppercase tracking-wider border-b border-gray-800">
                      <th className="py-1.5 px-1 text-left">B/S</th>
                      <th className="py-1.5 px-1 text-center">Strike</th>
                      <th className="py-1.5 px-1 text-center">Type</th>
                      <th className="py-1.5 px-1 text-center">Lots</th>
                      <th className="py-1.5 px-1 text-right">Entry ₹</th>
                      <th className="py-1.5 px-1 text-right">LTP</th>
                      {isLive && <th className="py-1.5 px-1 text-right">P&amp;L</th>}
                      <th className="py-1.5 px-1" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-800/60">
                    {legs.map((leg) => {
                      const currentLtp = getLegLtp(data, leg);
                      const pnl = getLegPnl(data, leg);
                      return (
                        <tr key={leg.id} className="hover:bg-gray-900/60 transition-colors">
                          <td className="py-1.5 px-1">
                            <span className={`px-1.5 py-0.5 rounded text-[9px] font-extrabold border ${
                              leg.action === "BUY"
                                ? "bg-green-950 text-green-400 border-green-900/40"
                                : "bg-red-950 text-red-400 border-red-900/40"
                            }`}>
                              {leg.action === "BUY" ? "B" : "S"}
                            </span>
                          </td>
                          <td className="py-1.5 px-1 text-center font-bold text-gray-200">{leg.strike}</td>
                          <td className="py-1.5 px-1 text-center">
                            <span className={`font-bold ${leg.opt_type === "CE" ? "text-red-400" : "text-green-400"}`}>
                              {leg.opt_type}
                            </span>
                          </td>
                          <td className="py-1.5 px-1">
                            <input
                              type="number" min="1" value={leg.lots}
                              onChange={(e) => handleUpdateLeg(leg.id, { lots: Math.max(1, Number(e.target.value)) })}
                              className="w-12 bg-gray-900 border border-gray-800 rounded px-1.5 py-0.5 text-[11px] text-white text-center focus:outline-none focus:border-blue-600"
                            />
                          </td>
                          <td className="py-1.5 px-1">
                            <input
                              type="number" step="0.05" value={leg.entry_price}
                              onChange={(e) => handleUpdateLeg(leg.id, { entry_price: Number(e.target.value) })}
                              className="w-16 bg-gray-900 border border-gray-800 rounded px-1.5 py-0.5 text-[11px] text-white text-right focus:outline-none focus:border-blue-600"
                            />
                          </td>
                          <td className="py-1.5 px-1 text-right text-gray-300">
                            {currentLtp !== null ? currentLtp.toFixed(2) : "—"}
                          </td>
                          {isLive && (
                            <td className="py-1.5 px-1 text-right">
                              {pnl !== null ? (
                                <span className={`text-[10px] font-bold ${pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                                  {pnl >= 0 ? "+" : ""}₹{Math.round(pnl).toLocaleString("en-IN")}
                                </span>
                              ) : "—"}
                            </td>
                          )}
                          <td className="py-1.5 px-1 text-center">
                            <button
                              onClick={() => handleRemoveLeg(leg.id)}
                              className="text-gray-600 hover:text-red-400 transition-colors text-xs"
                              title="Remove"
                            >🗑</button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* Total paper P&L */}
              {isLive && legs.length > 0 && (() => {
                const total = legs.reduce((sum, leg) => {
                  const p = getLegPnl(data, leg);
                  return p !== null ? sum + p : sum;
                }, 0);
                const hasPnl = legs.some(leg => getLegPnl(data, leg) !== null);
                if (!hasPnl) return null;
                return (
                  <div className={`flex items-center justify-between px-3 py-2 rounded-lg border font-mono ${
                    total >= 0 ? "bg-green-950/40 border-green-800/50 text-green-300"
                               : "bg-red-950/40 border-red-800/50 text-red-300"
                  }`}>
                    <span className="text-[10px] font-bold uppercase tracking-wider text-gray-400">Paper P&amp;L</span>
                    <span className="text-sm font-extrabold">
                      {total >= 0 ? "+" : ""}₹{Math.round(total).toLocaleString("en-IN")}
                    </span>
                  </div>
                );
              })()}

              {/* Save strategy widget */}
              <div className="border-t border-gray-850 pt-4 mt-auto space-y-3">
                <h4 className="text-[10px] text-gray-500 uppercase tracking-wider font-bold">Save Strategy Workspace</h4>
                <div className="flex gap-2">
                  <input
                    type="text"
                    placeholder="Enter strategy name (e.g. Bull Call Spread)..."
                    value={strategyName}
                    onChange={(e) => setStrategyName(e.target.value)}
                    className="bg-gray-950 border border-gray-800 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500 flex-1"
                  />
                  <button
                    onClick={handleSaveStrategy}
                    className="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold rounded-lg transition-colors shadow-md shadow-blue-900/10"
                  >
                    Save Strategy
                  </button>
                </div>
              </div>
            </div>

            {/* Right Column: Recharts Payoff Curve & Net Greeks (7 cols) */}
            <div className="xl:col-span-7 flex flex-col gap-5">
              
              {/* Payoff line chart */}
              <div className="bg-gray-950 border border-gray-850 rounded-xl p-4 h-[280px]">
                {payoffLoading && !payoff && (
                  <div className="h-full flex items-center justify-center text-gray-500 text-xs animate-pulse">Calculating strategy curves...</div>
                )}
                {payoff && (
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={payoffChartData} margin={{ top: 14, right: 16, left: 10, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 6" stroke="#1a2233" vertical={false} />
                      <XAxis dataKey="spot" stroke="#6b7280" fontSize={9}
                        tickFormatter={(v) => (v / 1000).toFixed(1) + "k"} />
                      <YAxis stroke="#6b7280" fontSize={9}
                        tickFormatter={(v) => v >= 0 ? `+${(v/1000).toFixed(0)}k` : `${(v/1000).toFixed(0)}k`}
                        width={42} />
                      <Tooltip
                        contentStyle={{ backgroundColor: "#030712", borderColor: "#1f2937", fontSize: 11 }}
                        labelStyle={{ color: "#9ca3af", fontWeight: "bold" }}
                        labelFormatter={(v: number) => `Spot: ₹${v.toLocaleString("en-IN")}`}
                        formatter={(val: number, name: string) => {
                          if (name === "profit_fill" || name === "loss_fill") return [null, null];
                          return [`${val >= 0 ? "+" : ""}₹${Math.round(val).toLocaleString("en-IN")}`, name];
                        }}
                      />
                      <Legend verticalAlign="top" height={22} iconType="circle" wrapperStyle={{ fontSize: "10px" }} />

                      {/* Green fill: Area fills exactly under the profit triangle, above zero */}
                      <Area type="linear" dataKey="profit_fill" fill="rgba(16,185,129,0.22)"
                        stroke="none" isAnimationActive={false} legendType="none" activeDot={false} />
                      {/* Red fill: Area fills exactly under the loss curve, below zero */}
                      <Area type="linear" dataKey="loss_fill" fill="rgba(239,68,68,0.25)"
                        stroke="none" isAnimationActive={false} legendType="none" activeDot={false} />

                      {/* Zero line */}
                      <ReferenceLine y={0} stroke="#4b5563" strokeWidth={1} />

                      {/* Breakeven vertical lines */}
                      {payoff.breakevens.map((be, i) => (
                        <ReferenceLine key={`be-${i}`} x={be} stroke="#f59e0b" strokeWidth={1.5} strokeDasharray="4 3"
                          label={{ value: `BE ${be.toLocaleString("en-IN")}`, fill: "#f59e0b", fontSize: 8,
                            position: i === 0 ? "insideTopRight" : "insideTopLeft" }} />
                      ))}

                      {/* 2σ lines */}
                      {sigma1 && spotPrice && (
                        <>
                          <ReferenceLine x={Math.round(spotPrice - sigma1 * 2)} stroke="#a78bfa" strokeDasharray="3 5" strokeWidth={1}
                            label={{ value: "−2SD", fill: "#a78bfa", fontSize: 8, position: "insideTopRight" }} />
                          <ReferenceLine x={Math.round(spotPrice + sigma1 * 2)} stroke="#a78bfa" strokeDasharray="3 5" strokeWidth={1}
                            label={{ value: "+2SD", fill: "#a78bfa", fontSize: 8, position: "insideTopLeft" }} />
                        </>
                      )}

                      {/* 1σ lines */}
                      {sigma1 && spotPrice && (
                        <>
                          <ReferenceLine x={Math.round(spotPrice - sigma1)} stroke="#818cf8" strokeDasharray="4 3" strokeWidth={1.5}
                            label={{ value: "−1SD", fill: "#818cf8", fontSize: 8, position: "insideTopRight" }} />
                          <ReferenceLine x={Math.round(spotPrice + sigma1)} stroke="#818cf8" strokeDasharray="4 3" strokeWidth={1.5}
                            label={{ value: "+1SD", fill: "#818cf8", fontSize: 8, position: "insideTopLeft" }} />
                        </>
                      )}

                      {/* Spot line */}
                      {spotPrice && (
                        <ReferenceLine x={spotPrice} stroke="#22c55e" strokeWidth={1.5} strokeDasharray="4 3"
                          label={{ value: "SPOT", fill: "#22c55e", fontSize: 8, position: "insideTopRight" }} />
                      )}

                      {/* Projected P&L dot at current spot price */}
                      {spotPrice && spotPnl !== null && (() => {
                        const projPnl = Math.round(spotPnl + ivImpact);
                        const color = projPnl >= 0 ? "#10b981" : "#ef4444";
                        const label = `${projPnl >= 0 ? "+" : ""}₹${projPnl.toLocaleString("en-IN")}`;
                        return (
                          <ReferenceDot x={spotPrice} y={projPnl} r={5}
                            fill={color} stroke="#111827" strokeWidth={2}
                            label={{ value: label, position: "top", fill: color, fontSize: 10, fontWeight: "bold" }} />
                        );
                      })()}

                      <Line type="linear" dataKey="expiry_pnl" name="On Expiry" stroke="#22c55e" strokeWidth={3} dot={false} isAnimationActive={false} />
                      <Line type="monotone" dataKey="today_pnl" name="On Target Date" stroke="#60a5fa" strokeWidth={1.5} dot={false} strokeDasharray="5 3" isAnimationActive={false} />
                    </ComposedChart>
                  </ResponsiveContainer>
                )}
                {payoff && sigma1 && (
                  <div className="flex gap-3 mt-1 px-1 text-[9px] text-gray-600 flex-wrap">
                    <span className="text-indigo-400">1SD ±{Math.round(sigma1).toLocaleString("en-IN")}</span>
                    <span className="text-purple-400">2SD ±{Math.round(sigma1 * 2).toLocaleString("en-IN")}</span>
                    {atmIv && <span>IV {atmIv.toFixed(1)}% · {Math.round(daysToExpiry)}DTE</span>}
                  </div>
                )}
              </div>

              {/* IV Simulator — below chart, affects blue "On Target Date" curve */}
              {payoff && (
                <div className="bg-gray-950 border border-gray-800 rounded-lg px-4 py-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-gray-400 uppercase tracking-wider font-bold">IV Simulator</span>
                    <div className="flex items-center gap-3">
                      {atmIv && (
                        <span className="text-[10px] text-gray-500 font-mono">
                          ATM {atmIv.toFixed(1)}% → <span className={ivShift !== 0 ? "text-indigo-300 font-bold" : "text-gray-500"}>{(atmIv + ivShift).toFixed(1)}%</span>
                        </span>
                      )}
                      <span className={`text-[11px] font-bold font-mono ${ivShift === 0 ? "text-gray-600" : ivImpact >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {ivShift === 0 ? "neutral" : `${ivShift > 0 ? "+" : ""}${ivShift}% → ${ivImpact >= 0 ? "+" : ""}₹${Math.abs(ivImpact).toLocaleString("en-IN")}`}
                      </span>
                      {ivShift !== 0 && (
                        <button onClick={() => setIvShift(0)} className="text-[10px] text-gray-500 hover:text-gray-300 border border-gray-700 rounded px-1.5 py-0.5">Reset</button>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-[9px] text-red-400 font-mono w-8 text-right">−50%</span>
                    <input
                      type="range" min={-50} max={50} step={1} value={ivShift}
                      onChange={(e) => setIvShift(Number(e.target.value))}
                      className="flex-1 accent-indigo-500 h-1.5 bg-gray-800 rounded cursor-pointer"
                    />
                    <span className="text-[9px] text-green-400 font-mono w-8">+50%</span>
                  </div>
                  <div className="flex gap-1.5 justify-center">
                    {[-20, -10, -5, 5, 10, 20].map(v => (
                      <button key={v} onClick={() => setIvShift(v)}
                        className={`text-[9px] px-2 py-0.5 rounded border font-mono transition-colors ${
                          ivShift === v ? "bg-indigo-900/60 border-indigo-700 text-indigo-300"
                                        : "border-gray-800 text-gray-600 hover:text-gray-400 hover:border-gray-700"
                        }`}>
                        {v > 0 ? "+" : ""}{v}%
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Payoff Metrics & Greeks grid */}
              {payoff && (
                <div className="space-y-4">
                  {/* Summary Cards */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <div className="bg-gray-950 border border-gray-850 p-3 rounded-lg">
                      <div className="text-[9px] text-gray-500 uppercase tracking-wider font-bold">Max Profit</div>
                      <div className={`text-sm font-extrabold font-mono mt-0.5 ${maxProfit === null ? "text-green-400" : maxProfit >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {maxProfit === null ? "Unlimited" : `₹${maxProfit.toLocaleString("en-IN")}`}
                      </div>
                    </div>
                    <div className="bg-gray-950 border border-gray-850 p-3 rounded-lg">
                      <div className="text-[9px] text-gray-500 uppercase tracking-wider font-bold">Max Loss</div>
                      <div className={`text-sm font-extrabold font-mono mt-0.5 ${maxLoss === null ? "text-red-400 animate-pulse" : maxLoss >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {maxLoss === null ? "Unlimited" : `₹${maxLoss.toLocaleString("en-IN")}`}
                      </div>
                    </div>
                    <div className="bg-gray-950 border border-gray-850 p-3 rounded-lg">
                      <div className="text-[9px] text-gray-500 uppercase tracking-wider font-bold">Net Premium</div>
                      <div className={`text-sm font-extrabold font-mono mt-0.5 ${payoff.net_premium >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {payoff.net_premium >= 0 ? `+₹${payoff.net_premium.toLocaleString()}` : `-₹${Math.abs(payoff.net_premium).toLocaleString()}`}
                      </div>
                    </div>
                    <div className="bg-gray-950 border border-gray-850 p-3 rounded-lg flex flex-col justify-center">
                      <div className="text-[9px] text-gray-500 uppercase tracking-wider font-bold">Breakevens</div>
                      <div className="flex flex-wrap gap-1 mt-1">
                        {payoff.breakevens.map(b => (
                          <span key={b} className="text-[10px] font-bold font-mono bg-gray-900 border border-gray-800 px-1 py-0.2 rounded text-gray-300">{Math.round(b)}</span>
                        ))}
                      </div>
                    </div>
                  </div>

                  {/* Greeks Row */}
                  <div className="bg-gray-950 border border-gray-850 rounded-xl p-4">
                    <h4 className="text-[10px] text-gray-550 uppercase tracking-wider font-bold mb-2.5">Portfolio Greeks (Combined)</h4>
                    <div className="grid grid-cols-4 gap-2 font-mono">
                      {[
                        { label: "Delta", val: payoff.net_greeks.delta.toFixed(3), color: payoff.net_greeks.delta >= 0 ? "text-green-400" : "text-red-400" },
                        { label: "Gamma", val: payoff.net_greeks.gamma.toFixed(5), color: "text-gray-300" },
                        { label: "Theta/day", val: `₹${payoff.net_greeks.theta.toFixed(0)}`, color: payoff.net_greeks.theta >= 0 ? "text-green-400" : "text-red-400" },
                        { label: "Vega/1%", val: `₹${payoff.net_greeks.vega.toFixed(0)}`, color: payoff.net_greeks.vega >= 0 ? "text-green-400" : "text-red-400" },
                      ].map(g => (
                        <div key={g.label} className="bg-gray-900/60 p-2 rounded border border-gray-850">
                          <div className="text-[9px] text-gray-500">{g.label}</div>
                          <div className={`text-xs font-bold mt-0.5 ${g.color}`}>{g.val}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

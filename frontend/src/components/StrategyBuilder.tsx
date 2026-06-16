import { useState, useEffect } from "react";
import { runBacktest } from "../api";
import type {
  BacktestResponse, LegSpec, ExitConditionsConfig, EntryConditionsConfig,
  IndicatorDef, ConditionGroup,
} from "../types";
import { DEFAULT_EXIT, DEFAULT_ENTRY } from "../types";
import { STRATEGY_TEMPLATES } from "../data/templates";
import type { StrategyTemplate } from "../data/templates";
import ExitConditions from "./ExitConditions";
import EntryConditions from "./EntryConditions";
import SignalBuilder, { emptyGroup } from "./SignalBuilder";

interface Props {
  onResult: (r: BacktestResponse) => void;
  onLoading?: (b: boolean) => void;
}

type LegRow = LegSpec & { id: string };

const mkLeg = (opt_type: "CE" | "PE" = "CE"): LegRow => ({
  id: Math.random().toString(36).slice(2),
  action: "SELL", opt_type, selection: "ATM", value: 0,
  lots: 1, sl_pct: null, sl_unit: "PERCENT", tp_pct: null, tp_unit: "PERCENT",
});

const VALUE_LABEL: Record<string, string> = {
  ATM: "Offset (steps)", PREMIUM: "Target Premium ₹", DELTA: "Target Delta (0–1)",
};

const CATEGORIES = [
  { id: "all", label: "All" },
  { id: "premium-sell", label: "Premium Sell" },
  { id: "spread", label: "Spread" },
  { id: "directional", label: "Directional" },
  { id: "indicator", label: "Indicator" },
];

function Toggle({ options, value, onChange, color }: {
  options: string[]; value: string; onChange: (v: string) => void; color?: (v: string) => string;
}) {
  return (
    <div className="flex rounded-lg overflow-hidden border border-gray-700">
      {options.map((o) => (
        <button key={o} type="button" onClick={() => onChange(o)}
          className={`flex-1 py-1.5 text-xs font-medium transition-colors ${
            value === o ? (color ? color(o) : "bg-blue-700 text-white") : "bg-gray-900 text-gray-500 hover:text-gray-300"
          }`}>{o}</button>
      ))}
    </div>
  );
}

export default function StrategyBuilder({ onResult, onLoading }: Props) {
  const [underlying, setUnderlying] = useState<"NIFTY" | "BANKNIFTY">("NIFTY");
  const [start, setStart] = useState("2023-01-02");
  const [end, setEnd] = useState("2023-12-29");
  const [entryTime, setEntryTime] = useState("09:20");
  const [exitTime, setExitTime] = useState("15:15");
  const [expiryOffset, setExpiryOffset] = useState(0);
  const [legs, setLegs] = useState<LegRow[]>([mkLeg("CE"), mkLeg("PE")]);
  const [exitConds, setExitConds] = useState<ExitConditionsConfig>(DEFAULT_EXIT);
  const [entryConds, setEntryConds] = useState<EntryConditionsConfig>(DEFAULT_ENTRY);
  const [indicators, setIndicators] = useState<IndicatorDef[]>([]);
  const [entrySignal, setEntrySignal] = useState<ConditionGroup>(emptyGroup());
  const [exitSignal, setExitSignal] = useState<ConditionGroup>(emptyGroup());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showTemplates, setShowTemplates] = useState(false);
  const [catFilter, setCatFilter] = useState("all");
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3000);
    return () => clearTimeout(t);
  }, [toast]);

  const updLeg = (id: string, patch: Partial<LegSpec>) =>
    setLegs((ls) => ls.map((l) => (l.id === id ? { ...l, ...patch } : l)));

  const loadTemplate = (t: StrategyTemplate) => {
    setUnderlying(t.underlying);
    setEntryTime(t.entry_time);
    setExitTime(t.exit_time);
    setExpiryOffset(t.expiry_offset);
    setLegs(t.legs.map((l) => ({
      ...l, id: Math.random().toString(36).slice(2),
      sl_unit: "PERCENT", tp_unit: "PERCENT",
    })));
    // wire indicator + signal config (indicator-driven templates)
    setIndicators(t.indicators ?? []);
    setEntrySignal(t.entry_signal ?? emptyGroup());
    setExitSignal(t.exit_signal ?? emptyGroup());
    setExitConds(t.exit_conditions ? { ...DEFAULT_EXIT, ...t.exit_conditions } : DEFAULT_EXIT);
    setShowTemplates(false);
    setToast(`Template loaded: ${t.name}`);
  };

  const handleRun = async () => {
    setLoading(true); onLoading?.(true); setError(null);
    try {
      const res = await runBacktest({
        underlying, start, end,
        entry_time: entryTime, exit_time: exitTime,
        legs: legs.map(({ id: _id, ...l }) => l),
        expiry_offset: expiryOffset,
        exit_conditions: exitConds,
        entry_conditions: entryConds,
        indicators: indicators.length ? indicators : undefined,
        entry_signal: entrySignal.conditions.length ? entrySignal : undefined,
        exit_signal: exitSignal.conditions.length ? exitSignal : undefined,
      });
      onResult(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false); onLoading?.(false);
    }
  };

  const inp = "w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500";
  const filtered = STRATEGY_TEMPLATES.filter((t) => catFilter === "all" || t.category === catFilter);

  return (
    <div className="p-5 space-y-5">
      <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest">Strategy Builder</h2>

      {toast && (
        <div className="bg-green-900/40 border border-green-700/50 rounded-lg px-3 py-2 text-xs text-green-400">{toast}</div>
      )}

      {/* Template Selector */}
      <div className="space-y-3">
        <button type="button" onClick={() => setShowTemplates((v) => !v)}
          className="w-full flex items-center justify-between py-2 px-3 bg-gray-800/60 rounded-lg border border-gray-700/50 hover:border-blue-600/40 transition-colors">
          <span className="text-xs font-semibold text-gray-400 uppercase tracking-widest">Strategy Templates</span>
          <span className="text-[10px] text-blue-400">{showTemplates ? "▲ Close" : "▼ Browse"}</span>
        </button>
        {showTemplates && (
          <div className="space-y-3">
            <div className="flex gap-1.5 flex-wrap">
              {CATEGORIES.map((c) => (
                <button key={c.id} type="button" onClick={() => setCatFilter(c.id)}
                  className={`px-2.5 py-1 rounded-lg text-[10px] font-medium transition-colors ${catFilter === c.id ? "bg-blue-700 text-white" : "bg-gray-800 text-gray-500 hover:text-gray-300"}`}>
                  {c.label}
                </button>
              ))}
            </div>
            <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
              {filtered.map((t) => (
                <div key={t.id} className="bg-gray-800/60 border border-gray-700/50 rounded-xl p-3 space-y-2 hover:border-blue-600/40 transition-colors">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-semibold text-white">{t.name}</div>
                      <div className="text-[10px] text-gray-400 mt-0.5 leading-relaxed">{t.description}</div>
                    </div>
                    <button type="button" onClick={() => loadTemplate(t)}
                      className="px-2.5 py-1 rounded-lg bg-blue-700 hover:bg-blue-600 text-white text-[10px] font-semibold transition-colors whitespace-nowrap flex-shrink-0">
                      Load
                    </button>
                  </div>
                  <div className="flex gap-1 flex-wrap">
                    {t.tags.slice(0, 3).map((tag) => (
                      <span key={tag} className="text-[9px] px-1.5 py-0.5 rounded bg-gray-700 text-gray-400">{tag}</span>
                    ))}
                  </div>
                  {t.exit_hint && <p className="text-[9px] text-gray-600 italic">{t.exit_hint}</p>}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Underlying */}
      <div className="space-y-1.5">
        <label className="text-xs text-gray-500">Underlying</label>
        <div className="flex gap-2">
          {(["NIFTY", "BANKNIFTY"] as const).map((u) => (
            <button key={u} type="button" onClick={() => setUnderlying(u)}
              className={`flex-1 py-2 rounded-lg text-sm font-semibold transition-colors ${underlying === u ? "bg-blue-600 text-white" : "bg-gray-800 text-gray-400 hover:bg-gray-700"}`}>
              {u}
            </button>
          ))}
        </div>
      </div>

      {/* Dates */}
      <div className="grid grid-cols-2 gap-3">
        {[{ label: "Start Date", val: start, set: setStart }, { label: "End Date", val: end, set: setEnd }].map(({ label, val, set }) => (
          <div key={label} className="space-y-1.5">
            <label className="text-xs text-gray-500">{label}</label>
            <input type="date" value={val} onChange={(e) => set(e.target.value)} className={inp} />
          </div>
        ))}
      </div>

      {/* Times */}
      <div className="grid grid-cols-2 gap-3">
        {[{ label: "Entry Time", val: entryTime, set: setEntryTime }, { label: "Exit Time", val: exitTime, set: setExitTime }].map(({ label, val, set }) => (
          <div key={label} className="space-y-1.5">
            <label className="text-xs text-gray-500">{label}</label>
            <input type="time" value={val} onChange={(e) => set(e.target.value)} className={inp} />
          </div>
        ))}
      </div>

      {/* Expiry */}
      <div className="space-y-1.5">
        <label className="text-xs text-gray-500">Expiry</label>
        <select value={expiryOffset} onChange={(e) => setExpiryOffset(Number(e.target.value))} className={inp}>
          <option value={0}>Nearest Weekly (0)</option>
          <option value={1}>Next Expiry (1)</option>
          <option value={2}>Monthly (2)</option>
        </select>
      </div>

      {/* Legs */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-gray-400 uppercase tracking-widest">Legs</span>
          <button type="button" onClick={() => setLegs((ls) => [...ls, mkLeg()])}
            className="text-xs text-blue-400 hover:text-blue-300 font-medium">+ Add Leg</button>
        </div>
        {legs.map((leg, idx) => (
          <div key={leg.id} className="bg-gray-800/60 rounded-xl p-4 space-y-3 border border-gray-700/50">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-gray-400">Leg {idx + 1}</span>
              {legs.length > 1 && (
                <button type="button" onClick={() => setLegs((ls) => ls.filter((l) => l.id !== leg.id))}
                  className="text-xs text-gray-600 hover:text-red-400 transition-colors">Remove</button>
              )}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div><label className="text-[10px] text-gray-600 block mb-1">Action</label>
                <Toggle options={["BUY", "SELL"]} value={leg.action}
                  onChange={(v) => updLeg(leg.id, { action: v as "BUY" | "SELL" })}
                  color={(v) => v === "SELL" ? "bg-red-700 text-white" : "bg-green-700 text-white"} /></div>
              <div><label className="text-[10px] text-gray-600 block mb-1">Type</label>
                <Toggle options={["CE", "PE"]} value={leg.opt_type}
                  onChange={(v) => updLeg(leg.id, { opt_type: v as "CE" | "PE" })} /></div>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <div><label className="text-[10px] text-gray-600 block mb-1">Strike</label>
                <select value={leg.selection} onChange={(e) => updLeg(leg.id, { selection: e.target.value as LegSpec["selection"] })}
                  className="w-full bg-gray-950 border border-gray-700 rounded-lg px-2 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500">
                  <option value="ATM">ATM</option><option value="PREMIUM">Premium</option><option value="DELTA">Delta</option>
                </select></div>
              <div className="col-span-2"><label className="text-[10px] text-gray-600 block mb-1">{VALUE_LABEL[leg.selection]}</label>
                <input type="number" step={leg.selection === "DELTA" ? "0.01" : "1"} value={leg.value}
                  onChange={(e) => updLeg(leg.id, { value: Number(e.target.value) })}
                  className="w-full bg-gray-950 border border-gray-700 rounded-lg px-2 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500" /></div>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {[
                { lbl: "Lots", key: "lots", min: 1, ph: "", step: "1" },
                { lbl: "SL %", key: "sl_pct", min: 0, ph: "none", step: "5" },
                { lbl: "TP %", key: "tp_pct", min: 0, ph: "none", step: "5" },
              ].map(({ lbl, key, min, ph, step }) => (
                <div key={key}><label className="text-[10px] text-gray-600 block mb-1">{lbl}</label>
                  <input type="number" min={min} step={step} placeholder={ph}
                    value={key === "lots" ? leg.lots : (leg[key as "sl_pct" | "tp_pct"] ?? "")}
                    onChange={(e) => updLeg(leg.id, {
                      [key]: key === "lots" ? Number(e.target.value) : (e.target.value ? Number(e.target.value) : null)
                    })}
                    className="w-full bg-gray-950 border border-gray-700 rounded-lg px-2 py-1.5 text-xs text-white placeholder-gray-700 focus:outline-none focus:border-blue-500" /></div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <SignalBuilder
        indicators={indicators} setIndicators={setIndicators}
        entry={entrySignal} setEntry={setEntrySignal}
        exit={exitSignal} setExit={setExitSignal}
      />

      <ExitConditions value={exitConds} onChange={setExitConds} />
      <EntryConditions value={entryConds} onChange={setEntryConds} />

      {error && (
        <div className="bg-red-900/30 border border-red-700/60 rounded-lg px-4 py-3 text-sm text-red-400">{error}</div>
      )}

      <button type="button" onClick={handleRun} disabled={loading}
        className="w-full py-3 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:bg-gray-800 disabled:text-gray-500 text-white font-semibold text-sm transition-colors">
        {loading ? "Running backtest…" : "Run Backtest"}
      </button>
    </div>
  );
}

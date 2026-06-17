import { useState, useEffect } from "react";
import { runBacktest, getTemplates, validateStrategy, saveStrategy, listStrategies, deleteStrategy, cloneStrategy, estimateMargin } from "../api";
import type {
  BacktestResponse, LegSpec, ExitConditionsConfig, EntryConditionsConfig,
  IndicatorDef, ConditionGroup, SavedStrategy
} from "../types";
import { DEFAULT_EXIT, DEFAULT_ENTRY } from "../types";
import ExitConditions from "./ExitConditions";
import EntryConditions from "./EntryConditions";
import SignalBuilder, { emptyGroup } from "./SignalBuilder";
import LegBuilder from "./LegBuilder";
import StrategyValidationPanel from "./StrategyValidationPanel";
import SavedStrategiesPanel from "./SavedStrategiesPanel";

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

const CATEGORIES = [
  { id: "all", label: "All" },
  { id: "premium-sell", label: "Premium Sell" },
  { id: "spread", label: "Spread" },
  { id: "directional", label: "Directional" },
];

export default function StrategyBuilder({ onResult, onLoading }: Props) {
  const [strategyName, setStrategyName] = useState("My Straddle Strategy");
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
  
  // templates / saved / validation / margin state
  const [templates, setTemplates] = useState<any[]>([]);
  const [savedStrategies, setSavedStrategies] = useState<SavedStrategy[]>([]);
  const [validation, setValidation] = useState<any>({ valid: true, errors: [], warnings: [] });
  const [estimatedMargin, setEstimatedMargin] = useState(0);
  const [showTemplates, setShowTemplates] = useState(false);
  const [catFilter, setCatFilter] = useState("all");
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    // Fetch templates
    getTemplates().then((res) => setTemplates(res.templates || [])).catch(() => setTemplates([]));
    // Fetch saved strategies
    refreshSaved();
  }, []);

  const refreshSaved = () => {
    listStrategies().then(setSavedStrategies).catch(() => setSavedStrategies([]));
  };

  useEffect(() => {
    // Run validation precheck
    validateStrategy({
      underlying, legs: legs.map(({ id, ...l }) => l), expiry_offset: expiryOffset
    }).then(setValidation).catch(() => null);

    // Run margin estimate (dummy strike values for estimate)
    const marginLegs = legs.map((l, i) => ({
      action: l.action,
      opt_type: l.opt_type,
      strike: l.opt_type === "CE" ? 23000 + i * 100 : 23000 - i * 100,
      lots: l.lots,
      entry_price: l.value || 100.0
    }));
    estimateMargin({ underlying, expiry: "2026-06-30", legs: marginLegs })
      .then((res) => setEstimatedMargin(res.estimated_margin))
      .catch(() => setEstimatedMargin(0));
  }, [underlying, legs, expiryOffset]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3000);
    return () => clearTimeout(t);
  }, [toast]);

  const updLeg = (id: string, patch: Partial<LegSpec>) =>
    setLegs((ls) => ls.map((l) => (l.id === id ? { ...l, ...patch } : l)));

  const loadTemplate = (t: any) => {
    setUnderlying(t.underlying || "NIFTY");
    setEntryTime(t.entry_time);
    setExitTime(t.exit_time);
    setLegs(t.legs.map((l: any) => ({
      ...l, id: Math.random().toString(36).slice(2),
      sl_unit: "PERCENT", tp_unit: "PERCENT",
      sl_pct: t.overall_sl_pct ?? null, tp_pct: t.overall_target_pct ?? null
    })));
    setShowTemplates(false);
    setToast(`Template loaded: ${t.name}`);
  };

  const handleSave = async () => {
    try {
      // Map legs structure to payoff structure compatibility
      const payoffLegs = legs.map((l) => ({
        action: l.action,
        opt_type: l.opt_type,
        strike: 23000, // placeholder since strike selection resolved at runtime
        lots: l.lots,
        entry_price: l.value || 100.0,
        underlying
      }));
      // Serialize full strategy builder configuration
      const config = {
        legs: legs.map(({ id: _id, ...rest }) => rest),
        underlying,
        start,
        end,
        entryTime,
        exitTime,
        expiryOffset,
        exitConditions: exitConds,
        entryConditions: entryConds,
        indicators,
        entrySignal,
        exitSignal,
      };
      const nextExpiry = new Date();
      nextExpiry.setDate(nextExpiry.getDate() + ((4 - nextExpiry.getDay() + 7) % 7 || 7));
      const expiryStr = nextExpiry.toISOString().slice(0, 10);
      await saveStrategy(strategyName, underlying, expiryStr, payoffLegs, config);
      setToast("Strategy saved successfully");
      refreshSaved();
    } catch (e: any) {
      setToast(`Failed to save: ${e.message}`);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteStrategy(id);
      setToast("Strategy deleted");
      refreshSaved();
    } catch (e: any) {
      setToast(`Failed to delete: ${e.message}`);
    }
  };

  const handleClone = async (id: string) => {
    try {
      await cloneStrategy(id);
      setToast("Strategy cloned");
      refreshSaved();
    } catch (e: any) {
      setToast(`Failed to clone: ${e.message}`);
    }
  };

  const handleLoadSaved = (st: SavedStrategy) => {
    setStrategyName(st.name);
    setUnderlying(st.underlying as any);

    // If full config exists, restore all builder state from it
    const cfg = (st as any).config;
    if (cfg) {
      if (cfg.legs) {
        setLegs(cfg.legs.map((l: any) => ({
          ...l,
          id: Math.random().toString(36).slice(2),
        })));
      }
      if (cfg.start) setStart(cfg.start);
      if (cfg.end) setEnd(cfg.end);
      if (cfg.entryTime) setEntryTime(cfg.entryTime);
      if (cfg.exitTime) setExitTime(cfg.exitTime);
      if (cfg.expiryOffset !== undefined) setExpiryOffset(cfg.expiryOffset);
      if (cfg.exitConditions) setExitConds(cfg.exitConditions);
      if (cfg.entryConditions) setEntryConds(cfg.entryConditions);
      if (cfg.indicators) setIndicators(cfg.indicators);
      if (cfg.entrySignal) setEntrySignal(cfg.entrySignal);
      if (cfg.exitSignal) setExitSignal(cfg.exitSignal);
    } else {
      // Fallback: populate from basic leg data
      setLegs(st.legs.map((l: any) => ({
        id: Math.random().toString(36).slice(2),
        action: l.action,
        opt_type: l.opt_type,
        selection: "ATM",
        value: 0,
        lots: l.lots,
        sl_pct: null,
        sl_unit: "PERCENT",
        tp_pct: null,
        tp_unit: "PERCENT"
      })));
    }
    setToast(`Saved strategy loaded: ${st.name}`);
  };

  const handleRun = async () => {
    if (!validation.valid) {
      setToast("Please fix validation errors before running backtest.");
      return;
    }
    setLoading(true); onLoading?.(true);
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
      setToast(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false); onLoading?.(false);
    }
  };

  const inp = "w-full bg-gray-950 border border-gray-700 hover:border-gray-650 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-blue-500 transition-colors";
  const filteredTemplates = templates.filter((t) => {
    if (catFilter === "all") return true;
    if (catFilter === "directional") return t.template_id.includes("spread");
    if (catFilter === "spread") return t.template_id.includes("condor") || t.template_id.includes("spread");
    if (catFilter === "premium-sell") return t.template_id.includes("straddle") || t.template_id.includes("strangle");
    return true;
  });

  return (
    <div className="p-5 space-y-5">
      <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest border-b border-gray-800 pb-2">
        Strategy Builder
      </h2>

      {toast && (
        <div className="bg-blue-950/30 border border-blue-800/40 rounded-xl px-3 py-2.5 text-xs text-blue-400 transition-all">
          {toast}
        </div>
      )}

      {/* Save / Edit strategy header */}
      <div className="space-y-1.5 bg-gray-950/40 border border-gray-800 rounded-xl p-3">
        <label className="text-[10px] uppercase font-bold text-gray-500">Workspace Strategy Name</label>
        <div className="flex gap-2">
          <input
            type="text"
            value={strategyName}
            onChange={(e) => setStrategyName(e.target.value)}
            className="flex-1 bg-gray-900 border border-gray-850 hover:border-gray-800 rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none"
          />
          <button
            type="button"
            onClick={handleSave}
            className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold transition-colors"
          >
            Save
          </button>
        </div>
      </div>

      {/* Template Selector */}
      <div className="space-y-3">
        <button type="button" onClick={() => setShowTemplates((v) => !v)}
          className="w-full flex items-center justify-between py-2 px-3 bg-gray-900/60 rounded-xl border border-gray-800 hover:border-gray-700 transition-all duration-200">
          <span className="text-xs font-semibold text-gray-400">Strategy Templates</span>
          <span className="text-[10px] text-blue-400 font-bold">{showTemplates ? "▲ Close" : "▼ Browse Templates"}</span>
        </button>
        {showTemplates && (
          <div className="space-y-3 p-1.5 border border-gray-800 rounded-xl bg-gray-950/20">
            <div className="flex gap-1 flex-wrap">
              {CATEGORIES.map((c) => (
                <button key={c.id} type="button" onClick={() => setCatFilter(c.id)}
                  className={`px-2.5 py-1 rounded-lg text-[9px] font-bold uppercase transition-colors ${catFilter === c.id ? "bg-blue-600 text-white" : "bg-gray-900 text-gray-500 hover:text-gray-300"}`}>
                  {c.label}
                </button>
              ))}
            </div>
            <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
              {filteredTemplates.map((t) => (
                <div key={t.template_id} className="bg-gray-900/60 border border-gray-850 rounded-xl p-3 space-y-2 hover:border-blue-900/30 transition-colors">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-extrabold text-white">{t.name}</div>
                      <div className="text-[10px] text-gray-400 mt-0.5 leading-relaxed">{t.description}</div>
                    </div>
                    <button type="button" onClick={() => loadTemplate(t)}
                      className="px-2.5 py-1 rounded bg-blue-600 hover:bg-blue-500 text-white text-[10px] font-semibold transition-colors flex-shrink-0">
                      Load
                    </button>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-gray-950 text-gray-500 font-bold">{t.risk_level} RISK</span>
                    {t.suitable_regime.map((rg: string) => (
                      <span key={rg} className="text-[9px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">{rg.replace("_", " ")}</span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Underlying & Estimate Margin info */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <label className="text-xs text-gray-500">Underlying Asset</label>
          <span className="text-[10px] text-gray-400 font-mono">
            Est Margin: <strong className="text-amber-400">₹{estimatedMargin.toLocaleString()}</strong>
          </span>
        </div>
        <div className="flex gap-2">
          {(["NIFTY", "BANKNIFTY"] as const).map((u) => (
            <button key={u} type="button" onClick={() => setUnderlying(u)}
              className={`flex-1 py-2 rounded-xl text-xs font-extrabold transition-all duration-200 ${underlying === u ? "bg-blue-600 text-white shadow-md" : "bg-gray-900 text-gray-400 hover:bg-gray-800"}`}>
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
        <label className="text-xs text-gray-500">Expiry Contract</label>
        <select value={expiryOffset} onChange={(e) => setExpiryOffset(Number(e.target.value))} className={inp}>
          <option value={0}>Nearest Weekly (0)</option>
          <option value={1}>Next Expiry (1)</option>
          <option value={2}>Monthly (2)</option>
        </select>
      </div>

      {/* Legs */}
      <div className="space-y-3">
        <div className="flex items-center justify-between border-b border-gray-800 pb-1.5">
          <span className="text-xs font-semibold text-gray-400 uppercase tracking-widest">Legs</span>
          <button type="button" onClick={() => setLegs((ls) => [...ls, mkLeg()])}
            className="text-xs text-blue-400 hover:text-blue-300 font-bold">+ Add Leg</button>
        </div>
        {legs.map((leg, idx) => (
          <LegBuilder
            key={leg.id}
            leg={leg}
            idx={idx}
            onUpdate={(patch) => updLeg(leg.id, patch)}
            onRemove={() => setLegs((ls) => ls.filter((l) => l.id !== leg.id))}
            isRemovable={legs.length > 1}
          />
        ))}
      </div>

      {/* Strategy Validation Panel */}
      <StrategyValidationPanel
        valid={validation.valid}
        errors={validation.errors}
        warnings={validation.warnings}
      />

      <SignalBuilder
        indicators={indicators} setIndicators={setIndicators}
        entry={entrySignal} setEntry={setEntrySignal}
        exit={exitSignal} setExit={setExitSignal}
      />

      <ExitConditions value={exitConds} onChange={setExitConds} />
      <EntryConditions value={entryConds} onChange={setEntryConds} />

      <button type="button" onClick={handleRun} disabled={loading || !validation.valid}
        className="w-full py-3.5 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:bg-gray-900 disabled:text-gray-600 text-white font-extrabold text-sm transition-all duration-200 shadow-lg shadow-blue-900/20">
        {loading ? "Running backtest…" : "Run Backtest"}
      </button>

      {/* Saved Workspace Strategies List */}
      <div className="pt-4 border-t border-gray-850">
        <SavedStrategiesPanel
          strategies={savedStrategies}
          onLoad={handleLoadSaved}
          onDelete={handleDelete}
          onClone={handleClone}
        />
      </div>
    </div>
  );
}

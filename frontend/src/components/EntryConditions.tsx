import { useState } from "react";
import type { EntryConditionsConfig, IndicatorConfig } from "../types";

interface Props {
  value: EntryConditionsConfig;
  onChange: (v: EntryConditionsConfig) => void;
}

const inp = "w-full bg-gray-950 border border-gray-700 rounded-lg px-2 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500";
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"];
const REGIMES = ["low", "normal", "elevated", "extreme"];
const REGIME_DESC: Record<string, string> = { low: "<13%", normal: "13-18%", elevated: "18-25%", extreme: ">25%" };

export default function EntryConditions({ value: v, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const set = <K extends keyof EntryConditionsConfig>(k: K, val: EntryConditionsConfig[K]) =>
    onChange({ ...v, [k]: val });
  const setInd = <K extends keyof IndicatorConfig>(k: K, val: IndicatorConfig[K]) =>
    onChange({ ...v, indicator: { ...v.indicator, [k]: val } });

  const toggleDay = (d: number) => {
    const next = v.weekdays.includes(d) ? v.weekdays.filter((x) => x !== d) : [...v.weekdays, d].sort();
    set("weekdays", next);
  };
  const toggleRegime = (r: string) => {
    const next = v.vix_regimes.includes(r) ? v.vix_regimes.filter((x) => x !== r) : [...v.vix_regimes, r];
    set("vix_regimes", next);
  };

  return (
    <div className="bg-gray-800/40 rounded-xl border border-gray-700/50 p-4 space-y-4">
      <button type="button" onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between">
        <h3 className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest">Entry Conditions</h3>
        <span className="text-gray-600 text-xs">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-[10px] text-gray-500 uppercase tracking-wider">Trade Days</label>
            <div className="flex gap-1.5">
              {DAYS.map((d, i) => (
                <button key={d} type="button" onClick={() => toggleDay(i)}
                  className={`flex-1 py-1.5 rounded-lg text-xs font-medium transition-colors ${v.weekdays.includes(i) ? "bg-blue-700 text-white" : "bg-gray-800 text-gray-500"}`}>
                  {d}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-[10px] text-gray-500 uppercase tracking-wider">
              PCR Filter <span className="text-gray-600 normal-case">(0 = off)</span>
            </label>
            <div className="grid grid-cols-2 gap-2">
              {[["Min PCR", "min_pcr"], ["Max PCR", "max_pcr"]] .map(([lbl, key]) => (
                <div key={key}>
                  <label className="text-[10px] text-gray-600 block mb-1">{lbl}</label>
                  <input type="number" min="0" step="0.1"
                    value={v[key as "min_pcr" | "max_pcr"]}
                    onChange={(e) => set(key as "min_pcr" | "max_pcr", Number(e.target.value))}
                    className={inp} />
                </div>
              ))}
            </div>
            <p className="text-[10px] text-gray-600">PCR&gt;1.3 bullish · PCR&lt;0.7 bearish</p>
          </div>

          <div className="space-y-1.5">
            <label className="text-[10px] text-gray-500 uppercase tracking-wider">
              IV Rank % Filter <span className="text-gray-600 normal-case">(0 = off)</span>
            </label>
            <div className="grid grid-cols-2 gap-2">
              {[["Min IVR %", "min_iv_rank"], ["Max IVR %", "max_iv_rank"]].map(([lbl, key]) => (
                <div key={key}>
                  <label className="text-[10px] text-gray-600 block mb-1">{lbl}</label>
                  <input type="number" min="0" max="100" step="1"
                    value={v[key as "min_iv_rank" | "max_iv_rank"]}
                    onChange={(e) => set(key as "min_iv_rank" | "max_iv_rank", Number(e.target.value))}
                    className={inp} />
                </div>
              ))}
            </div>
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center gap-3">
              <label className="text-[10px] text-gray-500 uppercase tracking-wider">VIX Regime Gate</label>
              <button type="button" onClick={() => set("use_vix_gate", !v.use_vix_gate)}
                className={`relative w-9 h-5 rounded-full transition-colors ${v.use_vix_gate ? "bg-blue-600" : "bg-gray-700"}`}>
                <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${v.use_vix_gate ? "translate-x-4" : "translate-x-0.5"}`} />
              </button>
            </div>
            {v.use_vix_gate && (
              <div className="flex gap-1.5 flex-wrap">
                {REGIMES.map((r) => (
                  <button key={r} type="button" onClick={() => toggleRegime(r)}
                    className={`px-2 py-1 rounded-lg text-[10px] font-medium transition-colors ${v.vix_regimes.includes(r) ? "bg-indigo-700 text-white" : "bg-gray-800 text-gray-500"}`}>
                    {r} {REGIME_DESC[r]}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="space-y-2">
            <label className="text-[10px] text-gray-500 uppercase tracking-wider">Indicator Filter</label>
            <select value={v.indicator.type}
              onChange={(e) => setInd("type", e.target.value as IndicatorConfig["type"])}
              className={inp}>
              <option value="">None</option>
              <option value="EMA_CROSS">EMA Crossover</option>
              <option value="RSI">RSI</option>
              <option value="BOLLINGER">Bollinger Bands</option>
              <option value="VWAP">VWAP</option>
            </select>

            {v.indicator.type === "EMA_CROSS" && (
              <div className="grid grid-cols-3 gap-2">
                <div><label className="text-[10px] text-gray-600 block mb-1">Fast</label>
                  <input type="number" min="2" value={v.indicator.ema_fast} onChange={(e) => setInd("ema_fast", Number(e.target.value))} className={inp} /></div>
                <div><label className="text-[10px] text-gray-600 block mb-1">Slow</label>
                  <input type="number" min="2" value={v.indicator.ema_slow} onChange={(e) => setInd("ema_slow", Number(e.target.value))} className={inp} /></div>
                <div><label className="text-[10px] text-gray-600 block mb-1">Signal</label>
                  <select value={v.indicator.ema_signal} onChange={(e) => setInd("ema_signal", e.target.value as "above" | "below")} className={inp}>
                    <option value="above">Bullish</option><option value="below">Bearish</option>
                  </select></div>
              </div>
            )}
            {v.indicator.type === "RSI" && (
              <div className="grid grid-cols-3 gap-2">
                <div><label className="text-[10px] text-gray-600 block mb-1">Period</label>
                  <input type="number" min="2" value={v.indicator.rsi_period} onChange={(e) => setInd("rsi_period", Number(e.target.value))} className={inp} /></div>
                <div><label className="text-[10px] text-gray-600 block mb-1">Oversold</label>
                  <input type="number" value={v.indicator.rsi_oversold} onChange={(e) => setInd("rsi_oversold", Number(e.target.value))} className={inp} /></div>
                <div><label className="text-[10px] text-gray-600 block mb-1">Overbought</label>
                  <input type="number" value={v.indicator.rsi_overbought} onChange={(e) => setInd("rsi_overbought", Number(e.target.value))} className={inp} /></div>
              </div>
            )}
            {v.indicator.type === "BOLLINGER" && (
              <div className="grid grid-cols-3 gap-2">
                <div><label className="text-[10px] text-gray-600 block mb-1">Period</label>
                  <input type="number" min="5" value={v.indicator.bb_period} onChange={(e) => setInd("bb_period", Number(e.target.value))} className={inp} /></div>
                <div><label className="text-[10px] text-gray-600 block mb-1">Std Dev</label>
                  <input type="number" min="0.5" step="0.5" value={v.indicator.bb_std} onChange={(e) => setInd("bb_std", Number(e.target.value))} className={inp} /></div>
                <div><label className="text-[10px] text-gray-600 block mb-1">Signal</label>
                  <select value={v.indicator.bb_signal} onChange={(e) => setInd("bb_signal", e.target.value as IndicatorConfig["bb_signal"])} className={inp}>
                    <option value="squeeze">Squeeze</option><option value="upper">Near Upper</option><option value="lower">Near Lower</option>
                  </select></div>
              </div>
            )}
            {v.indicator.type === "VWAP" && (
              <div><label className="text-[10px] text-gray-600 block mb-1">Spot must be</label>
                <select value={v.indicator.vwap_signal} onChange={(e) => setInd("vwap_signal", e.target.value as "above" | "below")} className={inp}>
                  <option value="above">Above VWAP (Bullish)</option><option value="below">Below VWAP (Bearish)</option>
                </select></div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

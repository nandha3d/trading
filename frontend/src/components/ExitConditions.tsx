import type { ExitConditionsConfig } from "../types";

interface Props {
  value: ExitConditionsConfig;
  onChange: (v: ExitConditionsConfig) => void;
}

const inp = "w-full bg-gray-950 border border-gray-700 rounded-lg px-2 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500";

function NumField({ label, hint, val, onChange }: {
  label: string; hint: string; val: number; onChange: (n: number) => void;
}) {
  return (
    <div className="space-y-1">
      <label className="text-[10px] text-gray-500 uppercase tracking-wider">{label}</label>
      <input type="number" min="0" max="1000" step="5" value={val}
        onChange={(e) => onChange(Number(e.target.value))} className={inp} />
      <p className="text-[10px] text-gray-600">{hint}</p>
    </div>
  );
}

export default function ExitConditions({ value: v, onChange }: Props) {
  const set = <K extends keyof ExitConditionsConfig>(k: K, val: ExitConditionsConfig[K]) =>
    onChange({ ...v, [k]: val });

  return (
    <div className="bg-gray-800/40 rounded-xl border border-gray-700/50 p-4 space-y-4">
      <h3 className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest">
        Exit Conditions
      </h3>
      <div className="grid grid-cols-2 gap-3">
        <NumField label="Overall Target %" hint="% of premium · 0=off"
          val={v.overall_target_pct} onChange={(n) => set("overall_target_pct", n)} />
        <NumField label="Overall SL %" hint="% of premium · 0=off"
          val={v.overall_sl_pct} onChange={(n) => set("overall_sl_pct", n)} />
        <NumField label="Trailing SL %" hint="% drop from peak · 0=off"
          val={v.trailing_sl_pct} onChange={(n) => set("trailing_sl_pct", n)} />
        <div className="space-y-1">
          <label className="text-[10px] text-gray-500 uppercase tracking-wider">Force Exit Time</label>
          <input type="time" value={v.force_exit_time}
            onChange={(e) => set("force_exit_time", e.target.value)} className={inp} />
          <p className="text-[10px] text-gray-600">Hard exit regardless</p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <span className="text-[10px] text-gray-500 uppercase tracking-wider">Re-entry after SL</span>
        <button type="button" onClick={() => set("re_entry_after_sl", !v.re_entry_after_sl)}
          className={`relative w-9 h-5 rounded-full transition-colors ${v.re_entry_after_sl ? "bg-blue-600" : "bg-gray-700"}`}>
          <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${v.re_entry_after_sl ? "translate-x-4" : "translate-x-0.5"}`} />
        </button>
        <span className="text-[10px] text-gray-500">{v.re_entry_after_sl ? "On" : "Off"}</span>
      </div>
    </div>
  );
}

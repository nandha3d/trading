import { useState } from "react";
import type {
  IndicatorDef, IndicatorType, Operand, Condition, ConditionGroup, CondOp,
} from "../types";

const TYPES: { v: IndicatorType; label: string }[] = [
  { v: "CURRENT_CANDLE", label: "Current Candle" },
  { v: "SMA", label: "SMA (Simple Moving Average)" },
  { v: "EMA", label: "EMA (Exponential Moving Average)" },
  { v: "RSI", label: "RSI (Relative Strength Index)" },
  { v: "MACD", label: "MACD" },
  { v: "SUPERTREND", label: "Super Trend" },
  { v: "BOLLINGER", label: "Bollinger Bands" },
  { v: "VWAP", label: "VWAP" },
  { v: "ATR", label: "ATR" },
  { v: "RANGE_BREAKOUT", label: "Range Breakout" },
];

// sub-outputs each indicator exposes (for operand reference)
export const SUBS: Record<IndicatorType, string[]> = {
  SMA: ["value"], EMA: ["value"], RSI: ["value"], ATR: ["value"], VWAP: ["value"],
  SUPERTREND: ["line", "dir"],
  MACD: ["macd", "signal", "hist"],
  BOLLINGER: ["upper", "mid", "lower"],
  RANGE_BREAKOUT: ["hi", "lo"],
  CURRENT_CANDLE: ["close", "open", "high", "low", "volume"],
};

const INTERVALS = [1, 3, 5, 15, 30, 60];
const OPS: { v: CondOp; label: string }[] = [
  { v: "==", label: "Equal To" },
  { v: ">", label: "Is Above" },
  { v: "<", label: "Is Below" },
  { v: "cross_above", label: "Crosses Above" },
  { v: "cross_below", label: "Crosses Below" },
  { v: ">=", label: "Equal Or Above" },
  { v: "<=", label: "Equal Or Below" },
];

// Candle / market operand fields (Quantman "Current …" + time operands)
const CANDLE_FIELDS: { v: string; label: string }[] = [
  { v: "close", label: "Current Close" },
  { v: "open", label: "Current Open" },
  { v: "high", label: "Current High" },
  { v: "low", label: "Current Low" },
  { v: "oi", label: "Current Open Interest" },
  { v: "volume", label: "Current Volume" },
  { v: "ltp", label: "Last Traded Price" },
  { v: "time_of_day", label: "Time Of Day (HHMM)" },
  { v: "day_of_week", label: "Day Of Week (1-5)" },
  { v: "dte", label: "Days To Expire" },
];

const uid = () => Math.random().toString(36).slice(2, 8);

const defIndicator = (): IndicatorDef => ({
  id: uid(), type: "EMA", name: "ema", interval: 5, field: "close",
  period: 14, fast: 12, slow: 26, signal: 9, multiplier: 2, std: 2,
  start_time: "09:30", end_time: "10:30",
});

const defOperand = (): Operand => ({ kind: "const", ref: "", sub: "value", field: "close", value: 0 });
const defCondition = (): Condition => ({ lhs: defOperand(), op: ">", rhs: defOperand() });

const inp = "bg-gray-950 border border-gray-700 rounded-lg px-2 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500";

interface Props {
  indicators: IndicatorDef[];
  setIndicators: (v: IndicatorDef[]) => void;
  entry: ConditionGroup;
  setEntry: (v: ConditionGroup) => void;
  exit: ConditionGroup;
  setExit: (v: ConditionGroup) => void;
}

export default function SignalBuilder({ indicators, setIndicators, entry, setEntry, exit, setExit }: Props) {
  const [modal, setModal] = useState<IndicatorDef | null>(null);

  const saveInd = (d: IndicatorDef) => {
    const exists = indicators.some((i) => i.id === d.id);
    setIndicators(exists ? indicators.map((i) => (i.id === d.id ? d : i)) : [...indicators, d]);
    setModal(null);
  };
  const delInd = (id: string) => setIndicators(indicators.filter((i) => i.id !== id));

  return (
    <div className="space-y-4">
      {/* Indicators */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-gray-400 uppercase tracking-widest">Indicators</span>
          <button type="button" onClick={() => setModal(defIndicator())}
            className="text-xs text-blue-400 hover:text-blue-300 font-medium">+ Add Indicator</button>
        </div>
        {indicators.length === 0 && <p className="text-[11px] text-gray-600">No indicators. Add EMA/RSI/Supertrend/MACD… then reference them in conditions.</p>}
        <div className="space-y-1.5">
          {indicators.map((d) => (
            <div key={d.id} className="flex items-center justify-between bg-gray-800/60 border border-gray-700/50 rounded-lg px-3 py-2">
              <div className="text-xs">
                <span className="font-semibold text-white">{d.name}</span>
                <span className="text-gray-500 ml-2">{d.type}</span>
                <span className="text-gray-600 ml-2">{summarise(d)} · {d.interval}m · {d.field}</span>
              </div>
              <div className="flex gap-2">
                <button type="button" onClick={() => setModal(d)} className="text-[11px] text-gray-400 hover:text-blue-300">Edit</button>
                <button type="button" onClick={() => delInd(d.id)} className="text-[11px] text-gray-600 hover:text-red-400">Delete</button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <Group title="Entry When" value={entry} onChange={setEntry} indicators={indicators} accent="text-green-400" />
      <Group title="Exit When" value={exit} onChange={setExit} indicators={indicators} accent="text-red-400" />

      {modal && <IndicatorModal initial={modal} onSave={saveInd} onClose={() => setModal(null)} />}
    </div>
  );
}

function summarise(d: IndicatorDef): string {
  switch (d.type) {
    case "MACD": return `${d.fast}/${d.slow}/${d.signal}`;
    case "SUPERTREND": return `${d.period}×${d.multiplier}`;
    case "BOLLINGER": return `${d.period}±${d.std}σ`;
    case "RANGE_BREAKOUT": return `${d.start_time}–${d.end_time}`;
    case "VWAP": case "CURRENT_CANDLE": return "";
    default: return `period ${d.period}`;
  }
}

// ---- Indicator modal ----
function IndicatorModal({ initial, onSave, onClose }: { initial: IndicatorDef; onSave: (d: IndicatorDef) => void; onClose: () => void }) {
  const [d, setD] = useState<IndicatorDef>(initial);
  const set = (p: Partial<IndicatorDef>) => setD({ ...d, ...p });
  const num = (k: keyof IndicatorDef, label: string, step = "1") => (
    <Field label={label}><input type="number" step={step} value={d[k] as number} onChange={(e) => set({ [k]: Number(e.target.value) } as Partial<IndicatorDef>)} className={inp + " w-full"} /></Field>
  );

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-gray-800 flex items-center justify-between">
          <h3 className="font-bold text-sm">Add Indicator</h3>
          <button type="button" onClick={onClose} className="text-gray-500 hover:text-gray-300">✕</button>
        </div>
        <div className="p-5 grid grid-cols-2 gap-3">
          <Field label="Indicator Type">
            <select value={d.type}
              onChange={(e) => {
                const ty = e.target.value as IndicatorType;
                // keep name in sync with type unless the user typed a custom one
                const wasDefault = !d.name || TYPES.some((t) => t.v.toLowerCase() === d.name.toLowerCase());
                set(wasDefault ? { type: ty, name: ty.toLowerCase() } : { type: ty });
              }}
              className={inp + " w-full"}>
              {TYPES.map((t) => <option key={t.v} value={t.v}>{t.label}</option>)}
            </select>
          </Field>
          <Field label="Name"><input value={d.name} onChange={(e) => set({ name: e.target.value })} className={inp + " w-full"} /></Field>

          {["SMA", "EMA", "RSI", "ATR", "SUPERTREND", "BOLLINGER"].includes(d.type) && num("period", "Period")}
          {d.type === "SUPERTREND" && num("multiplier", "Multiplier", "0.5")}
          {d.type === "BOLLINGER" && num("std", "Std Dev", "0.5")}
          {d.type === "MACD" && <>{num("fast", "Fast Period")}{num("slow", "Slow Period")}{num("signal", "Signal Period")}</>}
          {d.type === "RANGE_BREAKOUT" && <>
            <Field label="Start Time"><input type="time" value={d.start_time} onChange={(e) => set({ start_time: e.target.value })} className={inp + " w-full"} /></Field>
            <Field label="End Time"><input type="time" value={d.end_time} onChange={(e) => set({ end_time: e.target.value })} className={inp + " w-full"} /></Field>
          </>}

          <Field label="Candle Interval">
            <select value={d.interval} onChange={(e) => set({ interval: Number(e.target.value) })} className={inp + " w-full"}>
              {INTERVALS.map((m) => <option key={m} value={m}>{m} minutes</option>)}
            </select>
          </Field>
        </div>
        <div className="px-5 py-3 border-t border-gray-800 flex justify-end">
          <button type="button" onClick={() => onSave({ ...d, name: d.name.trim() || d.type.toLowerCase() })}
            className="px-5 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-bold">Save</button>
        </div>
      </div>
    </div>
  );
}

// ---- Condition group ----
function Group({ title, value, onChange, indicators, accent }: { title: string; value: ConditionGroup; onChange: (v: ConditionGroup) => void; indicators: IndicatorDef[]; accent: string }) {
  const set = (p: Partial<ConditionGroup>) => onChange({ ...value, ...p });
  const setCond = (i: number, c: Condition) => set({ conditions: value.conditions.map((x, j) => (j === i ? c : x)) });
  return (
    <div className="bg-gray-800/40 border border-gray-700/50 rounded-xl p-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className={`text-xs font-bold ${accent}`}>{title}</span>
        <div className="flex items-center gap-2">
          {value.conditions.length > 1 && (
            <select value={value.logic} onChange={(e) => set({ logic: e.target.value as "AND" | "OR" })}
              className="bg-gray-950 border border-gray-700 rounded px-2 py-1 text-[11px] text-gray-300">
              <option value="AND">ALL (AND)</option><option value="OR">ANY (OR)</option>
            </select>
          )}
          <button type="button" onClick={() => set({ conditions: [...value.conditions, defCondition()] })}
            className="text-[11px] text-blue-400 hover:text-blue-300">+ Condition</button>
        </div>
      </div>
      {value.conditions.length === 0 && <p className="text-[11px] text-gray-600">Is Empty — no {title.toLowerCase()} rule (uses fixed time).</p>}
      {value.conditions.map((c, i) => (
        <div key={i} className="flex items-center gap-1.5 flex-wrap">
          <OperandEditor op={c.lhs} onChange={(o) => setCond(i, { ...c, lhs: o })} indicators={indicators} />
          <select value={c.op} onChange={(e) => setCond(i, { ...c, op: e.target.value as CondOp })} className={inp}>
            {OPS.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
          </select>
          <OperandEditor op={c.rhs} onChange={(o) => setCond(i, { ...c, rhs: o })} indicators={indicators} />
          <button type="button" onClick={() => set({ conditions: value.conditions.filter((_, j) => j !== i) })}
            className="text-gray-600 hover:text-red-400 text-xs px-1">✕</button>
        </div>
      ))}
    </div>
  );
}

// ---- Operand editor ----
function OperandEditor({ op, onChange, indicators }: { op: Operand; onChange: (o: Operand) => void; indicators: IndicatorDef[] }) {
  const set = (p: Partial<Operand>) => onChange({ ...op, ...p });
  const indByName = indicators.find((i) => i.name === op.ref);
  const subs = indByName ? SUBS[indByName.type] : ["value"];
  return (
    <div className="flex items-center gap-1 bg-gray-950/60 border border-gray-700/50 rounded-lg px-1.5 py-1">
      <select value={op.kind}
        onChange={(e) => {
          const k = e.target.value as Operand["kind"];
          if (k === "indicator") {
            const first = indicators[0];
            set({ kind: k, ref: op.ref || first?.name || "", sub: first ? SUBS[first.type][0] : "value" });
          } else {
            set({ kind: k });
          }
        }}
        className="bg-gray-950 border border-gray-700 rounded px-1.5 py-1 text-[11px] text-gray-300">
        <option value="indicator">Indicator</option><option value="candle">Candle</option><option value="const">Value</option>
      </select>
      {op.kind === "indicator" && <>
        <select value={op.ref} onChange={(e) => set({ ref: e.target.value, sub: SUBS[(indicators.find((i) => i.name === e.target.value)?.type) ?? "EMA"][0] })} className={inp}>
          {indicators.length === 0 && <option value="">add an indicator first</option>}
          {indicators.map((i) => <option key={i.id} value={i.name}>{i.name}</option>)}
        </select>
        {subs.length > 1 && (
          <select value={op.sub} onChange={(e) => set({ sub: e.target.value })} className={inp}>
            {subs.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        )}
      </>}
      {op.kind === "candle" && (
        <select value={op.field} onChange={(e) => set({ field: e.target.value })} className={inp}>
          {CANDLE_FIELDS.map((f) => <option key={f.v} value={f.v}>{f.label}</option>)}
        </select>
      )}
      {op.kind === "const" && (
        <input type="number" step="any" value={op.value} onChange={(e) => set({ value: Number(e.target.value) })} className={inp + " w-20"} />
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="flex flex-col gap-1"><label className="text-[10px] uppercase tracking-wider text-gray-500">{label}</label>{children}</div>;
}

export const emptyGroup = (): ConditionGroup => ({ logic: "AND", conditions: [] });

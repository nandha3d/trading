import type { LegSpec } from "../types";

interface LegRow extends LegSpec {
  id: string;
}

interface LegBuilderProps {
  leg: LegRow;
  idx: number;
  onUpdate: (patch: Partial<LegSpec>) => void;
  onRemove: () => void;
  isRemovable: boolean;
}

const VALUE_LABEL: Record<string, string> = {
  ATM: "Offset (steps)",
  PREMIUM: "Target Premium ₹",
  DELTA: "Target Delta (0–1)",
};

export default function LegBuilder({ leg, idx, onUpdate, onRemove, isRemovable }: LegBuilderProps) {
  return (
    <div className="bg-gray-800/60 rounded-xl p-4 space-y-3 border border-gray-700/50 hover:border-gray-700 transition-colors">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-gray-300">Option Leg {idx + 1}</span>
        {isRemovable && (
          <button
            type="button"
            onClick={onRemove}
            className="text-[10px] text-gray-500 hover:text-red-400 transition-colors"
          >
            ✕ Remove
          </button>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2.5">
        <div>
          <label className="text-[10px] text-gray-400 block mb-1">Action</label>
          <div className="flex rounded-lg overflow-hidden border border-gray-700">
            {["BUY", "SELL"].map((a) => (
              <button
                key={a}
                type="button"
                onClick={() => onUpdate({ action: a as "BUY" | "SELL" })}
                className={`flex-1 py-1 text-xs font-medium transition-colors ${
                  leg.action === a
                    ? a === "SELL"
                      ? "bg-red-700 text-white"
                      : "bg-green-700 text-white"
                    : "bg-gray-900 text-gray-500 hover:text-gray-300"
                }`}
              >
                {a}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="text-[10px] text-gray-400 block mb-1">Option Type</label>
          <div className="flex rounded-lg overflow-hidden border border-gray-700">
            {["CE", "PE"].map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => onUpdate({ opt_type: t as "CE" | "PE" })}
                className={`flex-1 py-1 text-xs font-medium transition-colors ${
                  leg.opt_type === t ? "bg-blue-600 text-white" : "bg-gray-900 text-gray-500 hover:text-gray-300"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <div>
          <label className="text-[10px] text-gray-400 block mb-1">Selection</label>
          <select
            value={leg.selection}
            onChange={(e) => onUpdate({ selection: e.target.value as LegSpec["selection"] })}
            className="w-full bg-gray-950 border border-gray-700 rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
          >
            <option value="ATM">ATM</option>
            <option value="PREMIUM">Premium</option>
            <option value="DELTA">Delta</option>
          </select>
        </div>

        <div className="col-span-2">
          <label className="text-[10px] text-gray-400 block mb-1">{VALUE_LABEL[leg.selection]}</label>
          <input
            type="number"
            step={leg.selection === "DELTA" ? "0.01" : "1"}
            value={leg.value}
            onChange={(e) => onUpdate({ value: Number(e.target.value) })}
            className="w-full bg-gray-950 border border-gray-700 rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
          />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2.5 pt-1">
        <div>
          <label className="text-[10px] text-gray-400 block mb-1">Lots</label>
          <input
            type="number"
            min={1}
            value={leg.lots}
            onChange={(e) => onUpdate({ lots: Number(e.target.value) })}
            className="w-full bg-gray-950 border border-gray-700 rounded-lg px-2 py-1 text-xs text-white focus:outline-none focus:border-blue-500"
          />
        </div>

        <div>
          <label className="text-[10px] text-gray-400 block mb-1">SL %</label>
          <input
            type="number"
            min={0}
            placeholder="None"
            value={leg.sl_pct ?? ""}
            onChange={(e) => onUpdate({ sl_pct: e.target.value ? Number(e.target.value) : null })}
            className="w-full bg-gray-950 border border-gray-700 rounded-lg px-2 py-1 text-xs text-white placeholder-gray-800 focus:outline-none focus:border-blue-500"
          />
        </div>

        <div>
          <label className="text-[10px] text-gray-400 block mb-1">TP %</label>
          <input
            type="number"
            min={0}
            placeholder="None"
            value={leg.tp_pct ?? ""}
            onChange={(e) => onUpdate({ tp_pct: e.target.value ? Number(e.target.value) : null })}
            className="w-full bg-gray-950 border border-gray-700 rounded-lg px-2 py-1 text-xs text-white placeholder-gray-800 focus:outline-none focus:border-blue-500"
          />
        </div>
      </div>
    </div>
  );
}

import type { SavedStrategy } from "../types";

interface SavedStrategiesPanelProps {
  strategies: SavedStrategy[];
  onLoad: (strategy: SavedStrategy) => void;
  onDelete: (id: string) => void;
  onClone: (id: string) => void;
}

export default function SavedStrategiesPanel({
  strategies,
  onLoad,
  onDelete,
  onClone,
}: SavedStrategiesPanelProps) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 h-full space-y-4">
      <div className="flex items-center justify-between border-b border-gray-800 pb-2">
        <span className="text-xs font-bold uppercase tracking-wider text-gray-300">Saved Workspace Strategies</span>
        <span className="text-[10px] text-gray-500 font-mono">{strategies.length} strategies</span>
      </div>

      {strategies.length === 0 ? (
        <div className="text-xs text-gray-500 py-8 text-center select-none">
          No saved strategies in this workspace. Create one in Strategy Builder!
        </div>
      ) : (
        <div className="space-y-3.5 max-h-[300px] overflow-y-auto pr-1">
          {strategies.map((st) => (
            <div
              key={st.id}
              className="bg-gray-950/40 border border-gray-800/80 rounded-xl p-3 hover:border-gray-750 transition-all space-y-2.5"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <h4 className="text-xs font-bold text-white truncate">{st.name}</h4>
                  <span className="text-[10px] text-gray-500 uppercase tracking-wide block mt-0.5">
                    {st.underlying} · Expiry {st.expiry}
                  </span>
                </div>
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  <button
                    type="button"
                    onClick={() => onLoad(st)}
                    className="px-2 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded text-[10px] font-bold transition-colors"
                  >
                    Load
                  </button>
                  <button
                    type="button"
                    onClick={() => onClone(st.id)}
                    className="px-2 py-1 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded text-[10px] font-bold transition-colors"
                  >
                    Clone
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(st.id)}
                    className="px-2 py-1 bg-gray-900 hover:bg-red-950/40 hover:text-red-400 text-gray-500 rounded text-[10px] font-bold transition-colors"
                  >
                    Delete
                  </button>
                </div>
              </div>

              {/* Legs summary */}
              <div className="flex flex-wrap gap-1.5 pt-1.5 border-t border-gray-900">
                {st.legs.map((leg, lIdx) => {
                  const isSell = leg.action === "SELL";
                  return (
                    <span
                      key={lIdx}
                      className={`text-[9px] px-1.5 py-0.5 rounded font-mono font-bold ${
                        isSell ? "bg-red-950/30 text-red-400" : "bg-green-950/30 text-green-400"
                      }`}
                    >
                      {leg.action} {leg.opt_type} {leg.strike}
                    </span>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

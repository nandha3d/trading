

interface Level {
  level: number;
  type: string;
  source: string;
  strength: number;
}

interface SupportResistancePanelProps {
  levels: Level[];
}

export default function SupportResistancePanel({ levels }: SupportResistancePanelProps) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 h-full">
      <div className="flex items-center justify-between border-b border-gray-800 pb-2 mb-3">
        <span className="text-[10px] font-bold uppercase tracking-wider text-gray-400">Key S/R Levels</span>
        <span className="text-[10px] text-gray-500">Auto-calculated</span>
      </div>

      {levels.length === 0 ? (
        <div className="text-xs text-gray-500 py-6 text-center">No levels loaded</div>
      ) : (
        <div className="space-y-2 max-h-[170px] overflow-y-auto pr-1">
          {levels.map((lv, idx) => {
            const isSup = lv.type === "SUPPORT";
            return (
              <div
                key={idx}
                className="flex items-center justify-between bg-gray-950/40 border border-gray-800/50 rounded-lg p-2 hover:border-gray-700/60 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`text-[9px] px-1.5 py-0.5 rounded font-bold ${
                      isSup ? "bg-emerald-950/60 text-emerald-400" : "bg-rose-950/60 text-rose-400"
                    }`}
                  >
                    {isSup ? "SUP" : "RES"}
                  </span>
                  <span className="text-xs font-mono font-bold text-gray-200">
                    {lv.level.toLocaleString()}
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-[10px] text-gray-500 uppercase tracking-tight">
                    {lv.source.replace("_", " ")}
                  </span>
                  <div className="flex gap-0.5">
                    {Array.from({ length: 3 }).map((_, i) => (
                      <span
                        key={i}
                        className={`w-1 h-2 rounded-sm ${
                          i < Math.ceil(lv.strength / 3)
                            ? isSup
                              ? "bg-emerald-500"
                              : "bg-rose-500"
                            : "bg-gray-800"
                        }`}
                      />
                    ))}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}



interface Alert {
  code: string;
  severity: string;
  message: string;
  timestamp: string;
}

interface MarketAlertsPanelProps {
  alerts: Alert[];
}

export default function MarketAlertsPanel({ alerts }: MarketAlertsPanelProps) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 h-full">
      <div className="flex items-center justify-between border-b border-gray-800 pb-2 mb-3">
        <span className="text-[10px] font-bold uppercase tracking-wider text-gray-400">Technical Alerts</span>
        <span className="text-[10px] text-gray-500">Intraday triggers</span>
      </div>

      {alerts.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-8 text-center text-gray-500">
          <span className="text-xl mb-1.5 opacity-40">🔔</span>
          <p className="text-xs">No alerts triggered yet</p>
        </div>
      ) : (
        <div className="space-y-2 max-h-[170px] overflow-y-auto pr-1">
          {alerts.map((al, idx) => {
            const isHigh = al.severity === "HIGH";
            const isMed = al.severity === "MEDIUM";
            return (
              <div
                key={idx}
                className={`flex gap-2.5 rounded-lg p-2.5 border transition-colors ${
                  isHigh
                    ? "bg-rose-950/20 border-rose-900/40"
                    : isMed
                    ? "bg-amber-950/20 border-amber-900/40"
                    : "bg-blue-950/20 border-blue-900/40"
                }`}
              >
                <span className="text-sm select-none">
                  {isHigh ? "🚨" : isMed ? "⚠️" : "ℹ️"}
                </span>
                <div className="flex-1">
                  <div className="flex items-center justify-between">
                    <span
                      className={`text-[9px] font-bold uppercase ${
                        isHigh ? "text-rose-400" : isMed ? "text-amber-400" : "text-blue-400"
                      }`}
                    >
                      {al.code.replace("_", " ")}
                    </span>
                    <span className="text-[9px] text-gray-500">
                      {al.timestamp.slice(11, 19)}
                    </span>
                  </div>
                  <p className="text-xs text-gray-300 mt-1 leading-normal">
                    {al.message}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

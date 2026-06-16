import type { TradeResult } from "../types";

interface Props {
  trade: TradeResult | null;
  onClose: () => void;
}

const INR = (n: number) => {
  const s = Math.abs(n).toLocaleString("en-IN", { maximumFractionDigits: 0 });
  return `${n < 0 ? "-" : "+"}₹${s}`;
};

function ExitBadge({ reason }: { reason: string }) {
  if (!reason || reason === "TIME")
    return <span className="px-1.5 py-0.5 rounded text-[10px] bg-gray-800 text-gray-500">Time</span>;
  if (reason === "TARGET")
    return <span className="px-1.5 py-0.5 rounded text-[10px] bg-green-900/50 text-green-400">Target ✓</span>;
  if (reason === "STOPLOSS")
    return <span className="px-1.5 py-0.5 rounded text-[10px] bg-red-900/50 text-red-400">SL Hit</span>;
  if (reason === "TRAIL")
    return <span className="px-1.5 py-0.5 rounded text-[10px] bg-yellow-900/50 text-yellow-400">Trail SL</span>;
  return <span className="px-1.5 py-0.5 rounded text-[10px] bg-gray-800 text-gray-400">{reason}</span>;
}

export default function TradeDrawer({ trade, onClose }: Props) {
  if (!trade) return null;

  return (
    <>
      <div className="fixed inset-0 bg-black/50 z-40" onClick={onClose} />
      <div className="fixed right-0 top-0 h-screen w-[420px] bg-gray-900 border-l border-gray-800 z-50 overflow-y-auto">
        <div className="p-6 space-y-5">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-white">Trade Detail</h2>
              <p className="text-xs text-gray-500 mt-0.5">{trade.day}</p>
            </div>
            <button onClick={onClose}
              className="w-8 h-8 rounded-lg bg-gray-800 hover:bg-gray-700 flex items-center justify-center text-gray-400 hover:text-white transition-colors">
              ✕
            </button>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            <ExitBadge reason={trade.exit_reason} />
            {trade.entry_spot > 0 && (
              <span className="text-xs text-gray-500">
                Spot: <span className="text-gray-300 font-mono">{trade.entry_spot.toLocaleString("en-IN")}</span>
              </span>
            )}
            {trade.skip_reason && (
              <span className="text-xs text-yellow-500 bg-yellow-900/20 px-2 py-0.5 rounded">
                Skipped: {trade.skip_reason}
              </span>
            )}
          </div>

          {trade.legs.length > 0 && (
            <div className="space-y-2">
              <h3 className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest">Legs</h3>
              {trade.legs.map((leg, i) => {
                const sign = leg.action === "SELL" ? 1 : -1;
                const legPnl = sign * (leg.entry - leg.exit) * leg.qty;
                return (
                  <div key={i} className="bg-gray-800/60 rounded-xl p-3 border border-gray-700/50 space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${leg.action === "SELL" ? "bg-red-900/50 text-red-400" : "bg-green-900/50 text-green-400"}`}>
                          {leg.action}
                        </span>
                        <span className="text-xs font-mono text-white">{leg.strike}</span>
                      </div>
                      <ExitBadge reason={leg.exit_reason} />
                    </div>
                    <div className="grid grid-cols-3 gap-2 text-[11px]">
                      <div><span className="text-gray-600">Entry</span><div className="font-mono text-gray-300">₹{leg.entry.toFixed(1)}</div></div>
                      <div><span className="text-gray-600">Exit</span><div className="font-mono text-gray-300">₹{leg.exit.toFixed(1)}</div></div>
                      <div><span className="text-gray-600">Qty</span><div className="font-mono text-gray-300">{leg.qty}</div></div>
                    </div>
                    <div className={`text-xs font-semibold font-mono ${legPnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {INR(legPnl)}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {trade.legs.length > 0 && (
            <div className="bg-gray-800/40 rounded-xl p-4 border border-gray-700/40 space-y-2">
              <h3 className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest">Summary</h3>
              {[
                { label: "Gross P&L", val: trade.gross, cls: trade.gross >= 0 ? "text-green-400" : "text-red-400" },
                { label: "Charges", val: -trade.cost, cls: "text-orange-400" },
                { label: "Net P&L", val: trade.net, cls: trade.net >= 0 ? "text-green-400" : "text-red-400" },
              ].map(({ label, val, cls }) => (
                <div key={label} className="flex justify-between items-center">
                  <span className="text-xs text-gray-500">{label}</span>
                  <span className={`text-sm font-bold font-mono ${cls}`}>{INR(val)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

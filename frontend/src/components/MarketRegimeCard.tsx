

interface MarketRegimeCardProps {
  regime: string;
}

export default function MarketRegimeCard({ regime }: MarketRegimeCardProps) {
  const REGIMES: Record<string, { label: string; desc: string; color: string; bg: string; border: string }> = {
    BULLISH_TREND: {
      label: "Bullish Trend",
      desc: "Prices are rising consistently. Moving averages show long alignment. Ideal for CE buying or PE selling.",
      color: "text-emerald-400",
      bg: "bg-emerald-950/30",
      border: "border-emerald-800/50"
    },
    BEARISH_TREND: {
      label: "Bearish Trend",
      desc: "Prices are falling consistently. Moving averages show short alignment. Ideal for PE buying or CE selling.",
      color: "text-rose-400",
      bg: "bg-rose-950/30",
      border: "border-rose-800/50"
    },
    SIDEWAYS: {
      label: "Sideways / Rangebound",
      desc: "Price is oscillating in a tight range. Best suited for range-bound option selling strategies like Straddles/Strangles.",
      color: "text-blue-400",
      bg: "bg-blue-950/30",
      border: "border-blue-800/50"
    },
    VOLATILE: {
      label: "High Volatility",
      desc: "Wide price fluctuations. IV/VIX is elevated. High risk of stop loss hits. Consider hedging or sitting out.",
      color: "text-amber-400",
      bg: "bg-amber-950/30",
      border: "border-amber-800/50"
    },
    LOW_VOLATILITY: {
      label: "Low Volatility / Compression",
      desc: "Extremely quiet market. Premium decay is slow. Watch for sudden expansion/breakouts.",
      color: "text-violet-400",
      bg: "bg-violet-950/30",
      border: "border-violet-800/50"
    }
  };

  const current = REGIMES[regime] ?? {
    label: regime,
    desc: "Detecting current market state and trend direction...",
    color: "text-gray-400",
    bg: "bg-gray-900/50",
    border: "border-gray-800"
  };

  return (
    <div className={`border rounded-xl p-4 h-full flex flex-col justify-between transition-all duration-300 ${current.bg} ${current.border}`}>
      <div>
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-bold uppercase tracking-wider text-gray-400">Market Regime</span>
          <span className="flex h-2 w-2 relative">
            <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${current.color.replace("text-", "bg-")}`}></span>
            <span className={`relative inline-flex rounded-full h-2 w-2 ${current.color.replace("text-", "bg-")}`}></span>
          </span>
        </div>
        <h3 className={`text-lg font-extrabold mt-1.5 tracking-tight ${current.color}`}>
          {current.label}
        </h3>
        <p className="text-xs text-gray-400 mt-2 leading-relaxed">
          {current.desc}
        </p>
      </div>
      <div className="text-[10px] text-gray-500 mt-3 pt-3 border-t border-gray-800/60">
        Computed from spot and volume momentum (30m)
      </div>
    </div>
  );
}

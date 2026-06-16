/**
 * Share-market themed backtest loader. Pure CSS (no deps) — animated
 * candlestick/bar chart with a sweeping trend line. Shown centre-stage while
 * a backtest is calculating.
 */
export default function BacktestLoader() {
  const bars = [
    { h: 38, up: true }, { h: 60, up: true }, { h: 30, up: false },
    { h: 72, up: true }, { h: 50, up: false }, { h: 84, up: true },
    { h: 46, up: false }, { h: 66, up: true },
  ];
  return (
    <div className="h-full flex flex-col items-center justify-center select-none">
      <style>{`
        @keyframes bt-bar { 0%,100% { transform: scaleY(.35); } 50% { transform: scaleY(1); } }
        @keyframes bt-dash { to { stroke-dashoffset: 0; } }
        @keyframes bt-pulse { 0%,100% { opacity:.4 } 50% { opacity:1 } }
      `}</style>

      <div className="relative w-64 h-40">
        {/* trend line */}
        <svg viewBox="0 0 256 160" className="absolute inset-0 w-full h-full" preserveAspectRatio="none">
          <polyline
            points="0,120 36,96 72,108 108,60 144,80 180,36 216,64 256,28"
            fill="none" stroke="#3b82f6" strokeWidth="2.5"
            strokeLinecap="round" strokeLinejoin="round"
            strokeDasharray="520" strokeDashoffset="520"
            style={{ animation: "bt-dash 2s ease-in-out infinite alternate" }}
          />
        </svg>
        {/* bars */}
        <div className="absolute inset-0 flex items-end justify-between gap-2 px-1">
          {bars.map((b, i) => (
            <div
              key={i}
              className={`w-5 rounded-t origin-bottom ${b.up ? "bg-emerald-500/80" : "bg-rose-500/80"}`}
              style={{ height: `${b.h}%`, animation: `bt-bar 1.1s ease-in-out ${i * 0.12}s infinite` }}
            />
          ))}
        </div>
      </div>

      <div className="mt-6 text-sm font-semibold text-gray-300" style={{ animation: "bt-pulse 1.4s ease-in-out infinite" }}>
        Calculating backtest…
      </div>
      <div className="mt-1 text-xs text-gray-600 font-mono">crunching ticks · resolving strikes · evaluating signals</div>
    </div>
  );
}

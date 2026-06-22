import { useState, useEffect } from "react";
import StrategyBuilder from "./components/StrategyBuilder";
import ResultsPanel from "./components/ResultsPanel";
import OptionsChain from "./components/OptionsChain";
import FlowMatrix from "./components/FlowMatrix";
import BacktestLoader from "./components/BacktestLoader";
import GridSweep from "./components/GridSweep";
import { getStatus } from "./api";
import type { BacktestResponse, DbStatus } from "./types";

type Tab = "oi-matrix" | "backtest" | "sweep" | "chain";

function fmtM(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return String(n);
}

const TABS: { id: Tab; label: string }[] = [
  { id: "oi-matrix", label: "OI Matrix" },
  { id: "backtest", label: "Backtest" },
  { id: "sweep", label: "Auto Sweep" },
  { id: "chain", label: "Trade Simulator" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>(
    () => (localStorage.getItem("ob_tab") as Tab) ?? "oi-matrix"
  );
  const [result, setResult] = useState<BacktestResponse | null>(null);
  const [status, setStatus] = useState<DbStatus | null>(null);
  const [btLoading, setBtLoading] = useState(false);

  useEffect(() => {
    getStatus().then(setStatus).catch(() => null);
  }, []);

  const opts = status?.options_1m;

  return (
    <div className="flex flex-col h-screen bg-gray-950 text-gray-100 overflow-hidden">
      <header className="flex items-center justify-between px-6 py-3 border-b border-gray-800 bg-gray-900 flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center font-bold text-sm">
            OB
          </div>
          <span className="font-semibold text-lg">Options Backtest</span>
          <span className="text-gray-500 text-sm hidden sm:block">NSE · NIFTY + BANKNIFTY</span>
          <div className="h-5 w-[1px] bg-gray-800 mx-1" />
          <div className="flex bg-gray-950 rounded-lg p-0.5 border border-gray-800">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => { setTab(t.id); localStorage.setItem("ob_tab", t.id); }}
                className={`px-3 py-1 rounded-md text-xs font-semibold transition-colors ${
                  tab === t.id ? "bg-blue-600 text-white" : "text-gray-400 hover:text-gray-200"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
        {opts ? (
          <div className="flex items-center gap-4 text-xs text-gray-400">
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-green-500 inline-block" />
              {fmtM(opts.rows)} option rows
            </span>
            <span className="hidden md:block">
              NIFTY {fmtM(opts.by_underlying?.NIFTY ?? 0)} ·
              BANKNIFTY {fmtM(opts.by_underlying?.BANKNIFTY ?? 0)}
            </span>
            <span className="text-gray-600 hidden lg:block">
              {opts.ts_min?.slice(0, 10)} → {opts.ts_max?.slice(0, 10)}
            </span>
          </div>
        ) : (
          <span className="text-xs text-gray-600">connecting…</span>
        )}
      </header>

      {/* All tabs stay mounted — only visibility toggles. State (legs, payoff, WS) survives navigation. */}
      <div className={`flex-1 overflow-y-auto p-6 bg-gray-950 ${tab !== "oi-matrix" ? "hidden" : ""}`}>
        <FlowMatrix isActive={tab === "oi-matrix"} />
      </div>

      <div className={`flex flex-1 overflow-hidden ${tab !== "backtest" ? "hidden" : ""}`}>
        <aside className="w-[380px] flex-shrink-0 border-r border-gray-800 overflow-y-auto bg-gray-900">
          <StrategyBuilder onResult={setResult} onLoading={setBtLoading} />
        </aside>
        <main className="flex-1 overflow-y-auto p-6">
          {btLoading ? (
            <BacktestLoader />
          ) : result ? (
            <ResultsPanel result={result} />
          ) : (
            <div className="h-full flex flex-col items-center justify-center text-gray-600 select-none">
              <div className="text-7xl mb-5 opacity-30">📈</div>
              <p className="text-base font-medium text-gray-500">Configure strategy and run backtest</p>
              <p className="text-sm mt-1 text-gray-600">Results will appear here</p>
            </div>
          )}
        </main>
      </div>

      <div className={`flex-1 overflow-y-auto p-6 bg-gray-950 ${tab !== "sweep" ? "hidden" : ""}`}>
        <GridSweep />
      </div>
      <div className={`flex-1 overflow-y-auto p-6 bg-gray-950 ${tab !== "chain" ? "hidden" : ""}`}>
        <OptionsChain isActive={tab === "chain"} />
      </div>
    </div>
  );
}

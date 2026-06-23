import { useState } from "react";
import { detectOiStrategySignal, runOiStrategyBacktest } from "../api";
import type { OiStrategyBacktestResponse, OiStrategySignalResponse } from "../types";

interface Props {
  underlying: string;
  defaultDate: string;
  onLoadSuggested: (signal: OiStrategySignalResponse) => void;
}

const rowCls = "flex items-center justify-between gap-3 text-[10px] py-1 border-b border-gray-900 last:border-0";
const metricCls = "bg-gray-900/70 rounded-lg p-2 min-w-0";
const sectionCls = "bg-gray-900/40 rounded-xl px-2 py-2 space-y-1";

function HelpBox({ title, children }: { title: string; children: string }) {
  return (
    <div className="text-[10px] leading-relaxed text-sky-200 bg-sky-950/20 border border-sky-900/60 rounded-lg px-2 py-1.5">
      <span className="font-bold text-sky-300">{title}: </span>{children}
    </div>
  );
}

export default function OiStrategyPanel({ underlying, defaultDate, onLoadSuggested }: Props) {
  const [date, setDate] = useState(defaultDate);
  const [time, setTime] = useState("");
  const [expiry, setExpiry] = useState("");
  const [interval, setInterval] = useState(5);
  const [loading, setLoading] = useState(false);
  const [btLoading, setBtLoading] = useState(false);
  const [result, setResult] = useState<OiStrategySignalResponse | null>(null);
  const [backtest, setBacktest] = useState<OiStrategyBacktestResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [btStart, setBtStart] = useState(defaultDate);
  const [btEnd, setBtEnd] = useState(defaultDate);

  const setSignalDate = (nextDate: string) => {
    setDate(nextDate);
    if (btStart === date) setBtStart(nextDate);
    if (btEnd === date) setBtEnd(nextDate);
  };

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const timestamp = time ? `${date}T${time}` : null;
      const res = await detectOiStrategySignal({
        underlying,
        date,
        timestamp,
        expiry: expiry || null,
        interval,
        mode: "historical",
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const runBacktest = async () => {
    setBtLoading(true);
    setError(null);
    try {
      const res = await runOiStrategyBacktest({
        underlying,
        start: btStart,
        end: btEnd,
        interval,
        mode: "historical",
      });
      setBacktest(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBacktest(null);
    } finally {
      setBtLoading(false);
    }
  };

  const fmt = (n: number) =>
    n.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 0 });
  const pct = (n: number) =>
    `${n.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 0 })}%`;
  const getNum = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? value : 0;
  const factors = result?.factor_scores?.length ? result.factor_scores : result?.score_breakdown ?? [];
  const download = (name: string, content: string, type: string) => {
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  };
  const exportResearchJson = () => {
    if (!backtest) return;
    download(`oi-strategy-research-${btStart}-${btEnd}.json`, JSON.stringify(backtest, null, 2), "application/json");
  };
  const exportJournalCsv = () => {
    if (!backtest) return;
    const rows = [
      ["day", "timestamp", "action", "signal_type", "score", "wall_strike", "entry_price", "exit_price", "net_pnl", "exit_reason", "regime"],
      ...backtest.trade_journal.map((j) => [
        j.day ?? "", j.timestamp ?? "", j.action ?? "", j.signal_type ?? "", j.score ?? "", j.wall_strike ?? "",
        j.entry_price ?? "", j.exit_price ?? "", j.net_pnl ?? "", j.exit_reason ?? "", j.regime ?? "",
      ]),
    ];
    download(`oi-strategy-journal-${btStart}-${btEnd}.csv`, rows.map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n"), "text/csv");
  };

  const headline = result?.signal_type === "BUY_CE"
    ? "Bullish OI setup detected"
    : result?.signal_type === "BUY_PE"
      ? "Bearish OI setup detected"
      : "No-trade: confirmation missing";

  return (
    <div className="space-y-3 bg-gray-950/40 border border-gray-800 rounded-xl p-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold text-gray-300">OI Strategy</div>
          <div className="text-[10px] text-gray-500 mt-0.5">
            One OI workflow for setup detection and research scanning. Score shows rule confluence, not profit probability.
          </div>
        </div>
        {result && (
          <span className={`text-[10px] px-2 py-1 rounded-lg font-bold ${
            result.signal_type === "NO_TRADE" ? "bg-gray-900 text-gray-400" : "bg-emerald-900/40 text-emerald-300"
          }`}>
            {result.score}/100
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <label className="space-y-1">
          <span className="text-[10px] text-gray-500">Date</span>
          <input
            type="date"
            value={date}
            onChange={(e) => setSignalDate(e.target.value)}
            className="w-full bg-gray-950 border border-gray-800 rounded-lg px-2 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
          />
        </label>
        <label className="space-y-1">
          <span className="text-[10px] text-gray-500">Time optional</span>
          <input
            type="time"
            value={time}
            onChange={(e) => setTime(e.target.value)}
            className="w-full bg-gray-950 border border-gray-800 rounded-lg px-2 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
          />
        </label>
        <label className="space-y-1">
          <span className="text-[10px] text-gray-500">Expiry optional</span>
          <input
            type="date"
            value={expiry}
            onChange={(e) => setExpiry(e.target.value)}
            className="w-full bg-gray-950 border border-gray-800 rounded-lg px-2 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
          />
        </label>
        <label className="space-y-1">
          <span className="text-[10px] text-gray-500">Interval</span>
          <select
            value={interval}
            onChange={(e) => setInterval(Number(e.target.value))}
            className="w-full bg-gray-950 border border-gray-800 rounded-lg px-2 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
          >
            <option value={3}>3 min</option>
            <option value={5}>5 min</option>
            <option value={15}>15 min</option>
          </select>
        </label>
      </div>

      <button
        type="button"
        onClick={run}
        disabled={loading}
        className="w-full py-2 rounded-lg bg-cyan-700 hover:bg-cyan-600 disabled:bg-gray-900 disabled:text-gray-600 text-white text-xs font-bold transition-colors"
      >
        {loading ? "Detecting OI setup..." : "Detect OI Setup"}
      </button>

      <HelpBox title="How this connects">
        Detect Setup finds one OI signal and can load its BUY CE/PE leg into the normal Strategy Builder. The main Run Backtest then tests those legs with your selected indicators. The research scan below is the OI-gated backtest that checks every candle.
      </HelpBox>

      {error && (
        <div className="text-[10px] text-red-300 bg-red-950/30 border border-red-900 rounded-lg px-2 py-1.5">
          {error}
        </div>
      )}

      {result && (
        <div className="space-y-3">
          <div className="bg-gray-900/70 border border-gray-800 rounded-xl p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-bold text-white">{headline}</div>
              <span className="text-[10px] text-gray-500">{result.strength}</span>
            </div>
            <div className="text-[10px] text-gray-500 mt-1">
              {result.timestamp ? result.timestamp.replace("T", " ").slice(0, 16) : date}
              {result.expiry ? ` | Exp ${result.expiry}` : ""}
              {result.atm_strike ? ` | ATM ${result.atm_strike}` : ""}
            </div>
          </div>

          {result.reasons.length > 0 && (
            <div>
              <div className="text-[10px] uppercase font-bold text-emerald-400 mb-1">Reasons</div>
              <ul className="space-y-1">
                {result.reasons.map((r) => (
                  <li key={r} className="text-[10px] text-gray-300 bg-gray-900/50 rounded-lg px-2 py-1">{r}</li>
                ))}
              </ul>
            </div>
          )}

          {result.no_trade_reasons.length > 0 && (
            <div>
              <div className="text-[10px] uppercase font-bold text-amber-400 mb-1">No-trade reasons</div>
              <ul className="space-y-1">
                {result.no_trade_reasons.map((r) => (
                  <li key={r} className="text-[10px] text-gray-300 bg-gray-900/50 rounded-lg px-2 py-1">{r}</li>
                ))}
              </ul>
            </div>
          )}

          <HelpBox title="How to read the factor score">
            The score is a checklist of market confirmations such as OI unwinding, VWAP, PCR, volume, trend, and time risk. It is not a profit probability.
          </HelpBox>

          <div className="bg-gray-900/40 rounded-xl px-2">
            {factors.map((s) => (
              <div key={s.label} className={rowCls}>
                <span className={s.passed ? "text-gray-300" : "text-gray-600"}>
                  {s.label}
                  {s.available === false && <span className="text-amber-500"> unavailable</span>}
                </span>
                <span className={s.passed ? "text-emerald-300" : "text-gray-600"}>{s.points}/{s.max_points}</span>
              </div>
            ))}
          </div>
          {result.factor_coverage && (
            <div className="text-[10px] text-gray-500">
              Factor coverage: {String(result.factor_coverage.coverage_percent ?? "0")}%
              {result.regime ? ` | Regime ${result.regime}` : ""}
            </div>
          )}

          <div className="text-[10px] text-gray-500 leading-relaxed">
            Data caveat: IV rank/skew, futures OI, event calendar, F&O ban, and real bid/ask are marked unavailable when the feed does not provide them.
          </div>

          {result.suggested_legs.length > 0 && (
            <div className="space-y-1.5">
              <button
                type="button"
                onClick={() => onLoadSuggested(result)}
                className="w-full py-2 rounded-lg bg-emerald-700 hover:bg-emerald-600 text-white text-xs font-bold transition-colors"
              >
                Load Suggested BUY {result.suggested_legs[0].opt_type} Leg
              </button>
              <div className="text-[10px] text-gray-500 leading-relaxed">
                After loading, use the main Run Backtest button to test this leg with your selected indicators, SL, target, entry rules, and exit rules.
              </div>
            </div>
          )}
        </div>
      )}

      <div className="border-t border-gray-800 pt-3 space-y-3">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-widest text-gray-500">Research scan range</div>
          <div className="text-[10px] text-gray-500 mt-0.5">
            Scans every {interval}-minute candle, enters valid BUY CE/PE setups, and exits by SL, target, trailing SL, or time.
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <label className="space-y-1">
            <span className="text-[10px] text-gray-500">Start</span>
            <input
              type="date"
              value={btStart}
              onChange={(e) => setBtStart(e.target.value)}
              className="w-full bg-gray-950 border border-gray-800 rounded-lg px-2 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
            />
          </label>
          <label className="space-y-1">
            <span className="text-[10px] text-gray-500">End</span>
            <input
              type="date"
              value={btEnd}
              onChange={(e) => setBtEnd(e.target.value)}
              className="w-full bg-gray-950 border border-gray-800 rounded-lg px-2 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
            />
          </label>
        </div>

        <button
          type="button"
          onClick={runBacktest}
          disabled={btLoading}
          className="w-full py-2 rounded-lg bg-indigo-700 hover:bg-indigo-600 disabled:bg-gray-900 disabled:text-gray-600 text-white text-xs font-bold transition-colors"
        >
          {btLoading ? "Scanning OI setups..." : "Run OI Research Scan"}
        </button>

        {backtest && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <div className={metricCls}>
                <div className="text-[9px] uppercase text-gray-500 font-bold">Net P&L</div>
                <div className={backtest.stats.net_pnl >= 0 ? "text-emerald-300 text-sm font-bold" : "text-red-300 text-sm font-bold"}>
                  {fmt(backtest.stats.net_pnl)}
                </div>
              </div>
              <div className={metricCls}>
                <div className="text-[9px] uppercase text-gray-500 font-bold">Win Rate</div>
                <div className="text-white text-sm font-bold">{fmt(backtest.stats.win_rate)}%</div>
              </div>
              <div className={metricCls}>
                <div className="text-[9px] uppercase text-gray-500 font-bold">Trades</div>
                <div className="text-white text-sm font-bold">{backtest.stats.trades}</div>
              </div>
              <div className={metricCls}>
                <div className="text-[9px] uppercase text-gray-500 font-bold">Max DD</div>
                <div className="text-amber-300 text-sm font-bold">{fmt(backtest.stats.max_drawdown)}</div>
              </div>
              <div className={metricCls}>
                <div className="text-[9px] uppercase text-gray-500 font-bold">Sharpe</div>
                <div className="text-white text-sm font-bold">{fmt(backtest.stats.sharpe ?? 0)}</div>
              </div>
              <div className={metricCls}>
                <div className="text-[9px] uppercase text-gray-500 font-bold">Baseline Delta</div>
                <div className={(backtest.baseline_comparison?.net_pnl_delta ?? 0) >= 0 ? "text-emerald-300 text-sm font-bold" : "text-red-300 text-sm font-bold"}>
                  {fmt(backtest.baseline_comparison?.net_pnl_delta ?? 0)}
                </div>
              </div>
            </div>

            <HelpBox title="Main metrics">
              Net P&L is after modeled costs, win rate shows how often trades finished positive, max DD is the worst peak-to-trough pain, Sharpe is risk-adjusted return, and baseline delta shows whether the OI filter beat a naive ATM option buyer.
            </HelpBox>

            {backtest.sample_size_warning?.message && (
              <div className="text-[10px] leading-relaxed text-amber-200 bg-amber-950/30 border border-amber-800 rounded-lg px-2 py-1.5">
                <span className="font-bold text-amber-300">Sample size warning: </span>
                {String(backtest.sample_size_warning.message)}
              </div>
            )}

            {backtest.baseline_comparison?.stats && (
              <div className={sectionCls}>
                <div className="text-[9px] uppercase text-gray-500 font-bold">Baseline Comparison</div>
                <HelpBox title="Why this matters">
                  This checks whether the OI filter improves on simply buying the same ATM CE/PE candidates. If the baseline is better, the filter may be removing good trades.
                </HelpBox>
                <div className={rowCls}>
                  <span className="text-gray-400">Baseline net P&L</span>
                  <span className={getNum(backtest.baseline_comparison.stats.net_pnl) >= 0 ? "text-emerald-300" : "text-red-300"}>{fmt(getNum(backtest.baseline_comparison.stats.net_pnl))}</span>
                </div>
                <div className={rowCls}>
                  <span className="text-gray-400">Baseline win rate</span>
                  <span className="text-gray-300">{pct(getNum(backtest.baseline_comparison.stats.win_rate))}</span>
                </div>
                <div className={rowCls}>
                  <span className="text-gray-400">Baseline MDD</span>
                  <span className="text-amber-300">{fmt(getNum(backtest.baseline_comparison.stats.max_drawdown))}</span>
                </div>
                <div className={rowCls}>
                  <span className="text-gray-400">Baseline Sharpe / Sortino</span>
                  <span className="text-gray-300">{fmt(getNum(backtest.baseline_comparison.stats.sharpe))} / {fmt(getNum(backtest.baseline_comparison.stats.sortino))}</span>
                </div>
              </div>
            )}

            {backtest.drawdown_analysis && Object.keys(backtest.drawdown_analysis).length > 0 && (
              <div className={sectionCls}>
                <div className="text-[9px] uppercase text-gray-500 font-bold">Drawdown Quality</div>
                <HelpBox title="Survivability check">
                  Drawdown is the pain between equity highs. Recovery factor compares total profit to worst drawdown; higher is healthier, while long drawdown duration is harder to sit through.
                </HelpBox>
                <div className={rowCls}>
                  <span className="text-gray-400">Recovery factor</span>
                  <span className="text-gray-300">{fmt(getNum(backtest.drawdown_analysis.recovery_factor))}</span>
                </div>
                <div className={rowCls}>
                  <span className="text-gray-400">Average drawdown</span>
                  <span className="text-amber-300">{fmt(getNum(backtest.drawdown_analysis.average_drawdown))}</span>
                </div>
                <div className={rowCls}>
                  <span className="text-gray-400">MDD duration</span>
                  <span className="text-gray-300">{fmt(getNum(backtest.drawdown_analysis.max_drawdown_duration_trades))} trades</span>
                </div>
              </div>
            )}

            <div className="text-[10px] text-gray-500">
              Checked {backtest.checked_bars} bars; {backtest.no_trade_bars} bars were no-trade.
            </div>

            <HelpBox title="Exports">
              JSON contains the full research payload for audit. Journal CSV is easier for customers to review each trade, no-trade, factor reason, and exit.
            </HelpBox>

            <div className="grid grid-cols-2 gap-2">
              <button type="button" onClick={exportResearchJson} className="py-1.5 rounded-lg bg-gray-900 hover:bg-gray-800 text-[10px] text-gray-300">
                Export JSON
              </button>
              <button type="button" onClick={exportJournalCsv} className="py-1.5 rounded-lg bg-gray-900 hover:bg-gray-800 text-[10px] text-gray-300">
                Export Journal CSV
              </button>
            </div>

            {backtest.cost_sensitivity?.length > 0 && (
              <div className={sectionCls}>
                <div className="text-[9px] uppercase text-gray-500 font-bold py-1">Cost Sensitivity</div>
                <HelpBox title="Execution reality">
                  This reruns P&L at lower and higher cost assumptions. A robust strategy should not disappear when costs are doubled.
                </HelpBox>
                {backtest.cost_sensitivity.map((c) => (
                  <div key={String(c.cost_multiplier)} className={rowCls}>
                    <span className="text-gray-400">{String(c.cost_multiplier)}x costs</span>
                    <span className={(c.net_pnl ?? 0) >= 0 ? "text-emerald-300" : "text-red-300"}>{fmt(c.net_pnl ?? 0)}</span>
                  </div>
                ))}
              </div>
            )}

            {backtest.regime_summary?.length > 0 && (
              <div className={sectionCls}>
                <div className="text-[9px] uppercase text-gray-500 font-bold py-1">Regime Split</div>
                <HelpBox title="When it works">
                  This separates performance by trend, volatility proxy, and expiry status so one good market condition does not hide weak ones.
                </HelpBox>
                {backtest.regime_summary.slice(0, 4).map((r) => (
                  <div key={String(r.name)} className={rowCls}>
                    <span className="text-gray-400 truncate">{String(r.name)}</span>
                    <span className={(r.net_pnl ?? 0) >= 0 ? "text-emerald-300" : "text-red-300"}>{fmt(r.net_pnl ?? 0)}</span>
                  </div>
                ))}
              </div>
            )}

            {backtest.trade_quality && Object.keys(backtest.trade_quality).length > 0 && (
              <div className={sectionCls}>
                <div className="text-[9px] uppercase text-gray-500 font-bold py-1">Trade Quality</div>
                <HelpBox title="Trade behavior">
                  This shows whether profits come from targets, stops, or time exits, and whether losers are being held longer than winners.
                </HelpBox>
                <div className={rowCls}>
                  <span className="text-gray-400">Payoff ratio</span>
                  <span className="text-gray-300">{fmt(getNum(backtest.trade_quality.payoff_ratio))}</span>
                </div>
                <div className={rowCls}>
                  <span className="text-gray-400">Winner / loser hold</span>
                  <span className="text-gray-300">{fmt(getNum(backtest.trade_quality.avg_winner_holding_minutes))}m / {fmt(getNum(backtest.trade_quality.avg_loser_holding_minutes))}m</span>
                </div>
                <div className={rowCls}>
                  <span className="text-gray-400">Skipped baseline net</span>
                  <span className={getNum(backtest.trade_quality.skipped_baseline?.net_pnl) >= 0 ? "text-emerald-300" : "text-red-300"}>{fmt(getNum(backtest.trade_quality.skipped_baseline?.net_pnl))}</span>
                </div>
                {Object.entries(backtest.trade_quality.exit_reason_distribution ?? {}).slice(0, 4).map(([name, count]) => (
                  <div key={name} className={rowCls}>
                    <span className="text-gray-400">{name}</span>
                    <span className="text-gray-300">{String(count)} exits</span>
                  </div>
                ))}
              </div>
            )}

            {backtest.timing_analysis && Object.keys(backtest.timing_analysis).length > 0 && (
              <div className={sectionCls}>
                <div className="text-[9px] uppercase text-gray-500 font-bold py-1">Timing Analysis</div>
                <HelpBox title="Timing behavior">
                  This checks weekday, expiry-day, entry-time, and holding-duration buckets. Options often behave differently near expiry and around market open.
                </HelpBox>
                {(backtest.timing_analysis.expiry ?? []).slice(0, 3).map((r: Record<string, any>) => (
                  <div key={String(r.name)} className={rowCls}>
                    <span className="text-gray-400">{String(r.name)}</span>
                    <span className={(r.net_pnl ?? 0) >= 0 ? "text-emerald-300" : "text-red-300"}>{fmt(r.net_pnl ?? 0)}</span>
                  </div>
                ))}
                {(backtest.timing_analysis.entry_time ?? []).slice(0, 3).map((r: Record<string, any>) => (
                  <div key={String(r.name)} className={rowCls}>
                    <span className="text-gray-400">Entry {String(r.name)}</span>
                    <span className={(r.net_pnl ?? 0) >= 0 ? "text-emerald-300" : "text-red-300"}>{fmt(r.net_pnl ?? 0)}</span>
                  </div>
                ))}
              </div>
            )}

            {backtest.monte_carlo && Object.keys(backtest.monte_carlo).length > 0 && (
              <div className={sectionCls}>
                <div className="text-[9px] uppercase text-gray-500 font-bold py-1">Monte Carlo</div>
                <HelpBox title="Bad-sequence risk">
                  This resamples trade returns to estimate how bad drawdown could get if winners and losers arrive in a less friendly order.
                </HelpBox>
                <div className={rowCls}>
                  <span className="text-gray-400">Historical MDD</span>
                  <span className="text-amber-300">{fmt(getNum(backtest.monte_carlo.historical_mdd))}</span>
                </div>
                <div className={rowCls}>
                  <span className="text-gray-400">MC MDD 95% / 99%</span>
                  <span className="text-red-300">{fmt(getNum(backtest.monte_carlo.mdd_95))} / {fmt(getNum(backtest.monte_carlo.mdd_99))}</span>
                </div>
                <div className={rowCls}>
                  <span className="text-gray-400">P&L p05 / median / p95</span>
                  <span className="text-gray-300">{fmt(getNum(backtest.monte_carlo.pnl_p05))} / {fmt(getNum(backtest.monte_carlo.median_pnl))} / {fmt(getNum(backtest.monte_carlo.pnl_p95))}</span>
                </div>
              </div>
            )}

            {backtest.statistical_significance && Object.keys(backtest.statistical_significance).length > 0 && (
              <div className={sectionCls}>
                <div className="text-[9px] uppercase text-gray-500 font-bold py-1">Statistical Significance</div>
                <HelpBox title="Trust level">
                  Small samples can look strong by luck. Use p-value and required-trade count as a warning before treating results as reliable.
                </HelpBox>
                <div className={rowCls}>
                  <span className="text-gray-400">t-stat / p-value</span>
                  <span className="text-gray-300">{fmt(getNum(backtest.statistical_significance.t_statistic))} / {fmt(getNum(backtest.statistical_significance.p_value))}</span>
                </div>
                <div className={rowCls}>
                  <span className="text-gray-400">More trades needed</span>
                  <span className="text-amber-300">{fmt(getNum(backtest.statistical_significance.additional_trades_needed))}</span>
                </div>
              </div>
            )}

            <HelpBox title="Trade rows">
              These are the actual strategy trades. Each row shows the date, signal, selected strike, exit reason, regime, and final net P&L.
            </HelpBox>

            <div className="max-h-44 overflow-y-auto border border-gray-800 rounded-lg">
              {backtest.trades.slice(0, 12).map((t) => (
                <div key={`${t.day}-${t.entry_time}-${t.strike}-${t.opt_type}`} className="grid grid-cols-[1fr_auto] gap-2 px-2 py-1.5 border-b border-gray-900 last:border-0 text-[10px]">
                  <div className="text-gray-300">
                    {t.day} {t.signal_type} {t.strike} {t.opt_type}
                    <span className="text-gray-600"> | {t.exit_reason} | {t.regime ?? "regime n/a"}</span>
                  </div>
                  <div className={t.net_pnl >= 0 ? "text-emerald-300" : "text-red-300"}>{fmt(t.net_pnl)}</div>
                </div>
              ))}
              {!backtest.trades.length && (
                <div className="px-2 py-2 text-[10px] text-gray-500">No valid trades in this range.</div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

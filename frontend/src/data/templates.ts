import type {
  LegSpec, IndicatorDef, IndicatorType, Operand, Condition, ConditionGroup,
  ExitConditionsConfig,
} from "../types";

export interface StrategyTemplate {
  id: string;
  name: string;
  category: "premium-sell" | "premium-buy" | "spread" | "directional" | "indicator";
  description: string;
  tags: string[];
  underlying: "NIFTY" | "BANKNIFTY";
  entry_time: string;
  exit_time: string;
  expiry_offset: number;
  legs: Omit<LegSpec, "sl_unit" | "tp_unit">[];
  exit_hint: string;
  indicators?: IndicatorDef[];
  entry_signal?: ConditionGroup;
  exit_signal?: ConditionGroup;
  exit_conditions?: Partial<ExitConditionsConfig>;
}

// ---- indicator/condition builders for templates ----
const ind = (type: IndicatorType, name: string, over: Partial<IndicatorDef> = {}): IndicatorDef => ({
  id: name, type, name, interval: 5, field: "close",
  period: 14, fast: 12, slow: 26, signal: 9, multiplier: 3, std: 2,
  start_time: "09:15", end_time: "09:30", ...over,
});
const oInd = (ref: string, sub = "value"): Operand => ({ kind: "indicator", ref, sub, field: "", value: 0 });
const oCandle = (field: string): Operand => ({ kind: "candle", ref: "", sub: "", field, value: 0 });
const oConst = (value: number): Operand => ({ kind: "const", ref: "", sub: "", field: "", value });
const cond = (lhs: Operand, op: Condition["op"], rhs: Operand): Condition => ({ lhs, op, rhs });
const grp = (...conditions: Condition[]): ConditionGroup => ({ logic: "AND", conditions });

const mkLeg = (
  action: "BUY" | "SELL",
  opt_type: "CE" | "PE",
  value = 0,
  lots = 1,
  sl_pct: number | null = null,
  tp_pct: number | null = null,
): Omit<LegSpec, "sl_unit" | "tp_unit"> => ({
  action, opt_type, selection: "ATM", value, lots, sl_pct, tp_pct,
});

export const STRATEGY_TEMPLATES: StrategyTemplate[] = [
  {
    id: "short-straddle-expiry",
    name: "Short Straddle — Expiry Day",
    category: "premium-sell",
    description: "Sell ATM CE+PE Thursday open. Max theta decay on 0DTE. Exit at time or 50% profit.",
    tags: ["0DTE", "theta", "straddle"],
    underlying: "NIFTY",
    entry_time: "09:20",
    exit_time: "15:20",
    expiry_offset: 0,
    legs: [mkLeg("SELL", "CE", 0, 1, 100, 50), mkLeg("SELL", "PE", 0, 1, 100, 50)],
    exit_hint: "Overall target 50% | Overall SL 100%",
  },
  {
    id: "short-straddle-tuesday",
    name: "Short Straddle — Tuesday Entry",
    category: "premium-sell",
    description: "Sell ATM straddle Tuesday open, ride 3 days of theta to Thursday expiry.",
    tags: ["weekly", "theta", "straddle"],
    underlying: "NIFTY",
    entry_time: "09:20",
    exit_time: "15:20",
    expiry_offset: 0,
    legs: [mkLeg("SELL", "CE", 0, 1, 100, 50), mkLeg("SELL", "PE", 0, 1, 100, 50)],
    exit_hint: "Overall target 50% | Overall SL 100% | Enter Tuesday only",
  },
  {
    id: "short-strangle-weekly",
    name: "Short Strangle — Weekly",
    category: "premium-sell",
    description: "Sell 2-step OTM CE + PE Monday. Wider tent, more room to be wrong.",
    tags: ["weekly", "strangle", "OTM"],
    underlying: "NIFTY",
    entry_time: "09:20",
    exit_time: "15:20",
    expiry_offset: 0,
    legs: [mkLeg("SELL", "CE", 2, 1, 150, 50), mkLeg("SELL", "PE", 2, 1, 150, 50)],
    exit_hint: "Overall target 50% | Overall SL 150%",
  },
  {
    id: "iron-condor-weekly",
    name: "Iron Condor — Weekly",
    category: "spread",
    description: "Sell 2-OTM CE+PE, buy 4-OTM wings. Defined risk. Best risk-adjusted ratio.",
    tags: ["IC", "defined-risk", "weekly"],
    underlying: "NIFTY",
    entry_time: "09:20",
    exit_time: "15:20",
    expiry_offset: 0,
    legs: [
      mkLeg("SELL", "CE", 2, 1, null, 70),
      mkLeg("BUY",  "CE", 4, 1),
      mkLeg("SELL", "PE", 2, 1, null, 70),
      mkLeg("BUY",  "PE", 4, 1),
    ],
    exit_hint: "Overall target 70% | Overall SL 200%",
  },
  {
    id: "bull-put-spread",
    name: "Bull Put Spread",
    category: "directional",
    description: "Sell ATM PE, buy 2-step OTM PE hedge. Bullish bias, limited risk.",
    tags: ["spread", "bullish", "directional"],
    underlying: "NIFTY",
    entry_time: "09:20",
    exit_time: "15:20",
    expiry_offset: 0,
    legs: [mkLeg("SELL", "PE", 0, 1, null, 70), mkLeg("BUY", "PE", 2, 1)],
    exit_hint: "Overall target 70% | PCR filter min 0.9",
  },
  {
    id: "bear-call-spread",
    name: "Bear Call Spread",
    category: "directional",
    description: "Sell ATM CE, buy 2-step OTM CE hedge. Bearish bias, limited risk.",
    tags: ["spread", "bearish", "directional"],
    underlying: "NIFTY",
    entry_time: "09:20",
    exit_time: "15:20",
    expiry_offset: 0,
    legs: [mkLeg("SELL", "CE", 0, 1, null, 70), mkLeg("BUY", "CE", 2, 1)],
    exit_hint: "Overall target 70% | PCR filter max 1.1",
  },
  {
    id: "jade-lizard",
    name: "Jade Lizard",
    category: "spread",
    description: "Sell 1-OTM PE, sell 2-OTM CE, buy 4-OTM CE. Zero upside risk.",
    tags: ["jade-lizard", "no-upside-risk", "advanced"],
    underlying: "NIFTY",
    entry_time: "09:20",
    exit_time: "15:20",
    expiry_offset: 0,
    legs: [
      mkLeg("SELL", "PE", 1, 1, 200),
      mkLeg("SELL", "CE", 2, 1, 200),
      mkLeg("BUY",  "CE", 4, 1),
    ],
    exit_hint: "Overall SL 200% | Trailing SL 30% from peak",
  },
  {
    id: "ratio-spread-ce",
    name: "Ratio Spread CE 1:2",
    category: "premium-sell",
    description: "Buy 1 ATM CE, sell 2 OTM CE. Net credit. Profits in mild rally.",
    tags: ["ratio", "CE", "neutral-bullish"],
    underlying: "NIFTY",
    entry_time: "09:20",
    exit_time: "15:20",
    expiry_offset: 0,
    legs: [mkLeg("BUY", "CE", 0, 1), mkLeg("SELL", "CE", 2, 2, 200)],
    exit_hint: "Overall SL 200% | Trailing SL 25%",
  },
  {
    id: "calendar-straddle",
    name: "Calendar Spread — Straddle",
    category: "spread",
    description: "Sell current-week ATM straddle, buy next-week ATM straddle. Long vega/theta.",
    tags: ["calendar", "vega", "multi-expiry"],
    underlying: "NIFTY",
    entry_time: "09:20",
    exit_time: "15:20",
    expiry_offset: 0,
    legs: [
      mkLeg("SELL", "CE", 0, 1),
      mkLeg("SELL", "PE", 0, 1),
      mkLeg("BUY",  "CE", 0, 1),
      mkLeg("BUY",  "PE", 0, 1),
    ],
    exit_hint: "Time-based exit only — calendar needs DTE",
  },
  {
    id: "naked-put-sell",
    name: "Naked Put Sell",
    category: "directional",
    description: "Sell 1-step OTM PE. Bullish trend-following. High premium, no upside cap.",
    tags: ["naked", "put-sell", "bullish", "aggressive"],
    underlying: "NIFTY",
    entry_time: "09:30",
    exit_time: "15:20",
    expiry_offset: 0,
    legs: [mkLeg("SELL", "PE", 1, 1, 200, 60)],
    exit_hint: "Per-leg SL 200% | Target 60% | IVR filter >15%",
  },

  // ---------- Indicator-driven (Quantman-style signal) templates ----------
  {
    id: "ema-crossover-trend",
    name: "EMA Crossover — Trend",
    category: "indicator",
    description: "EMA 9 crosses above EMA 21 (5m) → buy ATM CE. Exit on cross-back down. Classic momentum.",
    tags: ["EMA", "crossover", "directional", "5m"],
    underlying: "NIFTY",
    entry_time: "09:20",
    exit_time: "15:15",
    expiry_offset: 0,
    legs: [mkLeg("BUY", "CE", 0, 1, 30, null)],
    exit_hint: "Entry: emaFast crosses above emaSlow | Exit: cross below",
    indicators: [ind("EMA", "emaFast", { period: 9 }), ind("EMA", "emaSlow", { period: 21 })],
    entry_signal: grp(cond(oInd("emaFast"), "cross_above", oInd("emaSlow"))),
    exit_signal: grp(cond(oInd("emaFast"), "cross_below", oInd("emaSlow"))),
  },
  {
    id: "supertrend-follow",
    name: "Supertrend Follow",
    category: "indicator",
    description: "Supertrend(10,3) turns up → sell ATM PE (ride the uptrend). Exit when it flips down.",
    tags: ["supertrend", "trend", "PE-sell", "5m"],
    underlying: "NIFTY",
    entry_time: "09:20",
    exit_time: "15:15",
    expiry_offset: 0,
    legs: [mkLeg("SELL", "PE", 0, 1, 35, null)],
    exit_hint: "Entry: Supertrend dir > 0 | Exit: dir < 0",
    indicators: [ind("SUPERTREND", "st", { period: 10, multiplier: 3 })],
    entry_signal: grp(cond(oInd("st", "dir"), ">", oConst(0))),
    exit_signal: grp(cond(oInd("st", "dir"), "<", oConst(0))),
  },
  {
    id: "rsi-reversal",
    name: "RSI Reversal",
    category: "indicator",
    description: "RSI(14) crosses above 30 (oversold bounce) → buy ATM CE. Exit when RSI > 60 or SL.",
    tags: ["RSI", "mean-reversion", "5m"],
    underlying: "NIFTY",
    entry_time: "09:20",
    exit_time: "15:15",
    expiry_offset: 0,
    legs: [mkLeg("BUY", "CE", 0, 1, 30, null)],
    exit_hint: "Entry: RSI crosses above 30 | Exit: RSI above 60",
    indicators: [ind("RSI", "rsi", { period: 14 })],
    entry_signal: grp(cond(oInd("rsi"), "cross_above", oConst(30))),
    exit_signal: grp(cond(oInd("rsi"), ">", oConst(60))),
  },
  {
    id: "macd-momentum",
    name: "MACD Momentum",
    category: "indicator",
    description: "MACD line crosses above signal (12/26/9) → buy ATM CE. Exit on cross below.",
    tags: ["MACD", "momentum", "5m"],
    underlying: "NIFTY",
    entry_time: "09:20",
    exit_time: "15:15",
    expiry_offset: 0,
    legs: [mkLeg("BUY", "CE", 0, 1, 30, null)],
    exit_hint: "Entry: MACD crosses above signal | Exit: cross below",
    indicators: [ind("MACD", "macd", { fast: 12, slow: 26, signal: 9 })],
    entry_signal: grp(cond(oInd("macd", "macd"), "cross_above", oInd("macd", "signal"))),
    exit_signal: grp(cond(oInd("macd", "macd"), "cross_below", oInd("macd", "signal"))),
  },
  {
    id: "opening-range-breakout",
    name: "Opening Range Breakout",
    category: "indicator",
    description: "Price breaks above the 09:15–09:30 high → buy ATM CE. Exit on break of the range low or time.",
    tags: ["ORB", "breakout", "intraday"],
    underlying: "NIFTY",
    entry_time: "09:30",
    exit_time: "15:15",
    expiry_offset: 0,
    legs: [mkLeg("BUY", "CE", 0, 1, 35, null)],
    exit_hint: "Entry: close crosses above ORB high | Exit: close crosses below ORB low",
    indicators: [ind("RANGE_BREAKOUT", "orb", { start_time: "09:15", end_time: "09:30" })],
    entry_signal: grp(cond(oCandle("close"), "cross_above", oInd("orb", "hi"))),
    exit_signal: grp(cond(oCandle("close"), "cross_below", oInd("orb", "lo"))),
  },
  {
    id: "rsi-range-straddle",
    name: "RSI Range Straddle (sell)",
    category: "indicator",
    description: "RSI between 40–60 (range-bound) → sell ATM straddle. Exit on overall target/SL.",
    tags: ["RSI", "straddle", "premium-sell", "range"],
    underlying: "NIFTY",
    entry_time: "09:20",
    exit_time: "15:20",
    expiry_offset: 0,
    legs: [mkLeg("SELL", "CE", 0, 1, null, null), mkLeg("SELL", "PE", 0, 1, null, null)],
    exit_hint: "Entry: 40 < RSI < 60 | Exit: target 25% / SL 50%",
    indicators: [ind("RSI", "rsi", { period: 14 })],
    entry_signal: grp(cond(oInd("rsi"), "<", oConst(60)), cond(oInd("rsi"), ">", oConst(40))),
    exit_conditions: { overall_target_pct: 25, overall_sl_pct: 50, force_exit_time: "15:20" },
  },
];

export const TEMPLATE_MAP: Record<string, StrategyTemplate> = Object.fromEntries(
  STRATEGY_TEMPLATES.map((t) => [t.id, t]),
);

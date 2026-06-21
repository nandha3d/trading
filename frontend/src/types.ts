export interface LegSpec {
  action: "BUY" | "SELL";
  opt_type: "CE" | "PE";
  selection: "ATM" | "PREMIUM" | "DELTA";
  value: number;
  lots: number;
  sl_pct: number | null;
  sl_unit: string;
  tp_pct: number | null;
  tp_unit: string;
}

export interface ExitConditionsConfig {
  overall_sl_pct: number;
  overall_target_pct: number;
  trailing_sl_pct: number;
  force_exit_time: string;
  re_entry_after_sl: boolean;
}

export interface IndicatorConfig {
  type: "" | "EMA_CROSS" | "RSI" | "BOLLINGER" | "VWAP";
  ema_fast: number;
  ema_slow: number;
  ema_signal: "above" | "below";
  rsi_period: number;
  rsi_oversold: number;
  rsi_overbought: number;
  bb_period: number;
  bb_std: number;
  bb_signal: "upper" | "lower" | "squeeze";
  vwap_signal: "above" | "below";
}

export interface EntryConditionsConfig {
  weekdays: number[];
  min_pcr: number;
  max_pcr: number;
  min_iv_rank: number;
  max_iv_rank: number;
  use_vix_gate: boolean;
  vix_regimes: string[];
  indicator: IndicatorConfig;
}

export const DEFAULT_EXIT: ExitConditionsConfig = {
  overall_sl_pct: 0, overall_target_pct: 0, trailing_sl_pct: 0,
  force_exit_time: "15:20", re_entry_after_sl: false,
};

export const DEFAULT_ENTRY: EntryConditionsConfig = {
  weekdays: [0, 1, 2, 3, 4], min_pcr: 0, max_pcr: 0,
  min_iv_rank: 0, max_iv_rank: 0, use_vix_gate: false,
  vix_regimes: ["normal", "elevated"],
  indicator: {
    type: "", ema_fast: 9, ema_slow: 21, ema_signal: "above",
    rsi_period: 14, rsi_oversold: 30, rsi_overbought: 70,
    bb_period: 20, bb_std: 2.0, bb_signal: "squeeze", vwap_signal: "above",
  },
};

// ---- Quantman-style indicator + condition engine ----

export type IndicatorType =
  | "SMA" | "EMA" | "RSI" | "SUPERTREND" | "MACD"
  | "BOLLINGER" | "VWAP" | "ATR" | "RANGE_BREAKOUT" | "CURRENT_CANDLE";

export interface IndicatorDef {
  id: string;
  type: IndicatorType;
  name: string;
  interval: number;
  field: "close" | "open" | "high" | "low";
  period: number;
  fast: number;
  slow: number;
  signal: number;
  multiplier: number;
  std: number;
  start_time: string;
  end_time: string;
}

export type OperandKind = "indicator" | "candle" | "const";

export interface Operand {
  kind: OperandKind;
  ref: string;   // indicator name
  sub: string;   // indicator sub-output
  field: string; // candle field
  value: number; // const
}

export type CondOp = ">" | "<" | ">=" | "<=" | "==" | "cross_above" | "cross_below";

export interface Condition {
  lhs: Operand;
  op: CondOp;
  rhs: Operand;
}

export interface ConditionGroup {
  logic: "AND" | "OR";
  conditions: Condition[];
}

export interface BacktestRequest {
  underlying: "NIFTY" | "BANKNIFTY";
  start: string;
  end: string;
  entry_time: string;
  exit_time: string;
  legs: LegSpec[];
  expiry_offset: number;
  exit_conditions?: ExitConditionsConfig;
  entry_conditions?: EntryConditionsConfig;
  indicators?: IndicatorDef[];
  entry_signal?: ConditionGroup | null;
  exit_signal?: ConditionGroup | null;
}

export interface LegResult {
  strike: number;
  entry: number;
  exit: number;
  qty: number;
  exit_reason: string;
  action: string;
  opt_type?: string;
  exit_time?: string | null;
}

export interface TradeResult {
  day: string;
  gross: number;
  cost: number;
  net: number;
  exit_reason: string;
  legs: LegResult[];
  entry_spot: number;
  skip_reason: string;
  vix: number;
  expiry?: string;
  entry_time?: string | null;
}

export interface StatsResult {
  trades: number;
  win_rate: number;
  net_pnl: number;
  expectancy: number;
  avg_win: number;
  avg_loss: number;
  max_drawdown: number;
  sharpe: number;
}

export interface BacktestResponse {
  stats: StatsResult;
  trades: TradeResult[];
  equity_curve: number[];
  skipped_days: number;
  run_id?: string;
}

// ---- OI Strategy Signal Detector ----

export interface OiStrategyConfigOverrides {
  min_option_oi?: number;
  min_option_volume?: number;
  max_bid_ask_spread_percent?: number;
  min_option_ltp?: number;
  oi_wall_multiplier?: number;
  ce_unwinding_threshold_percent?: number;
  pe_unwinding_threshold_percent?: number;
  ce_buildup_threshold_percent?: number;
  pe_buildup_threshold_percent?: number;
  volume_multiplier?: number;
  min_signal_score?: number;
  strong_signal_score?: number;
  no_trade_first_minutes?: number;
  no_fresh_trade_after?: string;
  force_exit_time?: string;
  premium_sl_percent?: number;
  premium_target_percent?: number;
  trailing_sl_percent?: number;
  max_trades_per_day?: number;
  monitor_strikes?: number;
  oi_lookback_candles?: number;
  pcr_lookback_candles?: number;
  volume_avg_candles?: number;
  trend_timeframes?: number[];
  score_weights?: Record<string, number>;
  execution_model?: "close" | "adverse_close" | "estimated_spread" | string;
  slippage_bps?: number;
  estimated_spread_percent?: number;
  initial_capital?: number;
  risk_per_trade_percent?: number;
  daily_loss_limit_percent?: number;
  cooldown_after_loss_bars?: number;
  theta_exit_profile?: string;
  expiry_day_tightening?: boolean;
  require_factor_coverage_percent?: number;
}

export interface OiStrategySignalRequest {
  underlying: string;
  date: string;
  timestamp?: string | null;
  expiry?: string | null;
  mode?: string;
  interval?: number;
  config?: OiStrategyConfigOverrides;
}

export interface OiSuggestedLeg extends LegSpec {
  entry_time?: string | null;
  exit_time?: string | null;
}

export interface OiScoreComponent {
  factor?: string | null;
  label: string;
  points: number;
  max_points: number;
  passed: boolean;
  available?: boolean;
  detail: string;
  raw_value?: number | string | null;
  threshold?: number | string | null;
}

export interface OiWallResult {
  strike: number;
  option_type: string;
  oi: number;
  avg_oi: number;
  rank: number;
  oi_change: number;
  oi_change_percent: number | null;
  ltp: number | null;
  ltp_change_percent: number | null;
}

export interface OiStrategySignalResponse {
  underlying: string;
  expiry: string | null;
  timestamp: string | null;
  spot_price: number | null;
  atm_strike: number | null;
  signal_type: "BUY_CE" | "BUY_PE" | "NO_TRADE" | string;
  strategy_name: string;
  score: number;
  strength: "STRONG" | "VALID" | "NO_TRADE" | string;
  reasons: string[];
  no_trade_reasons: string[];
  score_breakdown: OiScoreComponent[];
  factor_scores: OiScoreComponent[];
  factor_coverage: Record<string, number | string | null>;
  candidate_signal_type?: string | null;
  candidate_direction?: string | null;
  regime?: string | null;
  walls: {
    ce_wall: OiWallResult | null;
    pe_wall: OiWallResult | null;
  };
  entry_zone: number | null;
  stop_loss: number | null;
  target_1: number | null;
  target_2: number | null;
  suggested_legs: OiSuggestedLeg[];
  data_quality: Record<string, unknown>;
  config: Record<string, unknown>;
}

export interface OiStrategyBacktestRequest {
  underlying: string;
  start: string;
  end: string;
  expiry_offset?: number;
  interval?: number;
  mode?: string;
  config?: OiStrategyConfigOverrides;
}

export interface OiStrategyBacktestStats {
  trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  net_pnl: number;
  gross_profit: number;
  gross_loss: number;
  profit_factor: number;
  avg_trade: number;
  avg_win: number;
  avg_loss: number;
  max_drawdown: number;
  expectancy: number;
  sharpe: number;
  sortino: number;
  win_rate_ci_low: number;
  win_rate_ci_high: number;
}

export interface OiStrategyBacktestTrade {
  underlying: string;
  day: string;
  expiry: string;
  entry_time: string;
  exit_time: string;
  signal_type: string;
  strategy_name: string;
  score: number;
  strength: string;
  strike: number;
  opt_type: string;
  qty: number;
  entry_price: number;
  exit_price: number;
  raw_entry_price?: number | null;
  raw_exit_price?: number | null;
  exit_reason: string;
  gross_pnl: number;
  cost: number;
  net_pnl: number;
  entry_spot: number | null;
  reasons: string[];
  factor_scores: OiScoreComponent[];
  factor_coverage: Record<string, number | string | null>;
  wall_strike?: number | null;
  regime?: string | null;
  mae: number;
  mfe: number;
}

export interface OiStrategyBacktestDay {
  day: string;
  trades: number;
  net_pnl: number;
  skip_reason: string;
}

export interface OiStrategyBacktestResponse {
  underlying: string;
  start: string;
  end: string;
  interval: number;
  expiry_offset: number;
  stats: OiStrategyBacktestStats;
  equity_curve: number[];
  trades: OiStrategyBacktestTrade[];
  daily: OiStrategyBacktestDay[];
  checked_bars: number;
  no_trade_bars: number;
  trade_journal: Record<string, unknown>[];
  baseline_comparison: Record<string, any>;
  cost_sensitivity: Record<string, any>[];
  regime_summary: Record<string, any>[];
  factor_summary: Record<string, any>[];
  walk_forward_summary: Record<string, any>[];
  data_quality: Record<string, unknown>;
  config: Record<string, unknown>;
}

export interface DbStatus {
  options_1m: {
    rows: number;
    ts_min: string | null;
    ts_max: string | null;
    null_keys: number;
    dup_keys: number;
    by_underlying: Record<string, number>;
  };
  spot_1m: {
    rows: number;
    ts_min: string | null;
    ts_max: string | null;
    null_keys: number;
    dup_keys: number;
    by_underlying: Record<string, number>;
  };
}

export interface OptionData {
  close: number | null;
  volume: number | null;
  oi: number | null;
  iv: number | null;
  delta: number | null;
  theta: number | null;
  oi_change: number | null;
}

export interface OptionsChainRow {
  strike: number;
  ce: OptionData | null;
  pe: OptionData | null;
}

export interface OptionsChainSummary {
  pcr: number;
  max_pain: number;
  total_ce_oi: number;
  total_pe_oi: number;
}

export interface OptionsChainResponse {
  underlying: string;
  expiry: string;
  timestamp: string;
  spot_price: number | null;
  future_price?: number | null;   // front-month index future (live Angel feed only)
  future_expiry?: string | null;  // ISO expiry of the future contract above
  lot_size?: number | null;       // broker's authoritative lot size (live feed)
  chain: OptionsChainRow[];
  summary: OptionsChainSummary | null;
  source?: string;   // "angelone" = real live feed; absent/other = simulated
  status?: string;   // feed status: connected / disconnected / error / ...
  stale?: boolean;   // true = market closed/holiday; showing last fetched snapshot
}

// ---- Payoff Builder ----

export interface PayoffLegSpec {
  action: "BUY" | "SELL";
  opt_type: "CE" | "PE";
  strike: number;
  lots: number;
  entry_price: number;
  underlying: string;
  expiry?: string;   // per-leg expiry for calendar/diagonal spreads; omit = use chain expiry
}

export interface PayoffRequest {
  underlying: string;
  spot: number;
  expiry: string;
  current_date: string;
  legs: PayoffLegSpec[];
  r: number;
  lot_size?: number | null;   // from live chain (broker scrip); overrides server default
}

export interface PayoffPoint {
  spot: number;
  expiry_pnl: number;
  today_pnl: number;
}

export interface NetGreeks {
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
}

export interface PayoffResponse {
  curve: PayoffPoint[];
  breakevens: number[];
  max_profit: number | null;   // null = unbounded ("Unlimited")
  max_loss: number | null;     // null = unbounded
  net_premium: number;
  net_greeks: NetGreeks;
}

export interface BlockTradeAlert {
  timestamp: string;
  strike: number;
  option_type: "CE" | "PE";
  action: "BUY" | "SELL";
  qty: number;
  price: number;
  value: number;
}

export interface PcrTrendPoint {
  time: string;
  pcr: number;
  max_pain: number;
}

export interface LiveTelemetryResponse {
  underlying: string;
  expiry: string;
  timestamp: string;
  spot_price: number;
  pcr: number;
  max_pain: number;
  total_ce_oi: number;
  total_pe_oi: number;
  chain: OptionsChainRow[];
  pcr_trend: PcrTrendPoint[];
  block_trades: BlockTradeAlert[];
}

// ---- FlowMatrix: Connecting Dots ----

export interface DotsRow {
  time: string;
  trend: string; // Extreme Bullish | Bullish | Bearish | Extreme Bearish
  price: number; // +1 bull / -1 bear / 0 neutral
  oi: number;
  vix: number;
  vwap: number;
  supertrend: number;
  rsi: number;
  values: {
    close: number;
    pcr: number | null;
    rsi: number | null;
    vwap: number | null;
  };
}

export interface DotsResponse {
  rows: DotsRow[];
  underlying: string;
  date: string;
  interval: number;
  has_vix: boolean;
  expiry: string | null;
  message: string | null;
}

// ---- FlowMatrix: Live OI Flow ----

export interface FlowStrikeRow {
  strike: number;
  ce_oi: number;
  pe_oi: number;
  ce_oi_chg: number;
  pe_oi_chg: number;
  ce_ltp: number;
  pe_ltp: number;
  ce_interp: string;
  pe_interp: string;
}

export interface FlowBuildupRow {
  strike: number;
  ce_oi_chg: number;
  pe_oi_chg: number;
}

export interface FlowLiveResponse {
  underlying: string;
  expiry: string;
  timestamp: string;
  spot_price: number;
  future_price: number | null;
  pcr: number;
  max_pain: number;
  max_pain_dist: number | null;
  support: number;
  resistance: number;
  total_ce_oi: number;
  total_pe_oi: number;
  total_ce_oi_chg: number;
  total_pe_oi_chg: number;
  expected_range: { low: number; high: number; straddle: number; atm: number } | null;
  top_ce_buildup: FlowBuildupRow[];
  top_pe_buildup: FlowBuildupRow[];
  verdict: string;
  pcr_trend: { time: string; pcr: number; max_pain: number }[];
  rows: FlowStrikeRow[];
  source: string;
  status: string;
  stale: boolean;
}

// ---- FlowMatrix: OI Analysis ----

export interface OiBreak {
  type: string; // D.H.B | D.L.B
  level: number;
}

export interface OiRow {
  time: string;
  call_oi: number;
  call_oi_chg: number;
  call_ltp: number | null;
  call_ltp_chg: number;
  call_interp: string;
  call_break: OiBreak | null;
  total_oi_chg: number;
  strike: number;
  put_oi: number;
  put_oi_chg: number;
  put_ltp: number | null;
  put_ltp_chg: number;
  put_interp: string;
  put_break: OiBreak | null;
}

export interface OiAnalysisResponse {
  rows: OiRow[];
  underlying: string;
  date: string;
  expiry: string;
  strike: number;
  interval: number;
  message: string | null;
}

// ---- FlowMatrix: OI Tools (Statistics / Spurt / Big Move / Trending / Active) ----

export interface OiContract {
  strike: number;
  type: string; // CE | PE
  oi: number;
  oi_chg_bucket: number;
  oi_chg_day: number;
  ltp: number | null;
  ltp_chg: number;
  interp: string;
}

export interface OiStatRow {
  strike: number;
  ce_oi: number;
  pe_oi: number;
  ce_oi_chg: number;
  pe_oi_chg: number;
}

export interface OiStatistics {
  total_ce_oi: number;
  total_pe_oi: number;
  pcr: number | null;
  max_pain: number;
  rows: OiStatRow[];
}

export interface OiActiveStrike {
  strike: number;
  ce_oi: number;
  pe_oi: number;
  total_oi: number;
  bias: string;
}

export interface OiTrending {
  ce_oi_chg: number;
  pe_oi_chg: number;
  bull_pct: number;
  bear_pct: number;
  verdict: string;
}

export interface OiToolsResponse {
  underlying: string;
  date: string;
  expiry: string;
  interval: number;
  message: string | null;
  statistics: OiStatistics | null;
  spurt: OiContract[];
  big_movement: OiContract[];
  trending: OiTrending | null;
  active_strikes: OiActiveStrike[];
}

export interface SavedStrategy {
  id: string;
  name: string;
  underlying: string;
  expiry: string;
  created_at: string;
  legs: PayoffLegSpec[];
}

// ---- Parametric grid sweep (entry-time x stop-loss%) ----

export interface GridRequest {
  underlying: string;
  start: string;
  end: string;
  entry_start: string;
  entry_end: string;
  exit_time: string;
  sl_lo: number;
  sl_hi: number;
  sl_step: number;
  entry_step_min: number;
  expiry_offset: number;
  lots: number;
}

export interface GridCell {
  entry_time: string;
  sl_pct: number;
  net: number;
  gross: number;
  cost: number;
  trades: number;
  wins: number;
  win_rate: number;
  avg: number;
  max_dd: number;
}

export interface GridResponse {
  cells: GridCell[];
  entry_times: string[];
  sl_values: number[];
  best: GridCell | null;
  days_used: number;
}

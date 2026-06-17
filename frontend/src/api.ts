import type {
  BacktestRequest,
  BacktestResponse,
  DbStatus,
  OptionsChainResponse,
  PayoffRequest,
  PayoffResponse,
  SavedStrategy,
  PayoffLegSpec,
  DotsResponse,
  OiAnalysisResponse,
  OiToolsResponse,
  GridRequest,
  GridResponse,
  FlowLiveResponse,
} from "./types";

const BASE = "/api";

async function _json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail?: string }).detail ?? res.statusText);
  }
  return res.json() as Promise<T>;
}

export async function runBacktest(req: BacktestRequest): Promise<BacktestResponse> {
  const res = await fetch(`${BASE}/backtest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return _json<BacktestResponse>(res);
}

export async function runPayoff(req: PayoffRequest): Promise<PayoffResponse> {
  const res = await fetch(`${BASE}/strategy/payoff`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return _json<PayoffResponse>(res);
}

export async function runGrid(req: GridRequest): Promise<GridResponse> {
  const res = await fetch(`${BASE}/backtest/grid`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return _json<GridResponse>(res);
}

export async function getStatus(): Promise<DbStatus> {
  const res = await fetch(`${BASE}/status`);
  return _json<DbStatus>(res);
}

export async function getExpiries(underlying: string): Promise<string[]> {
  const res = await fetch(`${BASE}/expiries/${underlying}`);
  const data = await _json<{ expiries: string[] }>(res);
  return data.expiries;
}

export async function getTradeDates(underlying: string, expiry: string): Promise<string[]> {
  const res = await fetch(`${BASE}/options-chain/dates/${underlying}/${expiry}`);
  const data = await _json<{ dates: string[] }>(res);
  return data.dates;
}

export async function getExpiriesForDate(underlying: string, date: string): Promise<string[]> {
  const p = new URLSearchParams({ underlying, date });
  const res = await fetch(`${BASE}/options-chain/expiries-for-date?${p}`);
  const data = await _json<{ expiries: string[] }>(res);
  return data.expiries;
}

export async function getOptionsChainData(
  underlying: string,
  expiry: string,
  ts: string
): Promise<OptionsChainResponse> {
  const params = new URLSearchParams({ underlying, expiry, ts });
  const res = await fetch(`${BASE}/options-chain/data?${params.toString()}`);
  return _json<OptionsChainResponse>(res);
}

export async function getPayoffCurve(req: PayoffRequest): Promise<PayoffResponse> {
  const res = await fetch(`${BASE}/strategy/payoff`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return _json<PayoffResponse>(res);
}

export async function saveStrategy(
  name: string,
  underlying: string,
  expiry: string,
  legs: PayoffLegSpec[]
): Promise<{ id: string; status: string }> {
  const res = await fetch(`${BASE}/strategies/save`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, underlying, expiry, legs }),
  });
  return _json<{ id: string; status: string }>(res);
}

export async function listStrategies(): Promise<SavedStrategy[]> {
  const res = await fetch(`${BASE}/strategies/list`);
  return _json<SavedStrategy[]>(res);
}

export async function deleteStrategy(strategyId: string): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/strategies/${strategyId}`, {
    method: "DELETE",
  });
  return _json<{ status: string }>(res);
}

// ---- FlowMatrix ----

export async function getFlowDates(underlying: string): Promise<string[]> {
  const res = await fetch(`${BASE}/flow/dates?underlying=${underlying}`);
  const data = await _json<{ dates: string[] }>(res);
  return data.dates;
}

export async function getFlowLive(underlying: string, expiry = ""): Promise<FlowLiveResponse> {
  const params = new URLSearchParams({ underlying });
  if (expiry) params.set("expiry", expiry);
  const res = await fetch(`${BASE}/flow/live?${params.toString()}`);
  return _json<FlowLiveResponse>(res);
}

export async function getDots(
  underlying: string,
  date: string,
  interval: number,
  mode = "historical"
): Promise<DotsResponse> {
  const p = new URLSearchParams({ underlying, date, interval: String(interval), mode });
  const res = await fetch(`${BASE}/dots?${p.toString()}`);
  return _json<DotsResponse>(res);
}

export async function getOiExpiries(underlying: string, date: string): Promise<string[]> {
  const p = new URLSearchParams({ underlying, date });
  const res = await fetch(`${BASE}/oi-analysis/expiries?${p.toString()}`);
  const data = await _json<{ expiries: string[] }>(res);
  return data.expiries;
}

export async function getOiStrikes(
  underlying: string,
  date: string,
  expiry: string
): Promise<number[]> {
  const p = new URLSearchParams({ underlying, date, expiry });
  const res = await fetch(`${BASE}/oi-analysis/strikes?${p.toString()}`);
  const data = await _json<{ strikes: number[] }>(res);
  return data.strikes;
}

export async function getOiAnalysis(
  underlying: string,
  date: string,
  expiry: string,
  strike: number,
  interval: number,
  mode = "historical"
): Promise<OiAnalysisResponse> {
  const p = new URLSearchParams({
    underlying, date, expiry, strike: String(strike),
    interval: String(interval), mode,
  });
  const res = await fetch(`${BASE}/oi-analysis?${p.toString()}`);
  return _json<OiAnalysisResponse>(res);
}

export async function getOiTools(
  underlying: string,
  date: string,
  expiry: string,
  interval: number
): Promise<OiToolsResponse> {
  const p = new URLSearchParams({
    underlying, date, expiry, interval: String(interval),
  });
  const res = await fetch(`${BASE}/oi-tools?${p.toString()}`);
  return _json<OiToolsResponse>(res);
}

export interface FiiDiiParticipant {
  date: string;
  client_type: string;
  fut_idx_long: number | null;
  fut_idx_short: number | null;
  opt_call_long: number | null;
  opt_call_short: number | null;
  opt_put_long: number | null;
  opt_put_short: number | null;
}

export interface FiiDiiDay {
  date: string;
  participants: FiiDiiParticipant[];
}

export async function getFiiDii(days = 30): Promise<FiiDiiDay[]> {
  const res = await fetch(`${BASE}/fii-dii?days=${days}`);
  const data = await _json<{ days: FiiDiiDay[] }>(res);
  return data.days;
}

export interface Candle {
  time: number; open: number; high: number; low: number; close: number; volume: number;
}

export async function getCandles(
  underlying: string,
  date: string,
  interval: number
): Promise<Candle[]> {
  const p = new URLSearchParams({ underlying, date, interval: String(interval) });
  const res = await fetch(`${BASE}/chart/candles?${p.toString()}`);
  const data = await _json<{ candles: Candle[] }>(res);
  return data.candles;
}

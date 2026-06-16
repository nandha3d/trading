import { useEffect, useRef, useState } from "react";
import {
  createChart, ColorType, IChartApi, ISeriesApi, UTCTimestamp,
} from "lightweight-charts";
import { getCandles } from "../api";

interface Props {
  underlying: string;
  date: string;
  interval: number;
  height?: number;
}

/**
 * TradingView Lightweight-Charts candlestick fed by our own DuckDB candles
 * (/api/chart/candles). No external symbol gating — renders the data we store
 * and validated against NSE bhavcopy.
 */
export default function LWChart({ underlying, date, interval, height = 460 }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [count, setCount] = useState(0);

  // build chart once
  useEffect(() => {
    if (!wrapRef.current) return;
    const chart = createChart(wrapRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#030712" }, textColor: "#9ca3af" },
      grid: { vertLines: { color: "rgba(55,65,81,0.25)" }, horzLines: { color: "rgba(55,65,81,0.25)" } },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: "#1f2937" },
      rightPriceScale: { borderColor: "#1f2937" },
      crosshair: { mode: 0 },
      height,
      autoSize: true,
    });
    chartRef.current = chart;
    seriesRef.current = chart.addCandlestickSeries({
      upColor: "#10b981", downColor: "#ef4444",
      borderUpColor: "#10b981", borderDownColor: "#ef4444",
      wickUpColor: "#10b981", wickDownColor: "#ef4444",
    });
    volRef.current = chart.addHistogramSeries({
      priceFormat: { type: "volume" }, priceScaleId: "",
      color: "rgba(59,130,246,0.4)",
    });
    volRef.current.priceScale().applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
    return () => { chart.remove(); chartRef.current = null; };
  }, [height]);

  // load data on prop change
  useEffect(() => {
    if (!date || !seriesRef.current) return;
    setMsg(null);
    getCandles(underlying, date, interval)
      .then((c) => {
        if (!c.length) { setMsg(`No candles for ${underlying} on ${date}`); seriesRef.current?.setData([]); volRef.current?.setData([]); setCount(0); return; }
        seriesRef.current?.setData(c.map((x) => ({
          time: x.time as UTCTimestamp, open: x.open, high: x.high, low: x.low, close: x.close,
        })));
        volRef.current?.setData(c.map((x) => ({
          time: x.time as UTCTimestamp, value: x.volume,
          color: x.close >= x.open ? "rgba(16,185,129,0.4)" : "rgba(239,68,68,0.4)",
        })));
        setCount(c.length);
        chartRef.current?.timeScale().fitContent();
      })
      .catch((e) => setMsg(e.message));
  }, [underlying, date, interval]);

  return (
    <div className="relative rounded-xl overflow-hidden border border-gray-800">
      <div ref={wrapRef} style={{ height }} />
      {msg && <div className="absolute inset-0 flex items-center justify-center text-gray-500 text-sm bg-gray-950/60">{msg}</div>}
      {!msg && count > 0 && (
        <div className="absolute top-2 left-3 text-[11px] text-gray-500 font-mono pointer-events-none">
          {underlying} · {date} · {interval}m · {count} bars
        </div>
      )}
    </div>
  );
}

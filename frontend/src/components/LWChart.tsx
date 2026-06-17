import { useEffect, useRef, useState } from "react";
import {
  createChart, ColorType, IChartApi, ISeriesApi, UTCTimestamp, LineStyle,
} from "lightweight-charts";
import { getCandles } from "../api";

interface Props {
  underlying: string;
  date: string;
  interval: number;
  height?: number;
  prevDayHigh?: number;
  prevDayLow?: number;
  markers?: Array<{ time: number; position: "aboveBar" | "belowBar"; color: string; shape: "arrowUp" | "arrowDown" | "circle"; text: string }>;
}

function calcEMA(data: number[], period: number): (number | null)[] {
  const result: (number | null)[] = [];
  const k = 2 / (period + 1);
  let ema: number | null = null;
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) {
      result.push(null);
    } else if (i === period - 1) {
      ema = data.slice(0, period).reduce((a, b) => a + b, 0) / period;
      result.push(ema);
    } else {
      ema = data[i] * k + (ema ?? data[i]) * (1 - k);
      result.push(ema);
    }
  }
  return result;
}

function calcVWAP(candles: Array<{ close: number; high: number; low: number; volume: number }>): number[] {
  let cumTP = 0;
  let cumVol = 0;
  return candles.map((c) => {
    const tp = (c.high + c.low + c.close) / 3;
    cumTP += tp * c.volume;
    cumVol += c.volume;
    return cumVol > 0 ? cumTP / cumVol : tp;
  });
}

/**
 * TradingView Lightweight-Charts candlestick with VWAP, EMA 9/21 overlays
 * and previous day high/low reference lines.
 */
export default function LWChart({ underlying, date, interval, height = 460, prevDayHigh, prevDayLow, markers }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const ema9Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ema21Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const vwapRef = useRef<ISeriesApi<"Line"> | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [count, setCount] = useState(0);
  const [overlays, setOverlays] = useState({ vwap: true, ema9: true, ema21: true });

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

    // Overlay line series
    ema9Ref.current = chart.addLineSeries({
      color: "rgba(251,191,36,0.8)", lineWidth: 1, title: "EMA 9",
      priceLineVisible: false, lastValueVisible: false,
    });
    ema21Ref.current = chart.addLineSeries({
      color: "rgba(168,85,247,0.8)", lineWidth: 1, title: "EMA 21",
      priceLineVisible: false, lastValueVisible: false,
    });
    vwapRef.current = chart.addLineSeries({
      color: "rgba(59,130,246,0.9)", lineWidth: 2, title: "VWAP",
      lineStyle: LineStyle.Dashed,
      priceLineVisible: false, lastValueVisible: false,
    });

    return () => { chart.remove(); chartRef.current = null; };
  }, [height]);

  // load data on prop change
  useEffect(() => {
    if (!date || !seriesRef.current) return;
    setMsg(null);
    getCandles(underlying, date, interval)
      .then((c) => {
        if (!c.length) { setMsg(`No candles for ${underlying} on ${date}`); seriesRef.current?.setData([]); volRef.current?.setData([]); ema9Ref.current?.setData([]); ema21Ref.current?.setData([]); vwapRef.current?.setData([]); setCount(0); return; }
        
        // Main candlestick data
        seriesRef.current?.setData(c.map((x) => ({
          time: x.time as UTCTimestamp, open: x.open, high: x.high, low: x.low, close: x.close,
        })));
        volRef.current?.setData(c.map((x) => ({
          time: x.time as UTCTimestamp, value: x.volume,
          color: x.close >= x.open ? "rgba(16,185,129,0.4)" : "rgba(239,68,68,0.4)",
        })));

        // Compute EMA 9
        const closes = c.map((x) => x.close);
        const ema9 = calcEMA(closes, 9);
        ema9Ref.current?.setData(
          c.map((x, i) => ({ time: x.time as UTCTimestamp, value: ema9[i] ?? 0 }))
            .filter((_, i) => ema9[i] !== null)
        );
        // Compute EMA 21
        const ema21 = calcEMA(closes, 21);
        ema21Ref.current?.setData(
          c.map((x, i) => ({ time: x.time as UTCTimestamp, value: ema21[i] ?? 0 }))
            .filter((_, i) => ema21[i] !== null)
        );
        // Compute VWAP
        const vwap = calcVWAP(c);
        vwapRef.current?.setData(
          c.map((x, i) => ({ time: x.time as UTCTimestamp, value: vwap[i] }))
        );

        // Previous day high/low price lines
        if (prevDayHigh && seriesRef.current) {
          seriesRef.current.createPriceLine({
            price: prevDayHigh,
            color: "rgba(16,185,129,0.5)",
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: "Prev High",
          });
        }
        if (prevDayLow && seriesRef.current) {
          seriesRef.current.createPriceLine({
            price: prevDayLow,
            color: "rgba(239,68,68,0.5)",
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: "Prev Low",
          });
        }

        // Entry/exit markers
        if (markers?.length && seriesRef.current) {
          seriesRef.current.setMarkers(
            markers.map((m) => ({
              time: m.time as UTCTimestamp,
              position: m.position,
              color: m.color,
              shape: m.shape,
              text: m.text,
            }))
          );
        }

        setCount(c.length);
        chartRef.current?.timeScale().fitContent();
      })
      .catch((e) => setMsg(e.message));
  }, [underlying, date, interval, prevDayHigh, prevDayLow, markers]);

  // Toggle overlay visibility
  useEffect(() => {
    ema9Ref.current?.applyOptions({ visible: overlays.ema9 });
    ema21Ref.current?.applyOptions({ visible: overlays.ema21 });
    vwapRef.current?.applyOptions({ visible: overlays.vwap });
  }, [overlays]);

  const toggleBtn = (key: keyof typeof overlays, label: string, color: string) => (
    <button
      type="button"
      onClick={() => setOverlays((o) => ({ ...o, [key]: !o[key] }))}
      className={`px-2 py-0.5 rounded text-[9px] font-bold transition-all border ${overlays[key] ? `border-${color} text-${color} bg-${color}/10` : "border-gray-700 text-gray-600"}`}
      style={overlays[key] ? { borderColor: color, color: color, backgroundColor: `${color}15` } : {}}
    >
      {label}
    </button>
  );

  return (
    <div className="relative rounded-xl overflow-hidden border border-gray-800">
      <div ref={wrapRef} style={{ height }} />
      {/* Overlay toggles */}
      <div className="absolute top-2 right-3 flex items-center gap-1 z-10">
        {toggleBtn("vwap", "VWAP", "#3b82f6")}
        {toggleBtn("ema9", "EMA 9", "#fbbf24")}
        {toggleBtn("ema21", "EMA 21", "#a855f7")}
      </div>
      {msg && <div className="absolute inset-0 flex items-center justify-center text-gray-500 text-sm bg-gray-950/60">{msg}</div>}
      {!msg && count > 0 && (
        <div className="absolute top-2 left-3 text-[11px] text-gray-500 font-mono pointer-events-none">
          {underlying} · {date} · {interval}m · {count} bars
        </div>
      )}
    </div>
  );
}


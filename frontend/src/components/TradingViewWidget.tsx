import { useEffect, useRef, memo } from "react";

// Map our underlying codes -> TradingView NSE symbols
export const TV_SYMBOL: Record<string, string> = {
  NIFTY: "NSE:NIFTY",
  BANKNIFTY: "NSE:BANKNIFTY",
  FINNIFTY: "NSE:CNXFINANCE",
  INDIAVIX: "NSE:INDIAVIX",
};

interface Props {
  symbol: string;          // our underlying code or a raw TV symbol
  interval?: string;       // "1","3","5","15","60","D"
  height?: number;
  studies?: string[];      // TV study ids, e.g. ["STD;VWAP","STD;Supertrend"]
}

/**
 * TradingView Advanced Real-Time Chart embed. Loads the official TV widget
 * script per instance. Real live NSE data + full TV indicator UI.
 */
function TradingViewWidget({ symbol, interval = "15", height = 480, studies }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const tvSymbol = TV_SYMBOL[symbol] ?? symbol;
    ref.current.innerHTML = ""; // reset on prop change

    const container = document.createElement("div");
    container.className = "tradingview-widget-container__widget";
    container.style.height = `${height}px`;
    container.style.width = "100%";
    ref.current.appendChild(container);

    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.type = "text/javascript";
    script.async = true;
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol: tvSymbol,
      interval,
      timezone: "Asia/Kolkata",
      theme: "dark",
      style: "1",
      locale: "in",
      enable_publishing: false,
      allow_symbol_change: true,
      hide_side_toolbar: false,
      details: true,
      studies: studies ?? ["STD;VWAP", "STD;RSI"],
      backgroundColor: "rgba(3, 7, 18, 1)",
      gridColor: "rgba(55, 65, 81, 0.3)",
      support_host: "https://www.tradingview.com",
    });
    ref.current.appendChild(script);
  }, [symbol, interval, height, studies]);

  return (
    <div className="tradingview-widget-container rounded-xl overflow-hidden border border-gray-800" ref={ref} style={{ height }}>
      <div className="tradingview-widget-container__widget" style={{ height }} />
    </div>
  );
}

export default memo(TradingViewWidget);

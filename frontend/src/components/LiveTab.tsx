import { useEffect, useRef, useState, useCallback } from "react";

interface IndexRow { ltp: number }
interface AtmRow {
  strike: number; expiry: string;
  ce_ltp: number | null; pe_ltp: number | null;
  ce_oi:  number | null; pe_oi:  number | null;
}
interface Snap {
  status: string; ts: string; source: string;
  indices: Record<string, IndexRow>;
  atm:     Record<string, AtmRow>;
  error?:  string; msg?: string;
}

type WsState = "connecting" | "open" | "closed" | "error";

const UNDERLYINGS = ["NIFTY", "BANKNIFTY"] as const;

function fmt2(n: number | null | undefined) {
  if (n == null) return "—";
  return n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtOI(n: number | null | undefined) {
  if (n == null) return "—";
  if (n >= 1e7) return `${(n / 1e7).toFixed(2)}Cr`;
  if (n >= 1e5) return `${(n / 1e5).toFixed(1)}L`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}K`;
  return String(n);
}

const FATAL_ERRORS = new Set(["no_session", "token_expired"]);

function useUpstoxWs() {
  const [snap, setSnap]       = useState<Snap | null>(null);
  const [wsState, setWsState] = useState<WsState>("connecting");
  const wsRef  = useRef<WebSocket | null>(null);
  const retry  = useRef<ReturnType<typeof setTimeout> | null>(null);
  const delay  = useRef(1000);
  const fatal  = useRef(false);

  const connect = useCallback(() => {
    if (wsRef.current) wsRef.current.close();
    fatal.current = false;
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url   = `${proto}//${window.location.host}/api/ws/live`;
    const ws    = new WebSocket(url);
    wsRef.current = ws;
    setWsState("connecting");

    ws.onopen  = () => { setWsState("open"); delay.current = 1000; };
    ws.onclose = () => {
      setWsState("closed");
      if (fatal.current) return;   // no_session / token_expired — don't retry
      retry.current = setTimeout(() => {
        delay.current = Math.min(delay.current * 2, 30000);
        connect();
      }, delay.current);
    };
    ws.onerror = () => setWsState("error");
    ws.onmessage = (e) => {
      try {
        const data: Snap = JSON.parse(e.data);
        if (data.error && FATAL_ERRORS.has(data.error)) fatal.current = true;
        setSnap(data);
      } catch {}
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (retry.current) clearTimeout(retry.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { snap, wsState, retry: connect };
}

function StatusDot({ wsState, snap }: { wsState: WsState; snap: Snap | null }) {
  const ok = wsState === "open" && snap?.status === "ok";
  const color = ok ? "bg-green-500 animate-pulse" :
    wsState === "connecting" ? "bg-yellow-500" : "bg-red-500";
  const label = ok ? `Live · ${snap!.ts} UTC` :
    wsState === "connecting" ? "Connecting…" :
    wsState === "closed"     ? "Reconnecting…" : "Error";
  return (
    <div className="flex items-center gap-2 text-xs text-gray-400">
      <span className={`w-2 h-2 rounded-full ${color}`} />
      <span>{label}</span>
      <span className="text-gray-700">·</span>
      <span className="text-gray-600">Upstox</span>
    </div>
  );
}

function IndexCard({ ul, snap }: { ul: string; snap: Snap | null }) {
  const spot = snap?.indices?.[ul];
  const atm  = snap?.atm?.[ul];

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <span className="text-sm font-bold tracking-wide text-gray-200">{ul}</span>
        {atm && (
          <span className="text-xs text-gray-500 bg-gray-800 px-2 py-0.5 rounded">
            {atm.expiry} · ATM {atm.strike}
          </span>
        )}
      </div>

      {/* Spot */}
      <div className="text-3xl font-bold text-white tabular-nums mb-4">
        {fmt2(spot?.ltp)}
      </div>

      {/* ATM options */}
      {atm ? (
        <div className="grid grid-cols-2 gap-3">
          {[
            { label: `${atm.strike} CE`, ltp: atm.ce_ltp, oi: atm.ce_oi, color: "text-green-400" },
            { label: `${atm.strike} PE`, ltp: atm.pe_ltp, oi: atm.pe_oi, color: "text-red-400"   },
          ].map(({ label, ltp, oi, color }) => (
            <div key={label} className="bg-gray-800 rounded-lg p-3 text-center">
              <div className="text-xs text-gray-500 mb-1">{label}</div>
              <div className={`text-lg font-semibold tabular-nums ${color}`}>{fmt2(ltp)}</div>
              <div className="text-xs text-gray-600 mt-0.5">{fmtOI(oi)} OI</div>
            </div>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3">
          {["CE", "PE"].map((t) => (
            <div key={t} className="bg-gray-800 rounded-lg p-3 text-center animate-pulse">
              <div className="text-xs text-gray-600 mb-1">{t}</div>
              <div className="text-gray-700 font-semibold">—</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function LiveTab() {
  const { snap, wsState, retry } = useUpstoxWs();

  if (snap?.error) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3">
        <div className="text-red-400 font-semibold">{snap.error}</div>
        {snap.msg && <div className="text-sm text-gray-500">{snap.msg}</div>}
        <button
          onClick={retry}
          className="mt-2 px-4 py-1.5 text-xs bg-blue-700 hover:bg-blue-600 rounded text-white"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-5 max-w-3xl">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-100">Live Market Feed</h2>
        <StatusDot wsState={wsState} snap={snap} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {UNDERLYINGS.map((ul) => (
          <IndexCard key={ul} ul={ul} snap={snap} />
        ))}
      </div>

      {!snap && wsState !== "error" && (
        <div className="text-center text-gray-600 py-8 text-sm">
          {wsState === "connecting" ? "Connecting to Upstox feed…" : "Reconnecting…"}
        </div>
      )}

      {snap?.status && snap.status !== "ok" && (
        <div className="text-xs text-yellow-600 bg-yellow-950/30 border border-yellow-900 rounded px-3 py-2">
          Feed status: {snap.status}
          {snap.status === "token_expired" && " — run: python scripts/upstox_oauth.py"}
        </div>
      )}

      <div className="text-xs text-gray-700 pt-2">
        Spot: 1s refresh · ATM options: 10s refresh · Options chain from next weekly expiry
      </div>
    </div>
  );
}

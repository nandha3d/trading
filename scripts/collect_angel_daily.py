"""
Angel One daily 1-min candle collector — runs after market close (15:30 IST).

Headless TOTP auto-login. No browser required. Perfect for server cron.

Fetches OHLCV (note: Angel One historical has NO OI in 1-min data — use
backfill_upstox.py for OI-accurate history. Going forward, live WebSocket
in angelone_feed.py captures OI in real time.)

Usage
-----
  python scripts/collect_angel_daily.py             # today
  python scripts/collect_angel_daily.py 2026-06-13  # specific past date
  python scripts/collect_angel_daily.py --atm 30    # ATM ± 30 strikes (default 40)
  python scripts/collect_angel_daily.py --all-expiries  # all future expiries

Cron (add to crontab -e) — 16:15 IST = 10:45 UTC:
  45 10 * * 1-5 cd /opt/trading && python scripts/collect_angel_daily.py >> logs/angel_daily.log 2>&1
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings          # noqa: E402
from src.data import storage         # noqa: E402
from src.data import angelone_scrip as scrip  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MARKET_OPEN_M  = 9 * 60 + 15   # 09:15 in minutes
MARKET_CLOSE_M = 15 * 60 + 30  # 15:30 in minutes
RATE_PER_SEC   = 3              # Angel One historical: ~3 req/s safe
SPOT_TOKENS    = scrip.INDEX_SPOT_TOKENS  # {"NIFTY": "26000", "BANKNIFTY": "26009"}
STEP           = {"NIFTY": 50, "BANKNIFTY": 100}
UNDERLYINGS    = ("NIFTY", "BANKNIFTY")

# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def _login():
    """TOTP-based headless login. Returns (SmartConnect, jwt_token)."""
    try:
        from SmartApi import SmartConnect
        import pyotp
    except ImportError:
        sys.exit("Missing packages. Run: pip install smartapi-python pyotp")

    if not settings.angelone_ready:
        sys.exit("Angel One credentials missing in .env — need ANGELONE_API_KEY, "
                 "ANGELONE_CLIENT_CODE, ANGELONE_PIN, ANGELONE_TOTP_SECRET")

    sc   = SmartConnect(api_key=settings.angelone_api_key)
    totp = pyotp.TOTP(settings.angelone_totp_secret).now()
    res  = sc.generateSession(settings.angelone_client_code, settings.angelone_pin, totp)

    if not (res and res.get("status")):
        sys.exit(f"Angel One login failed: {res.get('message') if res else 'no response'}")

    jwt = res["data"]["jwtToken"]
    print(f"[angel] logged in as {settings.angelone_client_code}", flush=True)
    return sc, jwt


# ---------------------------------------------------------------------------
# Rate-limited candle fetch
# ---------------------------------------------------------------------------

_last_call = 0.0


def _rate_gate() -> None:
    global _last_call
    gap  = 1.0 / RATE_PER_SEC
    wait = gap - (time.time() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.time()


def _fetch_candles(sc, token: str, exchange: str, symbol_token: str,
                   from_dt: datetime, to_dt: datetime,
                   retries: int = 3) -> list[list]:
    params = {
        "exchange":    exchange,
        "symboltoken": symbol_token,
        "interval":    "ONE_MINUTE",
        "fromdate":    from_dt.strftime("%Y-%m-%d %H:%M"),
        "todate":      to_dt.strftime("%Y-%m-%d %H:%M"),
    }
    delay = 2.0
    for attempt in range(retries):
        _rate_gate()
        try:
            res = sc.getCandleData(params)
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(delay); delay *= 2
                continue
            print(f"    [error] {e}")
            return []

        if not res:
            return []
        if res.get("status") is True or res.get("status") == "true":
            return res.get("data") or []
        # Angel returns errorcode "AB1002" or similar for bad token / no data
        code = res.get("errorcode", "")
        if code in ("AB1002", "AB1004", "AB2000"):
            return []  # no data for this instrument/period
        msg = res.get("message", "")
        print(f"    [angel api] {code}: {msg}")
        if attempt < retries - 1:
            time.sleep(delay); delay *= 2

    return []


# ---------------------------------------------------------------------------
# Candle parsing
# ---------------------------------------------------------------------------

def _parse_ts(s: str) -> datetime:
    """'2026-06-13T09:15:00+05:30' -> naive IST datetime."""
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")


def _candles_to_options_df(
    candles: list[list],
    underlying: str,
    expiry: date,
    strike: int,
    opt_type: str,
) -> pl.DataFrame:
    rows = []
    for c in candles:
        if len(c) < 6:
            continue
        close = float(c[4] or 0)
        if close <= 0:
            continue
        rows.append({
            "underlying":  underlying,
            "expiry":      expiry,
            "strike":      strike,
            "option_type": opt_type,
            "ts":          _parse_ts(c[0]),
            "open":        float(c[1] or 0),
            "high":        float(c[2] or 0),
            "low":         float(c[3] or 0),
            "close":       close,
            "volume":      int(c[5] or 0),
            "oi":          0,  # Angel One historical has no OI
        })
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame(rows).with_columns([
        pl.col("underlying").cast(pl.Utf8),
        pl.col("expiry").cast(pl.Date),
        pl.col("strike").cast(pl.Int32),
        pl.col("option_type").cast(pl.Utf8),
        pl.col("ts").cast(pl.Datetime("us")),
        pl.col("open").cast(pl.Float64),
        pl.col("high").cast(pl.Float64),
        pl.col("low").cast(pl.Float64),
        pl.col("close").cast(pl.Float64),
        pl.col("volume").cast(pl.Int64),
        pl.col("oi").cast(pl.Int64),
    ])


def _candles_to_spot_df(candles: list[list], underlying: str) -> pl.DataFrame:
    rows = []
    for c in candles:
        if len(c) < 5:
            continue
        rows.append({
            "underlying": underlying,
            "ts":         _parse_ts(c[0]),
            "open":       float(c[1] or 0),
            "high":       float(c[2] or 0),
            "low":        float(c[3] or 0),
            "close":      float(c[4] or 0),
            "volume":     int(c[5]) if len(c) > 5 and c[5] else 0,
        })
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame(rows).with_columns([
        pl.col("underlying").cast(pl.Utf8),
        pl.col("ts").cast(pl.Datetime("us")),
        pl.col("open").cast(pl.Float64),
        pl.col("high").cast(pl.Float64),
        pl.col("low").cast(pl.Float64),
        pl.col("close").cast(pl.Float64),
        pl.col("volume").cast(pl.Int64),
    ])


# ---------------------------------------------------------------------------
# ATM strike estimation
# ---------------------------------------------------------------------------

def _approx_atm(und: str, scrip_master: list[dict]) -> int | None:
    """Estimate ATM from last_price in scrip master (good enough for ATM window)."""
    # Angel One scrip master has 'last_price' for spot indices... but often 0.
    # Fall back to median of active strikes.
    tok_map = scrip.resolve_option_tokens(und, _nearest_expiry(und, scrip_master),
                                          scrip=scrip_master)
    if not tok_map:
        return None
    strikes = sorted({v["strike"] for v in tok_map.values()})
    if not strikes:
        return None
    return strikes[len(strikes) // 2]


def _nearest_expiry(und: str, scrip_master: list[dict]) -> str:
    expiries = scrip.list_expiries(und, scrip=scrip_master)
    today_str = date.today().isoformat()
    future = [e for e in expiries if e >= today_str]
    return future[0] if future else (expiries[-1] if expiries else "")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Angel One daily 1-min candle collector")
    p.add_argument("date", nargs="?",
                   help="Trade date YYYY-MM-DD (default: today)")
    p.add_argument("--atm", type=int, default=40,
                   help="Collect ATM ± N strikes per expiry (default 40)")
    p.add_argument("--all-expiries", action="store_true",
                   help="Collect all future expiries (default: nearest 3 per underlying)")
    return p.parse_args()


def main() -> None:
    args      = parse_args()
    trade_day = date.fromisoformat(args.date) if args.date else date.today()
    frm_dt    = datetime(trade_day.year, trade_day.month, trade_day.day, 9, 15)
    to_dt     = datetime(trade_day.year, trade_day.month, trade_day.day, 15, 30)

    if trade_day.weekday() >= 5:
        sys.exit(f"{trade_day} is a weekend — no market data")

    print(f"[angel] collecting {trade_day}  {frm_dt.strftime('%H:%M')}→"
          f"{to_dt.strftime('%H:%M')}", flush=True)

    sc, _jwt  = _login()
    master    = scrip.fetch_scrip_master(max_age_hours=8)
    storage.init_db()

    total_rows = 0

    for und in UNDERLYINGS:
        all_exp = scrip.list_expiries(und, scrip=master)
        today_s = trade_day.isoformat()
        # Keep expiries that cover this trade date (expiry >= trade_day)
        active_exp = [e for e in all_exp if e >= today_s]
        if not active_exp:
            print(f"[angel] no active expiries for {und} on {trade_day}")
            continue

        # Limit to nearest 3 unless --all-expiries
        if not args.all_expiries:
            active_exp = active_exp[:3]

        print(f"[angel] {und}: {len(active_exp)} expir(ies): {active_exp}", flush=True)

        # Estimate ATM from median strike of nearest expiry
        nearest_tok_map = scrip.resolve_option_tokens(und, active_exp[0], scrip=master)
        if nearest_tok_map:
            strikes_sorted = sorted({v["strike"] for v in nearest_tok_map.values()})
            atm_est = strikes_sorted[len(strikes_sorted) // 2]
        else:
            atm_est = None

        step = STEP.get(und, 50)

        for exp_iso in active_exp:
            exp_date = date.fromisoformat(exp_iso)

            # Resolve all tokens for this expiry
            tok_map = scrip.resolve_option_tokens(und, exp_iso, scrip=master)
            if not tok_map:
                print(f"  [skip] no tokens for {und} {exp_iso}")
                continue

            # ATM filter
            if atm_est and not args.all_expiries:
                lo = atm_est - args.atm * step
                hi = atm_est + args.atm * step
                tok_map = {t: v for t, v in tok_map.items()
                           if lo <= v["strike"] <= hi}

            print(f"  [angel] {und} {exp_iso}: {len(tok_map)} instruments", flush=True)
            exp_rows = 0

            for token, meta in tok_map.items():
                strike   = meta["strike"]
                opt_type = meta["opt_type"]

                candles = _fetch_candles(sc, token, "NFO", token, frm_dt, to_dt)
                if not candles:
                    continue
                df = _candles_to_options_df(candles, und, exp_date, strike, opt_type)
                if not df.is_empty():
                    n = storage.write_options(df)
                    exp_rows += n

            print(f"  [angel] {und} {exp_iso}: wrote {exp_rows} rows", flush=True)
            total_rows += exp_rows

    # ---- spot index ----
    print("[angel] Fetching spot index candles...", flush=True)
    for und in UNDERLYINGS:
        spot_tok = SPOT_TOKENS.get(und)
        if not spot_tok:
            continue
        candles = _fetch_candles(sc, spot_tok, "NSE", spot_tok, frm_dt, to_dt)
        if candles:
            df = _candles_to_spot_df(candles, und)
            if not df.is_empty():
                n = storage.write_spot(df)
                print(f"  [angel] spot {und}: {n} rows", flush=True)
                total_rows += n

    print(f"\n[angel] DONE — {total_rows:,} total rows written for {trade_day}",
          flush=True)


if __name__ == "__main__":
    main()

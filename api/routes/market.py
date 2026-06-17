from __future__ import annotations
import asyncio
from datetime import date, datetime, time, timedelta
from typing import Optional, List, Dict
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
import polars as pl
import numpy as np

from src.data import storage
from src.analysis.oi_interpret import classify_oi, bias_of, Interp
from src.analysis.resample import resample_spot

router = APIRouter()

class SpotSnapshot(BaseModel):
    ltp: float
    open: float
    high: float
    low: float
    prev_close: float
    change: float
    change_pct: float

class FinniftySnapshot(BaseModel):
    ltp: Optional[float] = None
    change: Optional[float] = None
    change_pct: Optional[float] = None

class MarketSnapshotResponse(BaseModel):
    underlying: str
    timestamp: str
    source: str
    spot: SpotSnapshot
    regime: str
    freshness_seconds: int
    vix: Optional[float] = None
    finnifty: Optional[FinniftySnapshot] = None

class CandleOut(BaseModel):
    ts: str
    open: float
    high: float
    low: float
    close: float
    volume: int

class CandlesResponse(BaseModel):
    underlying: str
    interval: str
    candles: List[CandleOut]

class OiBuildupRow(BaseModel):
    strike: int
    option_type: str
    ltp: float
    price_change: float
    oi: int
    oi_change: int
    classification: str
    bias: str

class OiBuildupResponse(BaseModel):
    underlying: str
    expiry: str
    rows: List[OiBuildupRow]

class LevelOut(BaseModel):
    level: float
    type: str  # SUPPORT or RESISTANCE
    source: str
    strength: int

class LevelsResponse(BaseModel):
    underlying: str
    levels: List[LevelOut]

class AlertOut(BaseModel):
    code: str
    severity: str  # INFO, MEDIUM, HIGH
    message: str
    timestamp: str

class AlertsResponse(BaseModel):
    underlying: str
    alerts: List[AlertOut]


def _detect_regime(spot_df: pl.DataFrame, ltp: float) -> str:
    """Classify current market regime based on technical indicators."""
    if spot_df.height < 5:
        return "LOW_VOLATILITY"
    
    closes = spot_df["close"].to_numpy()
    volumes = spot_df["volume"].to_numpy()
    
    # Calculate daily VWAP
    cum_pv = np.cumsum(closes * volumes)
    cum_v = np.cumsum(volumes)
    vwap = cum_pv[-1] / cum_v[-1] if cum_v[-1] > 0 else ltp
    
    # Simple EMA9 / EMA21 calculation
    def calc_ema(arr: np.ndarray, period: int) -> float:
        alpha = 2 / (period + 1)
        ema = arr[0]
        for val in arr[1:]:
            ema = val * alpha + ema * (1 - alpha)
        return ema
        
    ema9 = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21)
    
    # Measure volatility (std dev of percentage changes)
    pct_changes = np.diff(closes) / closes[:-1]
    vol = np.std(pct_changes) if len(pct_changes) > 0 else 0.0
    
    if vol > 0.0015:  # High intraday std dev
        return "VOLATILE"
    elif vol < 0.0003:
        return "LOW_VOLATILITY"
    
    if ltp > vwap and ema9 > ema21:
        return "BULLISH_TREND"
    elif ltp < vwap and ema9 < ema21:
        return "BEARISH_TREND"
        
    return "SIDEWAYS"


def _get_market_snapshot(underlying: str) -> MarketSnapshotResponse:
    storage.init_db()
    con = storage.db().cursor()
    try:
        und = underlying.upper()
        # Find latest available timestamp for spot
        max_ts_row = con.execute(
            "SELECT MAX(ts) FROM spot_1m WHERE underlying = ?", [und]
        ).fetchone()
        
        if not max_ts_row or not max_ts_row[0]:
            # Fallback mock for empty database
            latest_ts = datetime.now()
            return MarketSnapshotResponse(
                underlying=und,
                timestamp=latest_ts.isoformat(),
                source="mock",
                spot=SpotSnapshot(
                    ltp=23000.0 if und == "NIFTY" else (50000.0 if und == "BANKNIFTY" else 20500.0),
                    open=22950.0 if und == "NIFTY" else (49900.0 if und == "BANKNIFTY" else 20450.0),
                    high=23100.0 if und == "NIFTY" else (50200.0 if und == "BANKNIFTY" else 20600.0),
                    low=22900.0 if und == "NIFTY" else (49800.0 if und == "BANKNIFTY" else 20400.0),
                    prev_close=22900.0 if und == "NIFTY" else (49850.0 if und == "BANKNIFTY" else 20400.0),
                    change=100.0,
                    change_pct=0.43
                ),
                regime="SIDEWAYS",
                freshness_seconds=1,
                vix=15.4,
                finnifty=FinniftySnapshot(ltp=20500.0, change=50.0, change_pct=0.24)
            )
            
        latest_ts = max_ts_row[0]
        latest_date = latest_ts.date()
        
        # Get all candles for that day
        day_start = datetime.combine(latest_date, time(9, 15))
        day_end = datetime.combine(latest_date, time(15, 30))
        
        spot_day = con.execute(
            "SELECT ts, open, high, low, close, volume FROM spot_1m WHERE underlying = ? AND ts >= ? AND ts <= ? ORDER BY ts",
            [und, day_start, day_end]
        ).pl()
        
        if spot_day.is_empty():
            raise ValueError(f"No daily spot candles found for {und} on {latest_date}")
            
        ltp = spot_day["close"][-1]
        open_val = spot_day["open"][0]
        high_val = spot_day["high"].max()
        low_val = spot_day["low"].min()
        
        # Find prev day close
        prev_close_row = con.execute(
            "SELECT close FROM spot_1m WHERE underlying = ? AND ts < ? ORDER BY ts DESC LIMIT 1",
            [und, day_start]
        ).fetchone()
        
        prev_close = prev_close_row[0] if prev_close_row else open_val
        change = ltp - prev_close
        change_pct = (change / prev_close) * 100 if prev_close else 0.0
        
        # Regime detection
        regime = _detect_regime(spot_day, ltp)
        
        # Fetch India VIX if exists
        vix_row = con.execute(
            "SELECT close FROM spot_1m WHERE underlying IN ('INDIAVIX', 'VIX') AND ts <= ? ORDER BY ts DESC LIMIT 1",
            [latest_ts]
        ).fetchone()
        vix = vix_row[0] if vix_row else None
        
        # Fetch FINNIFTY if exists
        finnifty = None
        fin_row = con.execute(
            "SELECT close FROM spot_1m WHERE underlying = 'FINNIFTY' AND ts <= ? ORDER BY ts DESC LIMIT 1",
            [latest_ts]
        ).fetchone()
        if fin_row:
            fin_ltp = fin_row[0]
            fin_prev_row = con.execute(
                "SELECT close FROM spot_1m WHERE underlying = 'FINNIFTY' AND ts < ? ORDER BY ts DESC LIMIT 1",
                [day_start]
            ).fetchone()
            fin_prev = fin_prev_row[0] if fin_prev_row else fin_ltp
            fin_change = fin_ltp - fin_prev
            fin_pct = (fin_change / fin_prev) * 100 if fin_prev else 0.0
            finnifty = FinniftySnapshot(ltp=round(fin_ltp, 2), change=round(fin_change, 2), change_pct=round(fin_pct, 4))
        
        return MarketSnapshotResponse(
            underlying=und,
            timestamp=latest_ts.isoformat(),
            source="lake",
            spot=SpotSnapshot(
                ltp=round(ltp, 2),
                open=round(open_val, 2),
                high=round(high_val, 2),
                low=round(low_val, 2),
                prev_close=round(prev_close, 2),
                change=round(change, 2),
                change_pct=round(change_pct, 4)
            ),
            regime=regime,
            freshness_seconds=1,
            vix=vix,
            finnifty=finnifty
        )
    finally:
        con.close()


def _get_market_candles(underlying: str, interval: str, from_date: str, to_date: str) -> List[CandleOut]:
    storage.init_db()
    und = underlying.upper()
    
    # Convert interval string (e.g., "5m", "15m", "1d") to minutes
    if interval.endswith("m"):
        int_mins = int(interval[:-1])
    elif interval.endswith("h"):
        int_mins = int(interval[:-1]) * 60
    elif interval.endswith("d"):
        int_mins = 375  # full market day in minutes approximately
    else:
        int_mins = int(interval)
        
    start_dt = datetime.combine(date.fromisoformat(from_date.split("T")[0].split(" ")[0]), time(9, 15))
    end_dt = datetime.combine(date.fromisoformat(to_date.split("T")[0].split(" ")[0]), time(15, 30))
    
    df = storage.read_spot(und, start_dt, end_dt)
    if df.is_empty():
        return []
        
    # Resample candles
    resampled = resample_spot(df, int_mins).sort("ts")
    
    out = []
    for r in resampled.iter_rows(named=True):
        out.append(CandleOut(
            ts=r["ts"].isoformat(),
            open=round(r["open"], 2),
            high=round(r["high"], 2),
            low=round(r["low"], 2),
            close=round(r["close"], 2),
            volume=int(r["volume"] or 0)
        ))
    return out


def _get_oi_buildup(underlying: str, expiry: str) -> List[OiBuildupRow]:
    storage.init_db()
    con = storage.db().cursor()
    try:
        und = underlying.upper()
        exp_date = date.fromisoformat(expiry.split("T")[0].split(" ")[0])
        
        # Get latest timestamp in options_1m
        max_ts_row = con.execute(
            "SELECT MAX(ts) FROM options_1m WHERE underlying = ? AND expiry = ?",
            [und, exp_date]
        ).fetchone()
        
        if not max_ts_row or not max_ts_row[0]:
            return []
            
        latest_ts = max_ts_row[0]
        day_date = latest_ts.date()
        
        # Get options chain snapshot at latest_ts
        rows = con.execute(
            "SELECT strike, option_type, close, oi, volume FROM options_1m WHERE underlying = ? AND expiry = ? AND ts = ?",
            [und, exp_date, latest_ts]
        ).fetchall()
        
        # Get open price/oi for the day (for change computations)
        open_ts_row = con.execute(
            "SELECT MIN(ts) FROM options_1m WHERE underlying = ? AND expiry = ? AND CAST(ts AS DATE) = ?",
            [und, exp_date, day_date]
        ).fetchone()
        
        open_map = {}
        if open_ts_row and open_ts_row[0]:
            open_rows = con.execute(
                "SELECT strike, option_type, close, oi FROM options_1m WHERE underlying = ? AND expiry = ? AND ts = ?",
                [und, exp_date, open_ts_row[0]]
            ).fetchall()
            for s, ot, c, o in open_rows:
                open_map[(s, ot)] = {"close": c or 0.0, "oi": o or 0}
                
        out = []
        for strike, opt_type, close, oi, volume in rows:
            c_val = close or 0.0
            oi_val = oi or 0
            
            # Retrieve open values
            o_data = open_map.get((strike, opt_type), {"close": c_val, "oi": oi_val})
            p_chg = c_val - o_data["close"]
            oi_chg = oi_val - o_data["oi"]
            
            interp = classify_oi(p_chg, oi_chg)
            
            # Determine bias
            bias = "NEUTRAL"
            if interp != Interp.NEUTRAL:
                bias_num = bias_of(interp)
                if opt_type == "CE":
                    bias = "BULLISH" if bias_num > 0 else "BEARISH"
                else:  # PE
                    bias = "BEARISH" if bias_num > 0 else "BULLISH"
                    
            out.append(OiBuildupRow(
                strike=strike,
                option_type=opt_type,
                ltp=round(c_val, 2),
                price_change=round(p_chg, 2),
                oi=oi_val,
                oi_change=oi_chg,
                classification=interp.name,
                bias=bias
            ))
            
        return sorted(out, key=lambda x: (x.strike, x.option_type))
    finally:
        con.close()


def _get_market_levels(underlying: str, expiry: str) -> List[LevelOut]:
    storage.init_db()
    con = storage.db().cursor()
    try:
        und = underlying.upper()
        exp_date = date.fromisoformat(expiry.split("T")[0].split(" ")[0])
        
        # Get latest spot snapshot
        max_ts_row = con.execute(
            "SELECT MAX(ts) FROM spot_1m WHERE underlying = ?", [und]
        ).fetchone()
        
        if not max_ts_row or not max_ts_row[0]:
            return []
            
        latest_ts = max_ts_row[0]
        latest_date = latest_ts.date()
        
        day_start = datetime.combine(latest_date, time(9, 15))
        day_end = datetime.combine(latest_date, time(15, 30))
        
        spot_day = con.execute(
            "SELECT ts, open, high, low, close FROM spot_1m WHERE underlying = ? AND ts >= ? AND ts <= ? ORDER BY ts",
            [und, day_start, day_end]
        ).pl()
        
        if spot_day.is_empty():
            return []
            
        ltp = spot_day["close"][-1]
        day_high = spot_day["high"].max()
        day_low = spot_day["low"].min()
        
        # Previous Day high/low
        prev_day_row = con.execute(
            "SELECT ts FROM spot_1m WHERE underlying = ? AND ts < ? ORDER BY ts DESC LIMIT 1",
            [und, day_start]
        ).fetchone()
        
        prev_high = ltp
        prev_low = ltp
        if prev_day_row:
            p_date = prev_day_row[0].date()
            prev_spot_day = con.execute(
                "SELECT high, low FROM spot_1m WHERE underlying = ? AND CAST(ts AS DATE) = ?",
                [und, p_date]
            ).pl()
            if not prev_spot_day.is_empty():
                prev_high = prev_spot_day["high"].max()
                prev_low = prev_spot_day["low"].min()
                
        # Highest CE and PE OI strikes
        oi_ts_row = con.execute(
            "SELECT MAX(ts) FROM options_1m WHERE underlying = ? AND expiry = ?",
            [und, exp_date]
        ).fetchone()
        
        highest_ce_strike = None
        highest_pe_strike = None
        if oi_ts_row and oi_ts_row[0]:
            oi_snap = con.execute(
                "SELECT strike, option_type, oi FROM options_1m WHERE underlying = ? AND expiry = ? AND ts = ?",
                [und, exp_date, oi_ts_row[0]]
            ).fetchall()
            
            ce_oi = [r for r in oi_snap if r[1] == "CE" and r[2] is not None]
            pe_oi = [r for r in oi_snap if r[1] == "PE" and r[2] is not None]
            
            if ce_oi:
                highest_ce_strike = max(ce_oi, key=lambda x: x[2])[0]
            if pe_oi:
                highest_pe_strike = max(pe_oi, key=lambda x: x[2])[0]
                
        levels = []
        # Previous Day High / Low
        levels.append(LevelOut(level=round(prev_high, 2), type="RESISTANCE", source="PREV_DAY_HIGH", strength=6))
        levels.append(LevelOut(level=round(prev_low, 2), type="SUPPORT", source="PREV_DAY_LOW", strength=6))
        
        # Current Day High / Low
        levels.append(LevelOut(level=round(day_high, 2), type="RESISTANCE", source="CURRENT_DAY_HIGH", strength=5))
        levels.append(LevelOut(level=round(day_low, 2), type="SUPPORT", source="CURRENT_DAY_LOW", strength=5))
        
        # Max Option Chain OI
        if highest_ce_strike:
            levels.append(LevelOut(level=float(highest_ce_strike), type="RESISTANCE", source="HIGHEST_CE_OI", strength=8))
        if highest_pe_strike:
            levels.append(LevelOut(level=float(highest_pe_strike), type="SUPPORT", source="HIGHEST_PE_OI", strength=8))
            
        # Round levels near spot
        step = 500 if und == "BANKNIFTY" else 100
        round_res = int(np.ceil(ltp / step) * step)
        round_sup = int(np.floor(ltp / step) * step)
        levels.append(LevelOut(level=float(round_res), type="RESISTANCE", source="ROUND_LEVEL", strength=3))
        levels.append(LevelOut(level=float(round_sup), type="SUPPORT", source="ROUND_LEVEL", strength=3))
        
        # Deduplicate and sort
        seen = set()
        dedup_levels = []
        for lv in sorted(levels, key=lambda x: x.level):
            if lv.level not in seen:
                seen.add(lv.level)
                dedup_levels.append(lv)
        return dedup_levels
    finally:
        con.close()


def _get_market_alerts(underlying: str) -> List[AlertOut]:
    storage.init_db()
    con = storage.db().cursor()
    try:
        und = underlying.upper()
        # Find latest spot candle
        max_ts_row = con.execute(
            "SELECT MAX(ts) FROM spot_1m WHERE underlying = ?", [und]
        ).fetchone()
        
        if not max_ts_row or not max_ts_row[0]:
            return []
            
        latest_ts = max_ts_row[0]
        latest_date = latest_ts.date()
        
        spot_day = con.execute(
            "SELECT ts, open, high, low, close, volume FROM spot_1m WHERE underlying = ? AND CAST(ts AS DATE) = ? ORDER BY ts",
            [und, latest_date]
        ).pl()
        
        if spot_day.is_empty():
            return []
            
        closes = spot_day["close"].to_numpy()
        volumes = spot_day["volume"].to_numpy()
        
        ltp = closes[-1]
        day_high = spot_day["high"].max()
        day_low = spot_day["low"].min()
        
        # Calculate daily VWAP
        cum_pv = np.cumsum(closes * volumes)
        cum_v = np.cumsum(volumes)
        vwap = cum_pv[-1] / cum_v[-1] if cum_v[-1] > 0 else ltp
        
        alerts = []
        now_str = latest_ts.isoformat()
        
        # VWAP crossover alerts
        if len(closes) >= 2:
            prev_close = closes[-2]
            prev_vwap = (cum_pv[-2] / cum_v[-2]) if cum_v[-2] > 0 else prev_close
            
            if prev_close < prev_vwap and ltp >= vwap:
                alerts.append(AlertOut(
                    code="VWAP_CROSS_ABOVE",
                    severity="MEDIUM",
                    message=f"Spot price {ltp:.2f} crossed above VWAP {vwap:.2f}",
                    timestamp=now_str
                ))
            elif prev_close > prev_vwap and ltp <= vwap:
                alerts.append(AlertOut(
                    code="VWAP_CROSS_BELOW",
                    severity="MEDIUM",
                    message=f"Spot price {ltp:.2f} crossed below VWAP {vwap:.2f}",
                    timestamp=now_str
                ))
                
        # Day breakouts
        if ltp == day_high:
            alerts.append(AlertOut(
                code="DAY_HIGH_BREAK",
                severity="HIGH",
                message=f"Spot price {ltp:.2f} breaks day high {day_high:.2f}",
                timestamp=now_str
            ))
        elif ltp == day_low:
            alerts.append(AlertOut(
                code="DAY_LOW_BREAK",
                severity="HIGH",
                message=f"Spot price {ltp:.2f} breaks day low {day_low:.2f}",
                timestamp=now_str
            ))
            
        return alerts
    finally:
        con.close()


@router.get("/market/snapshot", response_model=MarketSnapshotResponse)
async def get_market_snapshot(underlying: str = "NIFTY"):
    try:
        return await asyncio.to_thread(_get_market_snapshot, underlying)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"Error generating snapshot: {e}")


@router.get("/market/candles", response_model=CandlesResponse)
async def get_market_candles(
    underlying: str = Query(...),
    interval: str = Query("5m"),
    from_date: str = Query(...),
    to_date: str = Query(...)
):
    try:
        candles = await asyncio.to_thread(_get_market_candles, underlying, interval, from_date, to_date)
        return CandlesResponse(underlying=underlying.upper(), interval=interval, candles=candles)
    except Exception as e:
        raise HTTPException(500, f"Error fetching candles: {e}")


@router.get("/options/oi-buildup", response_model=OiBuildupResponse)
async def get_oi_buildup(
    underlying: str = Query(...),
    expiry: str = Query(...)
):
    try:
        rows = await asyncio.to_thread(_get_oi_buildup, underlying, expiry)
        return OiBuildupResponse(underlying=underlying.upper(), expiry=expiry, rows=rows)
    except Exception as e:
        raise HTTPException(500, f"Error fetching OI buildup: {e}")


@router.get("/market/levels", response_model=LevelsResponse)
async def get_market_levels(
    underlying: str = Query(...),
    expiry: str = Query(...)
):
    try:
        levels = await asyncio.to_thread(_get_market_levels, underlying, expiry)
        return LevelsResponse(underlying=underlying.upper(), levels=levels)
    except Exception as e:
        raise HTTPException(500, f"Error generating levels: {e}")


@router.get("/market/alerts", response_model=AlertsResponse)
async def get_market_alerts(underlying: str = Query(...)):
    try:
        alerts = await asyncio.to_thread(_get_market_alerts, underlying)
        return AlertsResponse(underlying=underlying.upper(), alerts=alerts)
    except Exception as e:
        raise HTTPException(500, f"Error checking alerts: {e}")

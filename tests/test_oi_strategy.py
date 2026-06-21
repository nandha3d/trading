from __future__ import annotations

import os
import sys
import asyncio
from datetime import date, datetime, timedelta

import polars as pl
import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _spot_rows(start_price: float, last_price: float, last_volume: int = 3000) -> pl.DataFrame:
    base = datetime(2024, 1, 2, 9, 25)
    rows = []
    for i in range(10):
        ts = base + timedelta(minutes=i)
        close = start_price if i < 5 else last_price
        volume = 1000 if i < 5 else last_volume
        rows.append({
            "underlying": "NIFTY",
            "ts": ts,
            "open": close - 2,
            "high": close + 5,
            "low": close - 5,
            "close": close,
            "volume": volume,
        })
    return pl.DataFrame(rows)


def _option_rows(kind: str = "bullish") -> pl.DataFrame:
    base = datetime(2024, 1, 2, 9, 25)
    expiry = date(2024, 1, 4)
    strikes = [24900, 24950, 25000, 25050]
    rows = []
    for i in range(10):
        ts = base + timedelta(minutes=i)
        second_bucket = i >= 5
        for strike in strikes:
            if kind == "bullish":
                ce_oi = 20_000 if strike == 25000 else 8_000
                pe_oi = 10_000 if strike == 25000 else 7_000
                if second_bucket and strike == 25000:
                    ce_oi = 18_000
                if second_bucket and strike == 25000:
                    pe_oi = 11_000
                ce_close = 100 if not second_bucket else 106
                pe_close = 80
            else:
                ce_oi = 10_000 if strike == 24900 else 7_000
                pe_oi = 20_000 if strike == 24950 else 8_000
                if second_bucket and strike == 24950:
                    pe_oi = 18_000
                if second_bucket and strike == 24900:
                    ce_oi = 11_000
                ce_close = 70
                pe_close = 100 if not second_bucket else 106
            rows.extend([
                {
                    "underlying": "NIFTY",
                    "expiry": expiry,
                    "strike": strike,
                    "option_type": "CE",
                    "ts": ts,
                    "open": ce_close,
                    "high": ce_close + 2,
                    "low": ce_close - 2,
                    "close": ce_close,
                    "volume": 10_000,
                    "oi": ce_oi,
                },
                {
                    "underlying": "NIFTY",
                    "expiry": expiry,
                    "strike": strike,
                    "option_type": "PE",
                    "ts": ts,
                    "open": pe_close,
                    "high": pe_close + 2,
                    "low": pe_close - 2,
                    "close": pe_close,
                    "volume": 10_000,
                    "oi": pe_oi,
                },
            ])
    return pl.DataFrame(rows)


def _spot_rows_three_buckets() -> pl.DataFrame:
    base = datetime(2024, 1, 2, 9, 25)
    rows = []
    for i in range(20):
        ts = base + timedelta(minutes=i)
        close = 24980 if i < 5 else 25020
        rows.append({
            "underlying": "NIFTY",
            "ts": ts,
            "open": close - 2,
            "high": close + 5,
            "low": close - 5,
            "close": close,
            "volume": 1000 if i < 5 else 5000,
        })
    return pl.DataFrame(rows)


def _option_rows_target_exit() -> pl.DataFrame:
    base = datetime(2024, 1, 2, 9, 25)
    expiry = date(2024, 1, 4)
    strikes = [24950, 25000, 25050]
    rows = []
    for i in range(20):
        ts = base + timedelta(minutes=i)
        bucket = 0 if i < 5 else (1 if i < 10 else 2)
        for strike in strikes:
            ce_oi = 20_000 if strike == 25000 else 8_000
            pe_oi = 10_000 if strike == 25000 else 7_000
            ce_close = 100
            if bucket >= 1 and strike == 25000:
                ce_oi = 18_000
                pe_oi = 11_000
                ce_close = 106
            if bucket >= 2 and strike == 25000:
                ce_close = 170
            rows.extend([
                {
                    "underlying": "NIFTY", "expiry": expiry, "strike": strike,
                    "option_type": "CE", "ts": ts, "open": ce_close,
                    "high": ce_close + 2, "low": ce_close - 2, "close": ce_close,
                    "volume": 10_000, "oi": ce_oi,
                },
                {
                    "underlying": "NIFTY", "expiry": expiry, "strike": strike,
                    "option_type": "PE", "ts": ts, "open": 80,
                    "high": 82, "low": 78, "close": 80,
                    "volume": 10_000, "oi": pe_oi,
                },
            ])
    return pl.DataFrame(rows)


def _loose_config() -> dict:
    return {
        "min_option_oi": 1,
        "min_option_volume": 1,
        "min_option_ltp": 1,
        "no_fresh_trade_after": "15:30",
        "force_exit_time": "15:31",
    }


def test_detect_oi_walls_finds_nearest_ce_and_pe():
    from src.analysis.oi_strategy import OiStrategyConfig, detect_oi_walls

    rows = [
        {"strike": 25000, "option_type": "CE", "oi": 30_000, "oi_chg": -2_000, "close": 100, "ltp_chg": 5},
        {"strike": 25100, "option_type": "CE", "oi": 20_000, "oi_chg": 500, "close": 80, "ltp_chg": 0},
        {"strike": 24900, "option_type": "PE", "oi": 35_000, "oi_chg": 2_500, "close": 90, "ltp_chg": 1},
        {"strike": 24800, "option_type": "PE", "oi": 15_000, "oi_chg": 200, "close": 60, "ltp_chg": 0},
    ]
    walls = detect_oi_walls(rows, spot=24980, step=50, cfg=OiStrategyConfig())
    assert walls["ce_wall"].strike == 25000
    assert walls["pe_wall"].strike == 24900


def test_bullish_oi_wall_breakout_generates_buy_ce():
    from src.analysis.oi_strategy import analyze_oi_frames

    result = analyze_oi_frames(
        "NIFTY",
        date(2024, 1, 2),
        date(2024, 1, 4),
        _spot_rows(24980, 25030),
        _option_rows("bullish"),
        target_dt=datetime(2024, 1, 2, 9, 34),
        config=_loose_config(),
    )
    assert result["signal_type"] == "BUY_CE"
    assert result["score"] >= 75
    assert result["suggested_legs"][0]["action"] == "BUY"
    assert result["suggested_legs"][0]["opt_type"] == "CE"
    assert result["factor_scores"]
    assert result["factor_coverage"]["coverage_percent"] >= 80
    assert any(f["factor"] == "oi_wall_unwinding" and f["passed"] for f in result["factor_scores"])
    assert result["data_quality"]["iv_rank"] == "unavailable_not_applied"


def test_bearish_oi_wall_breakdown_generates_buy_pe():
    from src.analysis.oi_strategy import analyze_oi_frames

    result = analyze_oi_frames(
        "NIFTY",
        date(2024, 1, 2),
        date(2024, 1, 4),
        _spot_rows(24980, 24920),
        _option_rows("bearish"),
        target_dt=datetime(2024, 1, 2, 9, 34),
        config=_loose_config(),
    )
    assert result["signal_type"] == "BUY_PE"
    assert result["score"] >= 75
    assert result["suggested_legs"][0]["opt_type"] == "PE"


def test_no_trade_includes_time_and_unavailable_data_quality():
    from src.analysis.oi_strategy import analyze_oi_frames

    result = analyze_oi_frames(
        "NIFTY",
        date(2024, 1, 2),
        date(2024, 1, 4),
        _spot_rows(24980, 25030),
        _option_rows("bullish"),
        target_dt=datetime(2024, 1, 2, 9, 29),
        config={"min_option_oi": 1, "min_option_volume": 1, "min_option_ltp": 1},
    )
    assert result["signal_type"] == "NO_TRADE"
    assert any("before 09:30" in reason for reason in result["no_trade_reasons"])
    assert result["data_quality"]["futures_oi"] == "unavailable"
    assert result["data_quality"]["real_bid_ask"] == "unavailable"


def test_config_override_can_raise_min_score_to_block_signal():
    from src.analysis.oi_strategy import analyze_oi_frames

    cfg = _loose_config()
    cfg["min_signal_score"] = 101
    result = analyze_oi_frames(
        "NIFTY",
        date(2024, 1, 2),
        date(2024, 1, 4),
        _spot_rows(24980, 25030),
        _option_rows("bullish"),
        target_dt=datetime(2024, 1, 2, 9, 34),
        config=cfg,
    )
    assert result["signal_type"] == "NO_TRADE"
    assert any("below minimum 101" in reason for reason in result["no_trade_reasons"])


def test_oi_strategy_api_success_with_monkeypatch(monkeypatch):
    from api.models import OiStrategySignalRequest
    from api.routes import oi_strategy as route

    def fake_detect(req):
        return {
            "underlying": "NIFTY",
            "expiry": "2024-01-04",
            "timestamp": "2024-01-02T09:35:00",
            "spot_price": 25030.0,
            "atm_strike": 25050,
            "signal_type": "BUY_CE",
            "strategy_name": "Bullish OI Wall Breakout",
            "score": 85,
            "strength": "STRONG",
            "reasons": ["5-minute close broke CE wall 25000"],
            "no_trade_reasons": [],
            "score_breakdown": [{"label": "Price breaks CE wall", "points": 20, "max_points": 20, "passed": True, "detail": "ok"}],
            "walls": {"ce_wall": None, "pe_wall": None},
            "entry_zone": 25000.0,
            "stop_loss": 25000.0,
            "target_1": 25100.0,
            "target_2": None,
            "suggested_legs": [{"action": "BUY", "opt_type": "CE", "selection": "ATM", "value": 0, "lots": 1, "sl_pct": 25, "sl_unit": "PERCENT", "tp_pct": None, "tp_unit": "PERCENT", "entry_time": "09:35", "exit_time": "15:15"}],
            "data_quality": {"futures_oi": "unavailable"},
            "config": {},
        }

    monkeypatch.setattr(route, "_detect", fake_detect)
    res = asyncio.run(route.detect_oi_strategy_signal(OiStrategySignalRequest(underlying="NIFTY", date=date(2024, 1, 2))))
    assert res["signal_type"] == "BUY_CE"


def test_oi_strategy_api_invalid_timestamp_returns_400():
    from api.models import OiStrategySignalRequest
    from api.routes import oi_strategy as route

    with pytest.raises(HTTPException) as exc:
        asyncio.run(route.detect_oi_strategy_signal(
            OiStrategySignalRequest(underlying="NIFTY", date=date(2024, 1, 2), timestamp="not-a-time")
        ))
    assert exc.value.status_code == 400


def test_oi_strategy_backtest_scans_bars_and_exits_target(monkeypatch):
    from src.analysis import oi_strategy

    monkeypatch.setattr(oi_strategy, "_trade_dates", lambda underlying, start, end: [date(2024, 1, 2)])
    monkeypatch.setattr(oi_strategy, "_expiry_for_offset", lambda underlying, day, offset=0: date(2024, 1, 4))
    monkeypatch.setattr(oi_strategy.storage, "read_spot", lambda underlying, start, end: _spot_rows_three_buckets())
    monkeypatch.setattr(
        oi_strategy.storage,
        "read_options",
        lambda underlying, start, end, expiry=None, strikes=None, option_type=None: _option_rows_target_exit(),
    )

    result = oi_strategy.backtest_oi_strategy(
        "NIFTY",
        date(2024, 1, 2),
        date(2024, 1, 2),
        config={**_loose_config(), "max_trades_per_day": 1, "premium_target_percent": 50},
    )
    assert result["stats"]["trades"] == 1
    assert result["trades"][0]["signal_type"] == "BUY_CE"
    assert result["trades"][0]["exit_reason"] == "TARGET"
    assert result["trades"][0]["net_pnl"] > 0
    assert result["baseline_comparison"]["name"].startswith("Naive")
    assert result["cost_sensitivity"]
    assert result["regime_summary"]
    assert result["walk_forward_summary"]
    assert result["trade_journal"][0]["action"] in {"TRADE", "NO_TRADE"}


def test_oi_strategy_execution_model_adverse_is_more_conservative(monkeypatch):
    from src.analysis import oi_strategy

    monkeypatch.setattr(oi_strategy, "_trade_dates", lambda underlying, start, end: [date(2024, 1, 2)])
    monkeypatch.setattr(oi_strategy, "_expiry_for_offset", lambda underlying, day, offset=0: date(2024, 1, 4))
    monkeypatch.setattr(oi_strategy.storage, "read_spot", lambda underlying, start, end: _spot_rows_three_buckets())
    monkeypatch.setattr(
        oi_strategy.storage,
        "read_options",
        lambda underlying, start, end, expiry=None, strikes=None, option_type=None: _option_rows_target_exit(),
    )

    base_cfg = {**_loose_config(), "max_trades_per_day": 1, "premium_target_percent": 50}
    close_fill = oi_strategy.backtest_oi_strategy(
        "NIFTY", date(2024, 1, 2), date(2024, 1, 2), config={**base_cfg, "execution_model": "close"}
    )
    adverse_fill = oi_strategy.backtest_oi_strategy(
        "NIFTY", date(2024, 1, 2), date(2024, 1, 2), config={**base_cfg, "execution_model": "adverse_close", "slippage_bps": 25}
    )
    assert adverse_fill["stats"]["net_pnl"] < close_fill["stats"]["net_pnl"]
    assert adverse_fill["trades"][0]["entry_price"] > adverse_fill["trades"][0]["raw_entry_price"]
    assert adverse_fill["trades"][0]["exit_price"] < adverse_fill["trades"][0]["raw_exit_price"]


def test_oi_strategy_backtest_api_success_with_monkeypatch(monkeypatch):
    from api.models import OiStrategyBacktestRequest
    from api.routes import oi_strategy as route

    def fake_backtest(req):
        return {
            "underlying": "NIFTY",
            "start": "2024-01-02",
            "end": "2024-01-02",
            "interval": 5,
            "expiry_offset": 0,
            "stats": {
                "trades": 1, "wins": 1, "losses": 0, "win_rate": 100.0,
                "net_pnl": 100.0, "gross_profit": 100.0, "gross_loss": 0.0,
                "profit_factor": 999.0, "avg_trade": 100.0, "avg_win": 100.0,
                "avg_loss": 0.0, "max_drawdown": 0.0,
            },
            "equity_curve": [100.0],
            "trades": [],
            "daily": [{"day": "2024-01-02", "trades": 1, "net_pnl": 100.0, "skip_reason": ""}],
            "checked_bars": 1,
            "no_trade_bars": 0,
            "data_quality": {},
            "config": {},
        }

    monkeypatch.setattr(route, "_backtest", fake_backtest)
    res = asyncio.run(route.run_oi_strategy_backtest(
        OiStrategyBacktestRequest(underlying="NIFTY", start=date(2024, 1, 2), end=date(2024, 1, 2))
    ))
    assert res["stats"]["trades"] == 1


def test_oi_strategy_backtest_api_rejects_bad_range():
    from api.models import OiStrategyBacktestRequest
    from api.routes import oi_strategy as route

    with pytest.raises(HTTPException) as exc:
        asyncio.run(route.run_oi_strategy_backtest(
            OiStrategyBacktestRequest(underlying="NIFTY", start=date(2024, 1, 3), end=date(2024, 1, 2))
        ))
    assert exc.value.status_code == 400

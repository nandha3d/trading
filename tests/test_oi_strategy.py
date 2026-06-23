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


def test_active_factor_controls_exclude_disabled_factors_and_require_pass():
    from src.analysis.oi_strategy import analyze_oi_frames

    cfg = {
        **_loose_config(),
        "active_factors": ["vwap_confirmation"],
        "required_factors": ["vwap_confirmation"],
    }
    result = analyze_oi_frames(
        "NIFTY",
        date(2024, 1, 2),
        date(2024, 1, 4),
        _spot_rows(24980, 25030),
        _option_rows("bullish"),
        target_dt=datetime(2024, 1, 2, 9, 34),
        config=cfg,
    )
    assert result["signal_type"] == "BUY_CE"
    assert result["score"] == 100
    assert [f["factor"] for f in result["factor_scores"]] == ["vwap_confirmation"]

    blocked = analyze_oi_frames(
        "NIFTY",
        date(2024, 1, 2),
        date(2024, 1, 4),
        _spot_rows(24980, 25030),
        _option_rows("bullish"),
        target_dt=datetime(2024, 1, 2, 9, 34),
        config={
            **_loose_config(),
            "active_factors": ["vwap_confirmation", "oi_wall_unwinding"],
            "required_factors": ["vwap_confirmation", "oi_wall_unwinding"],
            "ce_unwinding_threshold_percent": -50,
        },
    )
    assert blocked["signal_type"] == "NO_TRADE"
    assert any("Required factor oi_wall_unwinding did not pass" in reason for reason in blocked["no_trade_reasons"])


def test_first_minutes_block_allows_0930_boundary():
    from src.analysis.oi_strategy import analyze_oi_frames

    cfg = {**_loose_config(), "no_trade_first_minutes": 15}
    before = analyze_oi_frames(
        "NIFTY",
        date(2024, 1, 2),
        date(2024, 1, 4),
        _spot_rows(24980, 25030),
        _option_rows("bullish"),
        target_dt=datetime(2024, 1, 2, 9, 29),
        config=cfg,
    )
    boundary = analyze_oi_frames(
        "NIFTY",
        date(2024, 1, 2),
        date(2024, 1, 4),
        _spot_rows(24980, 25030),
        _option_rows("bullish"),
        target_dt=datetime(2024, 1, 2, 9, 30),
        config=cfg,
    )
    assert any("before 09:30" in reason for reason in before["no_trade_reasons"])
    assert not any("before 09:30" in reason for reason in boundary["no_trade_reasons"])


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
    assert "equity_curve" in result["baseline_comparison"]
    assert result["baseline_comparison"]["per_trade"]
    assert result["cost_sensitivity"]
    assert result["drawdown_analysis"]["max_drawdown_duration_trades"] >= 0
    assert result["trade_quality"]["exit_reason_distribution"]["TARGET"] == 1
    assert result["timing_analysis"]["expiry"]
    assert "mdd_95" in result["monte_carlo"]
    assert result["statistical_significance"]["additional_trades_needed"] == 199
    assert result["sample_size_warning"]["level"] == "warning"
    assert result["regime_summary"]
    assert result["walk_forward_summary"]
    assert result["trade_journal"][0]["action"] in {"TRADE", "NO_TRADE"}


def test_oi_strategy_drawdown_analysis_known_sequence():
    from src.analysis import oi_strategy

    trades = [
        {"day": "2024-01-02", "net_pnl": 100, "entry_time": "2024-01-02T09:30:00", "exit_time": "2024-01-02T09:35:00"},
        {"day": "2024-01-02", "net_pnl": -40, "entry_time": "2024-01-02T09:40:00", "exit_time": "2024-01-02T09:45:00"},
        {"day": "2024-01-02", "net_pnl": -30, "entry_time": "2024-01-02T09:50:00", "exit_time": "2024-01-02T09:55:00"},
        {"day": "2024-01-02", "net_pnl": 80, "entry_time": "2024-01-02T10:00:00", "exit_time": "2024-01-02T10:05:00"},
    ]
    dd = oi_strategy._drawdown_analysis(trades)
    assert dd["max_drawdown"] == -70
    assert dd["max_drawdown_duration_trades"] == 2
    assert dd["underwater_curve"][2]["drawdown"] == -70


def test_oi_strategy_quality_timing_and_monte_carlo_helpers():
    from src.analysis import oi_strategy

    trades = [
        {
            "underlying": "NIFTY", "day": "2024-01-02", "expiry": "2024-01-04",
            "entry_time": "2024-01-02T09:30:00", "exit_time": "2024-01-02T09:45:00",
            "strike": 25000, "opt_type": "CE", "exit_reason": "TARGET", "net_pnl": 100,
            "gross_pnl": 120, "cost": 20, "mae": -10, "mfe": 150,
        },
        {
            "underlying": "NIFTY", "day": "2024-01-03", "expiry": "2024-01-03",
            "entry_time": "2024-01-03T10:30:00", "exit_time": "2024-01-03T11:45:00",
            "strike": 25000, "opt_type": "PE", "exit_reason": "SL", "net_pnl": -50,
            "gross_pnl": -40, "cost": 10, "mae": -80, "mfe": 20,
        },
    ]
    baseline = [
        {"key": "b", "filter_decision": "skipped_by_filter", "baseline_net_pnl": 75},
        {"key": "c", "filter_decision": "skipped_by_filter", "baseline_net_pnl": -25},
    ]
    journal = [{"action": "NO_TRADE", "no_trade_reasons": ["Signal score below minimum"]}]

    quality = oi_strategy._trade_quality(trades, journal, baseline)
    timing = oi_strategy._timing_analysis(trades)
    mc = oi_strategy._monte_carlo(trades, runs=50)
    sig = oi_strategy._statistical_significance(trades)
    warning = oi_strategy._sample_size_warning(oi_strategy._stats_from_trades(trades))

    assert quality["exit_reason_distribution"] == {"TARGET": 1, "SL": 1}
    assert quality["skipped_baseline"]["candidates"] == 2
    assert quality["skipped_baseline"]["profitable"] == 1
    assert timing["expiry"][0]["name"] in {"expiry_day", "non_expiry_day"}
    assert "mdd_99" in mc
    assert sig["additional_trades_needed"] == 198
    assert warning["level"] == "warning"


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


def test_oi_strategy_ablation_study_outputs_factor_and_trailing_rows(monkeypatch):
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
        config={
            **_loose_config(),
            "max_trades_per_day": 1,
            "premium_target_percent": 50,
            "run_ablation_study": True,
            "ablation_trailing_sl_values": [20, 0],
        },
    )
    ids = {row["config_id"] for row in result["ablation_study"]}
    assert "standalone_oi_wall_unwinding" in ids
    assert "all_minus_oi_wall_unwinding" in ids
    assert "full_stack" in ids
    assert result["oi_marginal_contribution"]["delta_net_pnl"] is not None
    assert "overlap_trades" in result["paired_comparison"]
    assert result["research_verdict"]["verdict"] in {"OI wall improves", "OI wall hurts", "insufficient evidence"}
    assert {row["trailing_sl_percent"] for row in result["trailing_sl_study"]} == {20.0, 0.0}
    assert all("qualification" in row for row in result["ablation_study"])


def test_oi_strategy_optional_indicator_entry_filter_blocks_trade(monkeypatch):
    from api.models import Condition, ConditionGroup, IndicatorDef, Operand
    from src.analysis import oi_strategy

    monkeypatch.setattr(oi_strategy, "_trade_dates", lambda underlying, start, end: [date(2024, 1, 2)])
    monkeypatch.setattr(oi_strategy, "_expiry_for_offset", lambda underlying, day, offset=0: date(2024, 1, 4))
    monkeypatch.setattr(oi_strategy.storage, "read_spot", lambda underlying, start, end: _spot_rows_three_buckets())
    monkeypatch.setattr(
        oi_strategy.storage,
        "read_options",
        lambda underlying, start, end, expiry=None, strikes=None, option_type=None: _option_rows_target_exit(),
    )

    indicators = [IndicatorDef(id="candle", type="CURRENT_CANDLE", name="candle", interval=5)]
    entry_signal = ConditionGroup(conditions=[
        Condition(
            lhs=Operand(kind="candle", field="close"),
            op=">",
            rhs=Operand(kind="const", value=99_999),
        )
    ])
    result = oi_strategy.backtest_oi_strategy(
        "NIFTY",
        date(2024, 1, 2),
        date(2024, 1, 2),
        config={**_loose_config(), "max_trades_per_day": 1, "premium_target_percent": 50},
        signal_indicators=indicators,
        entry_signal=entry_signal,
    )
    assert result["stats"]["trades"] == 0
    assert any(
        "indicator_entry_signal_not_met" in row.get("no_trade_reasons", [])
        for row in result["trade_journal"]
    )


def test_oi_strategy_indicator_exit_signal_closes_trade(monkeypatch):
    from api.models import Condition, ConditionGroup, IndicatorDef, Operand
    from src.analysis import oi_strategy

    monkeypatch.setattr(oi_strategy, "_trade_dates", lambda underlying, start, end: [date(2024, 1, 2)])
    monkeypatch.setattr(oi_strategy, "_expiry_for_offset", lambda underlying, day, offset=0: date(2024, 1, 4))
    monkeypatch.setattr(oi_strategy.storage, "read_spot", lambda underlying, start, end: _spot_rows_three_buckets())
    monkeypatch.setattr(
        oi_strategy.storage,
        "read_options",
        lambda underlying, start, end, expiry=None, strikes=None, option_type=None: _option_rows_target_exit(),
    )

    indicators = [IndicatorDef(id="candle", type="CURRENT_CANDLE", name="candle", interval=5)]
    exit_signal = ConditionGroup(conditions=[
        Condition(
            lhs=Operand(kind="candle", field="time_of_day"),
            op=">=",
            rhs=Operand(kind="const", value=935),
        )
    ])
    result = oi_strategy.backtest_oi_strategy(
        "NIFTY",
        date(2024, 1, 2),
        date(2024, 1, 2),
        config={**_loose_config(), "max_trades_per_day": 1, "premium_target_percent": 999},
        signal_indicators=indicators,
        exit_signal=exit_signal,
    )
    assert result["stats"]["trades"] == 1
    assert result["trades"][0]["exit_reason"] == "SIGNAL"


def test_main_backtest_api_routes_oi_strategy_response(monkeypatch):
    from api.models import BacktestRequest
    from api.routes import backtest as route

    def fake_oi_backtest(req):
        return {
            "underlying": "NIFTY",
            "start": "2024-01-02",
            "end": "2024-01-02",
            "interval": 5,
            "expiry_offset": 0,
            "stats": {
                "trades": 1, "wins": 1, "losses": 0, "win_rate": 100.0,
                "net_pnl": 120.0, "gross_profit": 130.0, "gross_loss": 0.0,
                "profit_factor": 999.0, "avg_trade": 120.0, "avg_win": 120.0,
                "avg_loss": 0.0, "max_drawdown": 0.0, "expectancy": 120.0,
                "sharpe": 0.0,
            },
            "equity_curve": [120.0],
            "trades": [{
                "day": "2024-01-02", "expiry": "2024-01-04",
                "entry_time": "2024-01-02T09:30:00", "exit_time": "2024-01-02T09:35:00",
                "signal_type": "BUY_CE", "strategy_name": "Bullish OI Wall Breakout",
                "score": 85, "strength": "STRONG", "strike": 25000, "opt_type": "CE",
                "qty": 50, "entry_price": 100.0, "exit_price": 103.0,
                "exit_reason": "TARGET", "gross_pnl": 150.0, "cost": 30.0,
                "net_pnl": 120.0, "entry_spot": 25020.0,
            }],
            "daily": [{"day": "2024-01-02", "trades": 1, "net_pnl": 120.0, "skip_reason": ""}],
            "checked_bars": 1,
            "no_trade_bars": 0,
            "trade_journal": [],
            "baseline_comparison": {"stats": {"net_pnl": 80.0}},
            "data_quality": {},
            "config": {},
        }

    monkeypatch.setattr(route, "_run_oi_backtest", fake_oi_backtest)
    monkeypatch.setattr(route.storage, "save_backtest_run", lambda **kwargs: None)
    monkeypatch.setattr(route.storage, "log_audit_event", lambda *args, **kwargs: None)
    res = asyncio.run(route.run_backtest(
        BacktestRequest(
            underlying="NIFTY",
            start=date(2024, 1, 2),
            end=date(2024, 1, 2),
            strategy_type="OI",
            legs=[],
        )
    ))
    assert res.strategy_type == "OI"
    assert res.stats.win_rate == 1.0
    assert res.trades[0].legs[0].action == "BUY"
    assert res.trades[0].legs[0].opt_type == "CE"
    assert res.oi_analytics["baseline_comparison"]["stats"]["net_pnl"] == 80.0


def test_strategy_templates_include_oi():
    from api.routes import strategies

    res = asyncio.run(strategies.get_templates())
    oi = next(t for t in res["templates"] if t.template_id == "oi")
    assert oi.name == "OI"
    assert oi.strategy_type == "OI"
    assert oi.dynamic_legs is True


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

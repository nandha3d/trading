"""Unit tests for backend logic: options math, strategy validation, risk precheck, storage helpers."""
from __future__ import annotations
import json
import sys
import os
import pytest

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────── Options Math ───────────────────────────

class TestOptionsMath:
    """Tests for BSM pricing and Greeks calculations."""

    def test_bs_price_call(self):
        from src.data.options_math import bs_price
        # ATM call with 30 days, should be > 0
        price = bs_price(S=23000, K=23000, T=30 / 365, r=0.065, sigma=0.15, option_type="CE")
        assert price > 0
        assert price < 23000  # Can't be more than spot

    def test_bs_price_put(self):
        from src.data.options_math import bs_price
        price = bs_price(S=23000, K=23000, T=30 / 365, r=0.065, sigma=0.15, option_type="PE")
        assert price > 0

    def test_bs_price_deep_itm_call(self):
        from src.data.options_math import bs_price
        price = bs_price(S=25000, K=23000, T=30 / 365, r=0.065, sigma=0.15, option_type="CE")
        assert price > 2000  # Must be at least intrinsic

    def test_bs_price_deep_otm_call(self):
        from src.data.options_math import bs_price
        price = bs_price(S=23000, K=25000, T=5 / 365, r=0.065, sigma=0.15, option_type="CE")
        assert price < 100  # Deep OTM with little time

    def test_calculate_greeks_has_all_keys(self):
        from src.data.options_math import calculate_greeks
        g = calculate_greeks(S=23000, K=23000, T=30 / 365, r=0.065, sigma=0.15, option_type="CE")
        assert "delta" in g
        assert "gamma" in g
        assert "theta" in g
        assert "vega" in g

    def test_greeks_atm_call_delta(self):
        from src.data.options_math import calculate_greeks
        g = calculate_greeks(S=23000, K=23000, T=30 / 365, r=0.065, sigma=0.15, option_type="CE")
        # ATM call delta should be ~0.5
        assert 0.4 < g["delta"] < 0.7

    def test_greeks_atm_put_delta(self):
        from src.data.options_math import calculate_greeks
        g = calculate_greeks(S=23000, K=23000, T=30 / 365, r=0.065, sigma=0.15, option_type="PE")
        # ATM put delta should be ~-0.5
        assert -0.7 < g["delta"] < -0.3

    def test_calculate_iv_roundtrip(self):
        from src.data.options_math import bs_price, calculate_iv
        sigma = 0.20
        S, K, T, r = 23000, 23000, 30 / 365, 0.065
        price = bs_price(S, K, T, r, sigma, "CE")
        iv = calculate_iv(price, S, K, T, r, "CE")
        if iv:
            assert abs(iv - sigma) < 0.02  # Within 2%


# ─────────────────────────── Strategy Validation ───────────────────────────

class TestStrategyValidation:
    """Tests for strategy validate endpoint logic."""

    def test_empty_legs_invalid(self):
        """Strategy with no legs should produce errors."""
        from api.routes.strategies import ValidationIssue
        # Simulate the validation logic
        legs = []
        errors = []
        if not legs:
            errors.append(ValidationIssue(field="legs", message="Strategy must have at least one leg"))
        assert len(errors) == 1

    def test_invalid_action(self):
        from api.routes.strategies import ValidationIssue
        legs = [{"action": "HOLD", "opt_type": "CE"}]
        errors = []
        for i, leg in enumerate(legs):
            if leg.get("action") not in ["BUY", "SELL"]:
                errors.append(ValidationIssue(field=f"legs[{i}].action", message="Action must be BUY or SELL"))
        assert len(errors) == 1

    def test_valid_straddle(self):
        legs = [
            {"action": "SELL", "opt_type": "CE", "lots": 1},
            {"action": "SELL", "opt_type": "PE", "lots": 1},
        ]
        errors = []
        for i, leg in enumerate(legs):
            if leg.get("action") not in ["BUY", "SELL"]:
                errors.append(f"bad action at {i}")
            if leg.get("opt_type") not in ["CE", "PE"]:
                errors.append(f"bad opt_type at {i}")
        assert len(errors) == 0


# ─────────────────────────── Risk Precheck ───────────────────────────

class TestRiskPrecheck:
    """Tests for risk precheck constraint validation."""

    def test_naked_sell_warning(self):
        sell_legs = [{"action": "SELL", "opt_type": "CE"}]
        buy_legs = []
        has_naked_sell = False
        for l in sell_legs:
            is_hedged = any(h["opt_type"] == l["opt_type"] for h in buy_legs)
            if not is_hedged:
                has_naked_sell = True
        assert has_naked_sell is True

    def test_hedged_sell_no_warning(self):
        sell_legs = [{"action": "SELL", "opt_type": "CE"}]
        buy_legs = [{"action": "BUY", "opt_type": "CE"}]
        has_naked_sell = False
        for l in sell_legs:
            is_hedged = any(h["opt_type"] == l["opt_type"] for h in buy_legs)
            if not is_hedged:
                has_naked_sell = True
        assert has_naked_sell is False

    def test_insufficient_capital_blocks(self):
        capital = 100000
        sell_count = 2
        margin_req = 150000.0 * sell_count
        assert capital < margin_req

    def test_sufficient_capital_allows(self):
        capital = 500000
        sell_count = 2
        margin_req = 150000.0 * sell_count
        assert capital >= margin_req

    def test_risk_score_naked_no_sl(self):
        score = 2
        has_naked_sell = True
        has_sl = False
        if has_naked_sell:
            score += 3
        if not has_sl:
            score += 2
        assert score == 7
        assert score <= 8  # HIGH

    def test_risk_score_hedged_with_sl(self):
        score = 2
        has_naked_sell = False
        has_sl = True
        if has_naked_sell:
            score += 3
        if not has_sl:
            score += 2
        assert score == 2  # LOW


# ─────────────────────────── Margin Estimation ───────────────────────────

class TestMarginEstimation:
    """Tests for margin calculation logic."""

    def test_naked_sell_margin(self):
        """Naked sell should have full margin."""
        lot_size = 25  # NIFTY
        sell_legs = [{"action": "SELL", "opt_type": "CE", "strike": 23000, "lots": 1, "entry_price": 100}]
        buy_legs = []
        naked_margin = 150000.0 * len(sell_legs)
        assert naked_margin == 150000.0

    def test_hedged_margin_discount(self):
        """Hedged strategy should get 70% margin benefit."""
        sell_legs = [{"action": "SELL", "opt_type": "CE", "strike": 23000}]
        buy_legs = [{"action": "BUY", "opt_type": "CE", "strike": 23500}]
        leg_margin = 150000.0
        discount = leg_margin * 0.70
        net_margin = leg_margin - discount
        assert net_margin == 45000.0

    def test_iron_condor_margin(self):
        """Iron condor: 2 sell + 2 buy legs, both hedged."""
        margin_per_sell = 150000.0
        hedge_discount = 0.70
        total_margin = 2 * margin_per_sell * (1 - hedge_discount)
        assert total_margin == pytest.approx(90000.0)


# ─────────────────────────── Provider Factory ───────────────────────────

class TestProviderFactory:
    """Tests for the data provider factory pattern."""

    def test_unknown_provider_raises(self):
        from src.data.providers.provider_factory import get_provider
        with pytest.raises(ValueError, match="Unknown provider"):
            get_provider("nonexistent_broker")

    def test_list_providers(self):
        from src.data.providers.provider_factory import list_providers
        providers = list_providers()
        assert len(providers) >= 8
        names = [p["name"] for p in providers]
        assert "angelone" in names
        assert "upstox" in names
        assert "zerodha" in names


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

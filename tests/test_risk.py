"""
Tests for deterministic risk scoring.

Covers: tier thresholds, pattern contributions, numeric factor capping,
score clamping to [0, 100], contributing_factors structure, and reproducibility.
"""

import pytest
from pytest import approx

from src.pipeline.risk import score_user, tier_for, WEIGHTS, FORMULA_VERSION


# ---------------------------------------------------------------------------
# Tier thresholds
# ---------------------------------------------------------------------------

class TestTierFor:

    @pytest.mark.parametrize("score,expected_tier", [
        (0.0,   "low"),
        (24.99, "low"),
        (25.0,  "medium"),
        (49.99, "medium"),
        (50.0,  "high"),
        (74.99, "high"),
        (75.0,  "critical"),
        (100.0, "critical"),
    ])
    def test_tier_thresholds(self, score, expected_tier):
        assert tier_for(score) == expected_tier


# ---------------------------------------------------------------------------
# Pattern contributions
# ---------------------------------------------------------------------------

class TestPatternContributions:

    def _base_features(self):
        """Low-severity features so pattern contribution dominates."""
        return {
            "stake_escalation_ratio_after_losses": 1.0,
            "trades_per_minute": 0.5,
            "pct_trades_within_5min_of_high_impact_news": 0.0,
            "longest_losing_streak": 3,
            "total_net_pnl_usd": 0.0,
        }

    def test_martingale_pattern_adds_25(self):
        f = self._base_features()
        result = score_user("u_x", f, ["martingale"])
        pattern_contrib = next(
            c["contribution"] for c in result["contributing_factors"]
            if c["factor"] == "martingale"
        )
        assert pattern_contrib == approx(25)

    def test_revenge_trading_adds_20(self):
        f = self._base_features()
        result = score_user("u_x", f, ["revenge_trading"])
        pattern_contrib = next(
            c["contribution"] for c in result["contributing_factors"]
            if c["factor"] == "revenge_trading"
        )
        assert pattern_contrib == approx(20)

    def test_normal_pattern_adds_zero(self):
        f = self._base_features()
        result = score_user("u_x", f, ["normal"])
        assert result["risk_score"] == approx(0.0)

    def test_insufficient_evidence_adds_zero(self):
        f = self._base_features()
        result = score_user("u_x", f, ["insufficient_evidence"])
        assert result["risk_score"] == approx(0.0)

    def test_multiple_patterns_sum_contributions(self):
        """martingale(25) + news_chasing(15) = 40, with low features → medium tier."""
        f = self._base_features()
        result = score_user("u_x", f, ["martingale", "news_chasing"])
        assert result["risk_score"] == approx(40.0)
        assert result["risk_tier"] == "medium"


# ---------------------------------------------------------------------------
# Numeric factor capping
# ---------------------------------------------------------------------------

class TestNumericFactorCaps:

    def _zero_pattern_features(self, overrides):
        base = {
            "stake_escalation_ratio_after_losses": 1.0,
            "trades_per_minute": 0.5,
            "pct_trades_within_5min_of_high_impact_news": 0.0,
            "longest_losing_streak": 3,
            "total_net_pnl_usd": 0.0,
        }
        base.update(overrides)
        return base

    def test_stake_escalation_caps_at_25(self):
        # Very high ratio should be capped
        f = self._zero_pattern_features({"stake_escalation_ratio_after_losses": 1000.0})
        result = score_user("u_x", f, ["normal"])
        escalation_contrib = next(
            c["contribution"] for c in result["contributing_factors"]
            if "escalation" in c["factor"]
        )
        assert escalation_contrib <= WEIGHTS["stake_escalation_after_losses"]["cap"]

    def test_trades_per_minute_caps_at_15(self):
        f = self._zero_pattern_features({"trades_per_minute": 1000.0})
        result = score_user("u_x", f, ["normal"])
        tpm_contrib = next(
            c["contribution"] for c in result["contributing_factors"]
            if "trades_per_minute" in c["factor"]
        )
        assert tpm_contrib <= WEIGHTS["trades_per_minute"]["cap"]

    def test_longest_losing_streak_caps(self):
        f = self._zero_pattern_features({"longest_losing_streak": 1000})
        result = score_user("u_x", f, ["normal"])
        streak_contrib = next(
            c["contribution"] for c in result["contributing_factors"]
            if "losing_streak" in c["factor"]
        )
        assert streak_contrib <= WEIGHTS["longest_losing_streak"]["cap"]

    def test_pct_news_adjacent_caps(self):
        f = self._zero_pattern_features({"pct_trades_within_5min_of_high_impact_news": 1.0})
        result = score_user("u_x", f, ["normal"])
        news_contrib = next(
            c["contribution"] for c in result["contributing_factors"]
            if "news" in c["factor"]
        )
        assert news_contrib <= WEIGHTS["pct_news_adjacent"]["cap"]

    def test_recent_net_loss_caps(self):
        f = self._zero_pattern_features({"total_net_pnl_usd": -100_000.0})
        result = score_user("u_x", f, ["normal"])
        loss_contrib = next(
            c["contribution"] for c in result["contributing_factors"]
            if "loss" in c["factor"] and "net" in c["factor"]
        )
        assert loss_contrib <= WEIGHTS["recent_net_loss"]["cap"]


# ---------------------------------------------------------------------------
# Score clamping
# ---------------------------------------------------------------------------

class TestScoreClamping:

    def test_score_never_exceeds_100(self):
        extreme = {
            "stake_escalation_ratio_after_losses": 1000.0,
            "trades_per_minute": 1000.0,
            "pct_trades_within_5min_of_high_impact_news": 1.0,
            "longest_losing_streak": 1000,
            "total_net_pnl_usd": -1_000_000.0,
        }
        result = score_user("u_x", extreme, ["martingale", "revenge_trading", "news_chasing"])
        assert result["risk_score"] <= 100.0

    def test_score_never_below_zero(self):
        minimal = {
            "stake_escalation_ratio_after_losses": 0.0,
            "trades_per_minute": 0.0,
            "pct_trades_within_5min_of_high_impact_news": 0.0,
            "longest_losing_streak": 0,
            "total_net_pnl_usd": 1000.0,
        }
        result = score_user("u_x", minimal, ["normal"])
        assert result["risk_score"] >= 0.0


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------

class TestScoreUserOutputStructure:

    @pytest.fixture()
    def result(self):
        features = {
            "stake_escalation_ratio_after_losses": 2.0,
            "trades_per_minute": 1.5,
            "pct_trades_within_5min_of_high_impact_news": 0.0,
            "longest_losing_streak": 3,
            "total_net_pnl_usd": 1.0,
        }
        return score_user("u_001", features, ["martingale"])

    def test_has_user_id(self, result):
        assert result["user_id"] == "u_001"

    def test_has_risk_score(self, result):
        assert "risk_score" in result
        assert isinstance(result["risk_score"], float)

    def test_has_risk_tier(self, result):
        assert result["risk_tier"] in {"low", "medium", "high", "critical"}

    def test_has_formula_version(self, result):
        assert result["formula_version"] == FORMULA_VERSION

    def test_has_contributing_factors(self, result):
        assert isinstance(result["contributing_factors"], list)
        assert len(result["contributing_factors"]) > 0

    def test_contributing_factors_have_required_keys(self, result):
        required = {"factor", "value", "weight", "contribution"}
        for cf in result["contributing_factors"]:
            assert required.issubset(cf.keys()), f"Missing keys in {cf}"

    def test_risk_tier_matches_score(self, result):
        assert result["risk_tier"] == tier_for(result["risk_score"])


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------

class TestReproducibility:

    def test_identical_inputs_produce_identical_output(self):
        features = {
            "stake_escalation_ratio_after_losses": 2.0,
            "trades_per_minute": 1.589404,
            "pct_trades_within_5min_of_high_impact_news": 0.0,
            "longest_losing_streak": 3,
            "total_net_pnl_usd": 1.0,
        }
        r1 = score_user("u_001", features, ["martingale"])
        r2 = score_user("u_001", features, ["martingale"])
        assert r1["risk_score"] == r2["risk_score"]
        assert r1["risk_tier"] == r2["risk_tier"]

    def test_formula_version_is_non_empty_string(self):
        assert isinstance(FORMULA_VERSION, str)
        assert len(FORMULA_VERSION) > 0

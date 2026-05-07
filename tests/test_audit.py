"""
Tests for the false-positive martingale audit module.

The audit picks the first martingale-classified user and verifies in deterministic
code that stake escalation followed consecutive losses (≥3 qualifying pairs needed).
"""

import pytest

from src.pipeline.audit import verify_martingale


U001_TRADES = [
    {"trade_id": "t_00001", "open_ts": "2025-08-01T08:14:22Z", "close_ts": "2025-08-01T08:14:55Z",
     "stake_usd": 5,  "payout_usd": 0,  "result": "loss", "session_id": "s_4412"},
    {"trade_id": "t_00002", "open_ts": "2025-08-01T08:15:01Z", "close_ts": "2025-08-01T08:15:34Z",
     "stake_usd": 10, "payout_usd": 0,  "result": "loss", "session_id": "s_4412"},
    {"trade_id": "t_00003", "open_ts": "2025-08-01T08:15:40Z", "close_ts": "2025-08-01T08:16:13Z",
     "stake_usd": 20, "payout_usd": 0,  "result": "loss", "session_id": "s_4412"},
    {"trade_id": "t_00004", "open_ts": "2025-08-01T08:16:20Z", "close_ts": "2025-08-01T08:16:53Z",
     "stake_usd": 40, "payout_usd": 76, "result": "win",  "session_id": "s_4412"},
]


class TestVerifyMartingaleU001:
    """The u_001 fixture has 3 consecutive post-loss doublings → verified = True."""

    @pytest.fixture(autouse=True)
    def result(self):
        return verify_martingale("u_001", U001_TRADES, ["martingale"])

    def test_verified_is_true(self, result):
        assert result["verified"] is True

    def test_user_id_matches(self, result):
        assert result["user_id"] == "u_001"

    def test_pattern_is_martingale(self, result):
        assert result["pattern"] == "martingale"

    def test_supporting_trade_sequence_present(self, result):
        assert isinstance(result["supporting_trade_sequence"], list)
        assert len(result["supporting_trade_sequence"]) >= 3

    def test_supporting_trades_are_real_ids(self, result):
        valid_ids = {t["trade_id"] for t in U001_TRADES}
        for tid in result["supporting_trade_sequence"]:
            assert tid in valid_ids

    def test_calculation_field_is_non_empty_string(self, result):
        assert isinstance(result["calculation"], str)
        assert len(result["calculation"]) > 0


class TestVerifyMartingaleInsufficientPairs:
    """Only 2 escalation pairs → not enough evidence (need ≥3)."""

    def test_two_pairs_not_verified(self):
        trades = [
            {"trade_id": "tx1", "open_ts": "2025-08-01T10:00:00Z", "close_ts": "2025-08-01T10:00:30Z",
             "stake_usd": 5,  "payout_usd": 0,  "result": "loss"},
            {"trade_id": "tx2", "open_ts": "2025-08-01T10:01:00Z", "close_ts": "2025-08-01T10:01:30Z",
             "stake_usd": 10, "payout_usd": 0,  "result": "loss"},
            {"trade_id": "tx3", "open_ts": "2025-08-01T10:02:00Z", "close_ts": "2025-08-01T10:02:30Z",
             "stake_usd": 20, "payout_usd": 38, "result": "win"},
            # No further post-loss escalation
        ]
        result = verify_martingale("u_test", trades, ["martingale"])
        assert result["verified"] is False

    def test_no_escalation_pairs_not_verified(self):
        # All same stake → no escalation ratio ≥ 1.5
        trades = [
            {"trade_id": "tx1", "open_ts": "2025-08-01T10:00:00Z", "close_ts": "2025-08-01T10:00:30Z",
             "stake_usd": 10, "payout_usd": 0, "result": "loss"},
            {"trade_id": "tx2", "open_ts": "2025-08-01T10:01:00Z", "close_ts": "2025-08-01T10:01:30Z",
             "stake_usd": 10, "payout_usd": 0, "result": "loss"},
            {"trade_id": "tx3", "open_ts": "2025-08-01T10:02:00Z", "close_ts": "2025-08-01T10:02:30Z",
             "stake_usd": 10, "payout_usd": 19, "result": "win"},
        ]
        result = verify_martingale("u_test", trades, ["martingale"])
        assert result["verified"] is False


class TestVerifyMartingaleNotClassified:
    """User not classified as martingale → skip audit, return not-eligible record."""

    def test_non_martingale_user_returns_not_eligible(self):
        result = verify_martingale("u_normal", U001_TRADES, ["normal"])
        assert result["verified"] is False
        assert "note" in result or result.get("pattern") is None or result.get("eligible") is False


class TestAuditOutputStructure:

    def test_output_has_required_keys(self):
        result = verify_martingale("u_001", U001_TRADES, ["martingale"])
        assert "user_id" in result
        assert "pattern" in result
        assert "verified" in result
        assert "supporting_trade_sequence" in result
        assert "calculation" in result

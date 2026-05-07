"""
Golden-value tests for deterministic feature computation.

All expected values are pre-computed from the u_001 seed fixture:
  trades t_00001..t_00004, single session s_4412, 2025-08-01T08:14-08:16 UTC.
"""

import pytest
from pytest import approx

from src.pipeline.features import compute_features


# ---------------------------------------------------------------------------
# u_001 golden values
# ---------------------------------------------------------------------------

class TestU001Features:
    """Known-input / known-output for the bundled u_001 martingale fixture."""

    @pytest.fixture(autouse=True)
    def features(self, u001_trades, calendar):
        return compute_features(u001_trades, calendar)

    def test_total_trades(self, features):
        assert features["total_trades"] == 4

    def test_average_stake(self, features):
        # (5 + 10 + 20 + 40) / 4 = 18.75
        assert features["average_stake"] == approx(18.75)

    def test_stake_escalation_ratio_after_losses(self, features):
        # Three post-loss pairs: 10/5=2, 20/10=2, 40/20=2 → mean = 2.0
        assert features["stake_escalation_ratio_after_losses"] == approx(2.0)

    def test_n_post_loss_pairs_audit_field(self, features):
        assert features["n_post_loss_pairs"] == 3

    def test_trades_per_minute(self, features):
        # active_seconds = 151, active_minutes = 151/60
        # 4 / (151/60) = 240/151 ≈ 1.589404
        assert features["trades_per_minute"] == approx(240 / 151, rel=1e-5)

    def test_active_seconds_audit_field(self, features):
        assert features["active_seconds"] == approx(151.0)

    def test_pct_news_adjacent_zero(self, features):
        # All u_001 trades at 08:14-08:16; nearest high-impact events at 12:00 and 13:30
        assert features["pct_trades_within_5min_of_high_impact_news"] == approx(0.0)

    def test_win_rate(self, features):
        # 1 win out of 4 trades
        assert features["win_rate"] == approx(0.25)

    def test_n_wins_audit_field(self, features):
        assert features["n_wins"] == 1

    def test_n_losses_audit_field(self, features):
        assert features["n_losses"] == 3

    def test_revenge_interval_seconds_avg(self, features):
        # Intervals after each loss: 6s (t1→t2), 6s (t2→t3), 7s (t3→t4) → mean = 19/3
        assert features["revenge_interval_seconds_avg"] == approx(19 / 3, rel=1e-5)

    def test_n_loss_to_next_pairs_audit_field(self, features):
        assert features["n_loss_to_next_pairs"] == 3

    def test_longest_losing_streak(self, features):
        # t_00001, t_00002, t_00003 are consecutive losses
        assert features["longest_losing_streak"] == 3

    def test_total_net_pnl_usd(self, features):
        # (0-5) + (0-10) + (0-20) + (76-40) = -5 -10 -20 +36 = +1
        assert features["total_net_pnl_usd"] == approx(1.0)

    def test_average_session_duration_seconds(self, features):
        # Only session s_4412: max(close_ts) - min(open_ts) = 08:16:53 - 08:14:22 = 151s
        assert features["average_session_duration_seconds"] == approx(151.0)

    def test_n_sessions_audit_field(self, features):
        assert features["n_sessions"] == 1

    def test_all_values_rounded_to_6dp(self, features):
        float_keys = [
            "average_stake", "stake_escalation_ratio_after_losses",
            "trades_per_minute", "pct_trades_within_5min_of_high_impact_news",
            "win_rate", "revenge_interval_seconds_avg",
            "total_net_pnl_usd", "average_session_duration_seconds",
        ]
        for key in float_keys:
            val = features[key]
            assert round(val, 6) == val, f"{key} not rounded to 6dp: {val}"


# ---------------------------------------------------------------------------
# u_002 — news-adjacent detection
# ---------------------------------------------------------------------------

class TestU002Features:
    """u_002 has one trade at 13:29:55, within 5 seconds of the 13:30:00 US NFP event."""

    @pytest.fixture(autouse=True)
    def features(self, u002_trades, calendar):
        return compute_features(u002_trades, calendar)

    def test_total_trades(self, features):
        assert features["total_trades"] == 1

    def test_pct_news_adjacent_is_one(self, features):
        # Trade at 13:29:55 is 5 seconds before 13:30:00 high-impact event → within 5 min
        assert features["pct_trades_within_5min_of_high_impact_news"] == approx(1.0)

    def test_n_news_adjacent_audit_field(self, features):
        assert features["n_news_adjacent"] == 1

    def test_win_rate_zero(self, features):
        assert features["win_rate"] == approx(0.0)

    def test_net_pnl_negative(self, features):
        # payout 0 - stake 50 = -50
        assert features["total_net_pnl_usd"] == approx(-50.0)

    def test_longest_losing_streak_one(self, features):
        assert features["longest_losing_streak"] == 1

    def test_no_revenge_interval_single_trade(self, features):
        # Only one trade — no prior loss to measure interval from
        assert features["revenge_interval_seconds_avg"] == approx(0.0)
        assert features["n_loss_to_next_pairs"] == 0

    def test_no_escalation_single_trade(self, features):
        # No post-loss pairs
        assert features["stake_escalation_ratio_after_losses"] == approx(0.0)
        assert features["n_post_loss_pairs"] == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestFeaturesEdgeCases:

    def test_all_wins_no_escalation(self, calendar):
        trades = [
            {"trade_id": "tx1", "open_ts": "2025-08-01T10:00:00Z", "close_ts": "2025-08-01T10:00:30Z",
             "stake_usd": 10, "payout_usd": 19, "result": "win", "session_id": "sx1"},
            {"trade_id": "tx2", "open_ts": "2025-08-01T10:01:00Z", "close_ts": "2025-08-01T10:01:30Z",
             "stake_usd": 20, "payout_usd": 38, "result": "win", "session_id": "sx1"},
        ]
        f = compute_features(trades, calendar)
        assert f["stake_escalation_ratio_after_losses"] == approx(0.0)
        assert f["n_post_loss_pairs"] == 0
        assert f["win_rate"] == approx(1.0)
        assert f["longest_losing_streak"] == 0
        assert f["n_loss_to_next_pairs"] == 0

    def test_all_losses_no_revenge_after_last(self, calendar):
        trades = [
            {"trade_id": "tx1", "open_ts": "2025-08-01T10:00:00Z", "close_ts": "2025-08-01T10:00:30Z",
             "stake_usd": 5, "payout_usd": 0, "result": "loss", "session_id": "sx1"},
            {"trade_id": "tx2", "open_ts": "2025-08-01T10:01:00Z", "close_ts": "2025-08-01T10:01:30Z",
             "stake_usd": 10, "payout_usd": 0, "result": "loss", "session_id": "sx1"},
        ]
        f = compute_features(trades, calendar)
        # Last trade is a loss, no next trade → only 1 revenge interval (tx1 → tx2)
        assert f["n_loss_to_next_pairs"] == 1
        assert f["longest_losing_streak"] == 2

    def test_medium_impact_events_excluded(self, calendar):
        # ISM Services PMI is medium impact — should not count as news adjacent
        trades = [
            {"trade_id": "tx1", "open_ts": "2025-08-04T14:01:00Z", "close_ts": "2025-08-04T14:01:30Z",
             "stake_usd": 10, "payout_usd": 0, "result": "loss", "session_id": "sx1"},
        ]
        f = compute_features(trades, calendar)
        assert f["pct_trades_within_5min_of_high_impact_news"] == approx(0.0)

    def test_deterministic_order_independence(self, calendar):
        """Shuffling trade order must not change feature values (function should sort by open_ts)."""
        trades_ordered = [
            {"trade_id": "tx1", "open_ts": "2025-08-01T10:00:00Z", "close_ts": "2025-08-01T10:00:30Z",
             "stake_usd": 5, "payout_usd": 0, "result": "loss", "session_id": "sx1"},
            {"trade_id": "tx2", "open_ts": "2025-08-01T10:01:00Z", "close_ts": "2025-08-01T10:01:30Z",
             "stake_usd": 10, "payout_usd": 0, "result": "loss", "session_id": "sx1"},
            {"trade_id": "tx3", "open_ts": "2025-08-01T10:02:00Z", "close_ts": "2025-08-01T10:02:30Z",
             "stake_usd": 20, "payout_usd": 38, "result": "win", "session_id": "sx1"},
        ]
        trades_shuffled = [trades_ordered[2], trades_ordered[0], trades_ordered[1]]
        f1 = compute_features(trades_ordered, calendar)
        f2 = compute_features(trades_shuffled, calendar)
        assert f1["stake_escalation_ratio_after_losses"] == f2["stake_escalation_ratio_after_losses"]
        assert f1["longest_losing_streak"] == f2["longest_losing_streak"]
        assert f1["revenge_interval_seconds_avg"] == f2["revenge_interval_seconds_avg"]

    def test_multiple_sessions_average_duration(self, calendar):
        trades = [
            # session A: 60s span
            {"trade_id": "tx1", "open_ts": "2025-08-01T10:00:00Z", "close_ts": "2025-08-01T10:00:30Z",
             "stake_usd": 10, "payout_usd": 0, "result": "loss", "session_id": "sA"},
            {"trade_id": "tx2", "open_ts": "2025-08-01T10:00:45Z", "close_ts": "2025-08-01T10:01:00Z",
             "stake_usd": 10, "payout_usd": 19, "result": "win", "session_id": "sA"},
            # session B: 30s span
            {"trade_id": "tx3", "open_ts": "2025-08-01T11:00:00Z", "close_ts": "2025-08-01T11:00:30Z",
             "stake_usd": 10, "payout_usd": 0, "result": "loss", "session_id": "sB"},
        ]
        f = compute_features(trades, calendar)
        assert f["n_sessions"] == 2
        # session A: max(close_ts)=10:01:00, min(open_ts)=10:00:00 → 60s
        # session B: max(close_ts)=11:00:30, min(open_ts)=11:00:00 → 30s
        # mean = (60 + 30) / 2 = 45s
        assert f["average_session_duration_seconds"] == approx(45.0)

    def test_exact_5min_boundary_is_included(self, calendar):
        # Trade exactly 5 min before a high-impact event should count
        trades = [
            {"trade_id": "tx1", "open_ts": "2025-08-01T13:25:00Z", "close_ts": "2025-08-01T13:25:30Z",
             "stake_usd": 10, "payout_usd": 0, "result": "loss", "session_id": "sx1"},
        ]
        f = compute_features(trades, calendar)
        assert f["pct_trades_within_5min_of_high_impact_news"] == approx(1.0)

    def test_just_outside_5min_boundary_excluded(self, calendar):
        # Trade 5 min 1 second before a high-impact event should NOT count
        trades = [
            {"trade_id": "tx1", "open_ts": "2025-08-01T13:24:59Z", "close_ts": "2025-08-01T13:25:29Z",
             "stake_usd": 10, "payout_usd": 0, "result": "loss", "session_id": "sx1"},
        ]
        f = compute_features(trades, calendar)
        assert f["pct_trades_within_5min_of_high_impact_news"] == approx(0.0)

"""
Tests for deterministic dataset extension.

The extension must:
  - preserve all original trades verbatim
  - produce ≥ 8 unique users and ≥ 800 trades
  - be byte-identical across runs with the same seed
  - raise on missing required fields in input trades
"""

import json
import pathlib

import pytest

from src.pipeline.dataset import extend_to_minimum, validate_and_extend, MIN_USERS, MIN_TRADES

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture()
def seed_trades_raw():
    return json.loads((FIXTURES / "trades_small.json").read_text())


@pytest.fixture()
def seed_trades(seed_trades_raw):
    return seed_trades_raw["trades"]


@pytest.fixture()
def seed_calendar():
    return json.loads((FIXTURES / "calendar_small.json").read_text())


# ---------------------------------------------------------------------------
# validate_and_extend — input validation
# ---------------------------------------------------------------------------

class TestValidateAndExtend:

    def test_valid_inputs_do_not_raise(self, seed_trades_raw, seed_calendar):
        validate_and_extend(seed_trades_raw, seed_calendar)  # must not raise

    def test_missing_required_trade_field_raises(self, seed_calendar):
        bad = {"trades": [{"user_id": "u_001", "trade_id": "t_1"}]}  # most fields missing
        with pytest.raises(Exception):
            validate_and_extend(bad, seed_calendar)

    def test_empty_trades_still_extends_to_minimum(self, seed_calendar):
        # Spec: extend or generate to ≥8 users / ≥800 trades; empty input is valid
        result = validate_and_extend({"trades": []}, seed_calendar)
        assert len({t["user_id"] for t in result}) >= MIN_USERS
        assert len(result) >= MIN_TRADES

    def test_returns_list_of_trade_dicts(self, seed_trades_raw, seed_calendar):
        result = validate_and_extend(seed_trades_raw, seed_calendar)
        assert isinstance(result, list)
        assert all(isinstance(t, dict) for t in result)

    def test_at_least_min_users(self, seed_trades_raw, seed_calendar):
        result = validate_and_extend(seed_trades_raw, seed_calendar)
        assert len({t["user_id"] for t in result}) >= MIN_USERS

    def test_at_least_min_trades(self, seed_trades_raw, seed_calendar):
        result = validate_and_extend(seed_trades_raw, seed_calendar)
        assert len(result) >= MIN_TRADES


# ---------------------------------------------------------------------------
# extend_to_minimum — core behaviour
# ---------------------------------------------------------------------------

class TestExtendToMinimum:

    @pytest.fixture()
    def extended(self, seed_trades, seed_calendar):
        return extend_to_minimum(seed_trades, seed_calendar, seed=42)

    def test_at_least_8_users(self, extended):
        user_ids = {t["user_id"] for t in extended}
        assert len(user_ids) >= 8

    def test_at_least_800_trades(self, extended):
        assert len(extended) >= 800

    def test_original_trades_preserved_verbatim(self, extended, seed_trades):
        extended_by_id = {t["trade_id"]: t for t in extended}
        for orig in seed_trades:
            tid = orig["trade_id"]
            assert tid in extended_by_id, f"Original trade {tid} missing from extended set"
            assert extended_by_id[tid] == orig, f"Trade {tid} was mutated"

    def test_original_trades_not_duplicated(self, extended, seed_trades):
        orig_ids = [t["trade_id"] for t in seed_trades]
        extended_ids = [t["trade_id"] for t in extended]
        for orig_id in orig_ids:
            assert extended_ids.count(orig_id) == 1

    def test_all_synthetic_trades_have_required_fields(self, extended, seed_trades):
        required = {"user_id", "trade_id", "open_ts", "close_ts", "instrument",
                    "direction", "stake_usd", "payout_usd", "result", "session_id"}
        orig_ids = {t["trade_id"] for t in seed_trades}
        for trade in extended:
            if trade["trade_id"] not in orig_ids:
                assert required.issubset(trade.keys()), f"Synthetic trade missing fields: {trade}"

    def test_all_result_values_valid(self, extended):
        for trade in extended:
            assert trade["result"] in {"win", "loss"}, f"Invalid result: {trade['result']}"

    def test_all_stakes_positive(self, extended):
        for trade in extended:
            assert trade["stake_usd"] > 0, f"Non-positive stake: {trade}"

    def test_synthetic_user_ids_follow_anonymous_pattern(self, extended, seed_trades):
        orig_user_ids = {t["user_id"] for t in seed_trades}
        for trade in extended:
            if trade["user_id"] not in orig_user_ids:
                uid = trade["user_id"]
                assert "synth" in uid or uid.startswith("u_"), \
                    f"Unexpected synthetic user_id format: {uid}"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

class TestExtensionDeterminism:

    def test_same_seed_produces_identical_output(self, seed_trades, seed_calendar):
        ext1 = extend_to_minimum(seed_trades, seed_calendar, seed=42)
        ext2 = extend_to_minimum(seed_trades, seed_calendar, seed=42)
        assert ext1 == ext2

    def test_different_seed_produces_different_output(self, seed_trades, seed_calendar):
        ext1 = extend_to_minimum(seed_trades, seed_calendar, seed=42)
        ext2 = extend_to_minimum(seed_trades, seed_calendar, seed=99)
        ids1 = {t["trade_id"] for t in ext1}
        ids2 = {t["trade_id"] for t in ext2}
        assert ids1 != ids2

    def test_idempotent_when_already_at_minimum(self, seed_calendar):
        """If input already has ≥8 users and ≥800 trades, no new trades are added."""
        trades = []
        for u in range(8):
            for i in range(100):
                trades.append({
                    "user_id": f"u_{u:03d}", "trade_id": f"t_{u}_{i}",
                    "open_ts": "2025-08-01T10:00:00Z", "close_ts": "2025-08-01T10:00:30Z",
                    "instrument": "V75", "direction": "rise",
                    "stake_usd": 10, "payout_usd": 0, "result": "loss",
                    "session_id": "s_1",
                })
        original_ids = {t["trade_id"] for t in trades}
        extended = extend_to_minimum(trades, seed_calendar, seed=42)
        extended_ids = {t["trade_id"] for t in extended}
        assert original_ids == extended_ids

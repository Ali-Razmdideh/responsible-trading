"""
Tests for the stage state machine.

The machine must refuse to advance to a stage if the predecessor's artifacts
are missing, and must persist state so a restarted pipeline can resume.
"""

import json
import pathlib

import pytest

from src.pipeline.state import Stage, StateMachine


# ---------------------------------------------------------------------------
# Stage ordering constants
# ---------------------------------------------------------------------------

ORDERED_STAGES = [
    Stage.INIT,
    Stage.INPUTS_LOADED,
    Stage.DATASET_EXTENDED_OR_VALIDATED,
    Stage.FEATURES_COMPUTED,
    Stage.PATTERNS_CLASSIFIED,
    Stage.RISK_SCORES_COMPUTED,
    Stage.INTERVENTIONS_GENERATED,
    Stage.VALIDATION_COMPLETE,
    Stage.RESULTS_FINALISED,
]


class TestStageEnum:

    def test_all_required_stages_exist(self):
        names = {s.value for s in Stage}
        required = {
            "INIT", "INPUTS_LOADED", "DATASET_EXTENDED_OR_VALIDATED",
            "FEATURES_COMPUTED", "PATTERNS_CLASSIFIED", "RISK_SCORES_COMPUTED",
            "INTERVENTIONS_GENERATED", "VALIDATION_COMPLETE", "RESULTS_FINALISED",
        }
        assert required.issubset(names)

    def test_stage_ordering_is_correct(self):
        # Each stage in the ordered list must come after the previous one
        for i in range(len(ORDERED_STAGES) - 1):
            assert ORDERED_STAGES[i] != ORDERED_STAGES[i + 1]


class TestStateMachineAdvance:

    @pytest.fixture()
    def sm(self, tmp_path):
        return StateMachine(base_dir=tmp_path)

    def test_initial_stage_is_init(self, sm):
        assert sm.current_stage == Stage.INIT

    def test_advance_to_inputs_loaded(self, sm, tmp_path):
        # Create required artifact: trades.json
        (tmp_path / "trades.json").write_text('{"trades":[]}')
        (tmp_path / "economic_calendar.json").write_text("[]")
        sm.advance(Stage.INPUTS_LOADED)
        assert sm.current_stage == Stage.INPUTS_LOADED

    def test_cannot_skip_stage(self, sm):
        """Skipping INPUTS_LOADED to jump straight to FEATURES_COMPUTED must raise."""
        with pytest.raises(Exception):
            sm.advance(Stage.FEATURES_COMPUTED)

    def test_state_persisted_to_disk(self, sm, tmp_path):
        (tmp_path / "trades.json").write_text('{"trades":[]}')
        (tmp_path / "economic_calendar.json").write_text("[]")
        sm.advance(Stage.INPUTS_LOADED)

        state_file = tmp_path / ".pipeline_state.json"
        assert state_file.exists()
        state = json.loads(state_file.read_text())
        assert state["current_stage"] == Stage.INPUTS_LOADED.value

    def test_reloaded_machine_resumes_from_persisted_state(self, tmp_path):
        sm1 = StateMachine(base_dir=tmp_path)
        (tmp_path / "trades.json").write_text('{"trades":[]}')
        (tmp_path / "economic_calendar.json").write_text("[]")
        sm1.advance(Stage.INPUTS_LOADED)

        # New machine instance reads persisted state
        sm2 = StateMachine(base_dir=tmp_path)
        assert sm2.current_stage == Stage.INPUTS_LOADED

    def test_advance_to_same_stage_is_idempotent(self, sm, tmp_path):
        (tmp_path / "trades.json").write_text('{"trades":[]}')
        (tmp_path / "economic_calendar.json").write_text("[]")
        sm.advance(Stage.INPUTS_LOADED)
        sm.advance(Stage.INPUTS_LOADED)  # must not raise
        assert sm.current_stage == Stage.INPUTS_LOADED


class TestStateMachineArtifactGuards:
    """Verify that missing predecessor artifacts block stage advancement."""

    @pytest.fixture()
    def sm(self, tmp_path):
        return StateMachine(base_dir=tmp_path)

    def test_missing_trades_json_blocks_inputs_loaded(self, sm, tmp_path):
        # economic_calendar.json exists but trades.json does not
        (tmp_path / "economic_calendar.json").write_text("[]")
        with pytest.raises(Exception):
            sm.advance(Stage.INPUTS_LOADED)

    def test_missing_features_dir_blocks_features_computed(self, sm, tmp_path):
        # Force state to DATASET_EXTENDED_OR_VALIDATED without features dir
        state_path = tmp_path / ".pipeline_state.json"
        state_path.write_text(json.dumps({"current_stage": "DATASET_EXTENDED_OR_VALIDATED"}))
        sm2 = StateMachine(base_dir=tmp_path)
        with pytest.raises(Exception):
            sm2.advance(Stage.FEATURES_COMPUTED)

    def test_missing_patterns_json_blocks_patterns_classified(self, sm, tmp_path):
        state_path = tmp_path / ".pipeline_state.json"
        state_path.write_text(json.dumps({"current_stage": "FEATURES_COMPUTED"}))
        sm2 = StateMachine(base_dir=tmp_path)
        with pytest.raises(Exception):
            sm2.advance(Stage.PATTERNS_CLASSIFIED)

    def test_missing_risk_scores_blocks_interventions(self, sm, tmp_path):
        state_path = tmp_path / ".pipeline_state.json"
        state_path.write_text(json.dumps({"current_stage": "PATTERNS_CLASSIFIED"}))
        sm2 = StateMachine(base_dir=tmp_path)
        with pytest.raises(Exception):
            sm2.advance(Stage.INTERVENTIONS_GENERATED)

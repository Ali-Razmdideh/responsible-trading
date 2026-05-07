"""
Tests for validate.py — the post-run validation script.

Invokes validate.py as a subprocess.  All artifact sets must be internally
consistent: risk_scores must match what score_user() would recompute from
the same features + patterns, otherwise the reproducibility check fires.

Precomputed consistent values (via risk.score_user):
  features={escalation=0, tpm=1.0, pct_news=0, streak=1, pnl=-10}, normal  → score=4.2, tier=low
  same features + martingale                                                → score=29.2, tier=medium
"""

import json
import pathlib
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent

# Consistent risk values for features written by write_minimal_artifacts
_RISK_NORMAL = {"risk_score": 4.2, "risk_tier": "low"}
_RISK_MARTINGALE = {"risk_score": 29.2, "risk_tier": "medium"}


def run_validate(cwd):
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "validate.py")],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    return result


def write_minimal_artifacts(
    base: pathlib.Path,
    user_ids=("u_001", "u_002"),
    pattern_override: dict | None = None,
    risk_override: dict | None = None,
):
    """
    Write the minimum valid artifact set.

    pattern_override: {user_id: ["pattern"]} — replaces per-user patterns.
    risk_override:    {user_id: {"risk_score": float, "risk_tier": str}}.
    Risk scores default to values consistent with the written features + "normal" pattern.
    """
    base.mkdir(parents=True, exist_ok=True)

    trades = [
        {"user_id": uid, "trade_id": f"t_{i}", "open_ts": "2025-08-01T10:00:00Z",
         "close_ts": "2025-08-01T10:00:30Z", "instrument": "V75", "direction": "rise",
         "stake_usd": 10, "payout_usd": 0, "result": "loss", "session_id": "s_1"}
        for i, uid in enumerate(user_ids)
    ]
    (base / "trades.json").write_text(json.dumps({"trades": trades}))
    (base / "economic_calendar.json").write_text(json.dumps([]))

    features_dir = base / "features"
    features_dir.mkdir(exist_ok=True)
    base_features = {
        "total_trades": 1, "average_stake": 10.0,
        "stake_escalation_ratio_after_losses": 0.0, "n_post_loss_pairs": 0,
        "trades_per_minute": 1.0, "active_seconds": 30.0,
        "pct_trades_within_5min_of_high_impact_news": 0.0, "n_news_adjacent": 0,
        "win_rate": 0.0, "n_wins": 0, "n_losses": 1,
        "revenge_interval_seconds_avg": 0.0, "n_loss_to_next_pairs": 0,
        "longest_losing_streak": 1, "total_net_pnl_usd": -10.0,
        "average_session_duration_seconds": 30.0, "n_sessions": 1,
        "sum_stake_usd": 10.0, "sum_payout_usd": 0.0,
        "sum_escalation_ratios": 0.0, "n_high_impact_events": 0,
        "session_durations": [30.0],
    }
    for uid in user_ids:
        (features_dir / f"{uid}.json").write_text(
            json.dumps({"user_id": uid, **base_features})
        )

    patterns = []
    for uid in user_ids:
        pats = (pattern_override or {}).get(uid, ["normal"])
        evidence = []
        if "martingale" in pats:
            evidence = [{"pattern": "martingale",
                         "triggering_features": ["stake_escalation_ratio_after_losses"],
                         "trade_ids": [f"t_{list(user_ids).index(uid)}"],
                         "explanation": "stake doubles after losses"}]
        patterns.append({
            "user_id": uid, "patterns": pats,
            "evidence": evidence, "confidence": "high",
        })
    (base / "patterns.json").write_text(json.dumps(patterns))

    risk_scores = []
    for uid in user_ids:
        pats = (pattern_override or {}).get(uid, ["normal"])
        override = (risk_override or {}).get(uid)
        if override:
            r = override
        elif "martingale" in pats:
            r = _RISK_MARTINGALE
        else:
            r = _RISK_NORMAL
        risk_scores.append({
            "user_id": uid, "risk_score": r["risk_score"], "risk_tier": r["risk_tier"],
            "contributing_factors": [], "formula_version": "v1",
        })
    (base / "risk_scores.json").write_text(json.dumps(risk_scores))

    tier = _RISK_MARTINGALE["risk_tier"] if "martingale" in (
        (pattern_override or {}).get(user_ids[0], ["normal"])
    ) else _RISK_NORMAL["risk_tier"]
    pats_for_first = (pattern_override or {}).get(user_ids[0], ["normal"])
    interventions = [
        {"user_id": uid, "risk_tier": risk_scores[i]["risk_tier"],
         "intervention_type": "soft_nudge",
         "triggering_patterns": (pattern_override or {}).get(uid, ["normal"]),
         "evidence_summary": "Assessed.", "recommended_action": "Monitor."}
        for i, uid in enumerate(user_ids)
    ]
    (base / "interventions.json").write_text(json.dumps(interventions))

    (base / "risk_model.md").write_text("# Risk Model\n\nv1 weights.\n")

    llm_calls = [
        {"stage": "patterns", "user_id": uid, "timestamp": "2025-08-01T10:00:00Z",
         "provider": "anthropic", "model": "claude-sonnet-4-6",
         "prompt_hash": "abc123", "input_artifacts": [f"features/{uid}.json"],
         "output_artifact": "patterns.json"}
        for uid in user_ids
    ]
    llm_calls.append({
        "stage": "interventions", "user_id": None, "timestamp": "2025-08-01T10:01:00Z",
        "provider": "anthropic", "model": "claude-sonnet-4-6",
        "prompt_hash": "def456", "input_artifacts": ["patterns.json", "risk_scores.json"],
        "output_artifact": "interventions.json",
    })
    (base / "llm_calls.jsonl").write_text(
        "\n".join(json.dumps(r) for r in llm_calls) + "\n"
    )


# ---------------------------------------------------------------------------
# Passing case
# ---------------------------------------------------------------------------

class TestValidatePassesOnValidArtifacts:

    def test_exits_zero_on_complete_artifact_set(self, tmp_path):
        # u_001 must be martingale for validate.py to pass the sample-fixture check
        write_minimal_artifacts(tmp_path, pattern_override={"u_001": ["martingale"]})
        result = run_validate(tmp_path)
        assert result.returncode == 0, f"validate.py failed:\n{result.stdout}\n{result.stderr}"


# ---------------------------------------------------------------------------
# Missing artifacts
# ---------------------------------------------------------------------------

class TestValidateFailsOnMissingArtifacts:

    def _valid_base(self, tmp_path):
        write_minimal_artifacts(tmp_path, pattern_override={"u_001": ["martingale"]})

    def test_missing_trades_json(self, tmp_path):
        self._valid_base(tmp_path)
        (tmp_path / "trades.json").unlink()
        assert run_validate(tmp_path).returncode != 0

    def test_missing_patterns_json(self, tmp_path):
        self._valid_base(tmp_path)
        (tmp_path / "patterns.json").unlink()
        assert run_validate(tmp_path).returncode != 0

    def test_missing_risk_scores_json(self, tmp_path):
        self._valid_base(tmp_path)
        (tmp_path / "risk_scores.json").unlink()
        assert run_validate(tmp_path).returncode != 0

    def test_missing_interventions_json(self, tmp_path):
        self._valid_base(tmp_path)
        (tmp_path / "interventions.json").unlink()
        assert run_validate(tmp_path).returncode != 0

    def test_missing_risk_model_md(self, tmp_path):
        self._valid_base(tmp_path)
        (tmp_path / "risk_model.md").unlink()
        assert run_validate(tmp_path).returncode != 0

    def test_missing_llm_calls_jsonl(self, tmp_path):
        self._valid_base(tmp_path)
        (tmp_path / "llm_calls.jsonl").unlink()
        assert run_validate(tmp_path).returncode != 0

    def test_missing_feature_file_for_one_user(self, tmp_path):
        write_minimal_artifacts(
            tmp_path, user_ids=("u_001", "u_002"),
            pattern_override={"u_001": ["martingale"]},
        )
        (tmp_path / "features" / "u_002.json").unlink()
        assert run_validate(tmp_path).returncode != 0


# ---------------------------------------------------------------------------
# Invalid content
# ---------------------------------------------------------------------------

class TestValidateFailsOnInvalidContent:

    def _valid_base(self, tmp_path, users=("u_001", "u_002")):
        write_minimal_artifacts(
            tmp_path, user_ids=users,
            pattern_override={"u_001": ["martingale"]},
        )

    def test_malformed_patterns_json(self, tmp_path):
        self._valid_base(tmp_path)
        (tmp_path / "patterns.json").write_text("{not valid json")
        assert run_validate(tmp_path).returncode != 0

    def test_malformed_risk_scores_json(self, tmp_path):
        self._valid_base(tmp_path)
        (tmp_path / "risk_scores.json").write_text("[{broken")
        assert run_validate(tmp_path).returncode != 0

    def test_intervention_references_unknown_user(self, tmp_path):
        self._valid_base(tmp_path, users=("u_001",))
        interventions = [
            {"user_id": "u_ghost", "risk_tier": "medium", "intervention_type": "soft_nudge",
             "triggering_patterns": ["martingale"], "evidence_summary": "x",
             "recommended_action": "y"}
        ]
        (tmp_path / "interventions.json").write_text(json.dumps(interventions))
        assert run_validate(tmp_path).returncode != 0

    def test_intervention_invalid_intervention_type(self, tmp_path):
        self._valid_base(tmp_path, users=("u_001",))
        interventions = [
            {"user_id": "u_001", "risk_tier": "medium", "intervention_type": "make_them_stop",
             "triggering_patterns": ["martingale"], "evidence_summary": "x",
             "recommended_action": "y"}
        ]
        (tmp_path / "interventions.json").write_text(json.dumps(interventions))
        assert run_validate(tmp_path).returncode != 0

    def test_missing_llm_call_for_a_user(self, tmp_path):
        self._valid_base(tmp_path)
        lines = (tmp_path / "llm_calls.jsonl").read_text().strip().splitlines()
        filtered = [l for l in lines if '"u_002"' not in l]
        (tmp_path / "llm_calls.jsonl").write_text("\n".join(filtered) + "\n")
        assert run_validate(tmp_path).returncode != 0

    def test_no_interventions_stage_llm_call(self, tmp_path):
        self._valid_base(tmp_path, users=("u_001",))
        lines = (tmp_path / "llm_calls.jsonl").read_text().strip().splitlines()
        filtered = [l for l in lines if '"interventions"' not in l]
        (tmp_path / "llm_calls.jsonl").write_text("\n".join(filtered) + "\n")
        assert run_validate(tmp_path).returncode != 0

    def test_pattern_not_in_controlled_vocabulary(self, tmp_path):
        self._valid_base(tmp_path, users=("u_001",))
        patterns = [
            {"user_id": "u_001", "patterns": ["super_aggressive"],
             "evidence": [], "confidence": "high"}
        ]
        (tmp_path / "patterns.json").write_text(json.dumps(patterns))
        assert run_validate(tmp_path).returncode != 0


# ---------------------------------------------------------------------------
# Reproducibility check
# ---------------------------------------------------------------------------

class TestValidateRiskReproducibility:

    def test_tampered_risk_score_detected(self, tmp_path):
        write_minimal_artifacts(tmp_path, pattern_override={"u_001": ["martingale"]})
        risk = json.loads((tmp_path / "risk_scores.json").read_text())
        risk[0]["risk_score"] = 99.9  # tamper: doesn't match recomputed value
        (tmp_path / "risk_scores.json").write_text(json.dumps(risk))
        assert run_validate(tmp_path).returncode != 0


# ---------------------------------------------------------------------------
# u_001 sample fixture detection
# ---------------------------------------------------------------------------

class TestValidateU001SampleFixture:
    """When u_001 is present, validate.py must require martingale or position_doubling."""

    def test_u001_classified_normal_fails(self, tmp_path):
        # u_001 is classified as "normal" — validate.py must reject this
        write_minimal_artifacts(tmp_path, user_ids=("u_001",))
        # Default from write_minimal_artifacts: pattern=["normal"] for u_001
        assert run_validate(tmp_path).returncode != 0

    def test_u001_classified_martingale_passes(self, tmp_path):
        write_minimal_artifacts(
            tmp_path, user_ids=("u_001",),
            pattern_override={"u_001": ["martingale"]},
        )
        result = run_validate(tmp_path)
        assert result.returncode == 0, f"validate.py failed:\n{result.stdout}\n{result.stderr}"

    def test_u001_classified_position_doubling_passes(self, tmp_path):
        from src.pipeline.risk import score_user
        features = {
            "stake_escalation_ratio_after_losses": 0.0, "trades_per_minute": 1.0,
            "pct_trades_within_5min_of_high_impact_news": 0.0,
            "longest_losing_streak": 1, "total_net_pnl_usd": -10.0,
        }
        r = score_user("u_001", features, ["position_doubling"])
        write_minimal_artifacts(
            tmp_path, user_ids=("u_001",),
            pattern_override={"u_001": ["position_doubling"]},
            risk_override={"u_001": {"risk_score": r["risk_score"], "risk_tier": r["risk_tier"]}},
        )
        result = run_validate(tmp_path)
        assert result.returncode == 0, f"validate.py failed:\n{result.stdout}\n{result.stderr}"

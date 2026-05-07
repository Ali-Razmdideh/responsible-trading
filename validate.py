#!/usr/bin/env python3
"""
Validation script for the responsible-trading pipeline.

Exit code 0 = all checks pass.
Exit code 1 = one or more checks failed (diagnostics printed to stdout).

Artifact root = current working directory (so tests can run it from tmp_path).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Artifact root is wherever the script is invoked from (cwd).
ARTIFACTS = Path.cwd()

# Imports from the pipeline package — located next to this script.
_REPO = Path(__file__).parent
sys.path.insert(0, str(_REPO))  # noqa: E402 — must precede local imports

from src.pipeline.io import read_jsonl  # noqa: E402
from src.pipeline.risk import score_user  # noqa: E402
from src.pipeline.vocab import INTERVENTIONS, PATTERNS  # noqa: E402


def _trades_file() -> Path:
    """Return the canonical trades file: extended artifact if it exists, else input."""
    extended = ARTIFACTS / "artifacts" / "trades_extended.json"
    return extended if extended.exists() else ARTIFACTS / "trades.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(f"FAIL: {message}")


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_required_files(errors: list[str]) -> None:
    required = [
        ARTIFACTS / "trades.json",
        ARTIFACTS / "economic_calendar.json",
        ARTIFACTS / "patterns.json",
        ARTIFACTS / "risk_scores.json",
        ARTIFACTS / "risk_model.md",
        ARTIFACTS / "interventions.json",
        ARTIFACTS / "llm_calls.jsonl",
        ARTIFACTS / "features",
    ]
    for p in required:
        if not p.exists():
            errors.append(f"MISSING required artifact: {p.name}")


def check_json_valid(errors: list[str]) -> None:
    for path in ARTIFACTS.glob("*.json"):
        try:
            json.loads(path.read_text())
        except json.JSONDecodeError as e:
            errors.append(f"INVALID JSON: {path.name} — {e}")
    features_dir = ARTIFACTS / "features"
    if features_dir.exists():
        for path in features_dir.glob("*.json"):
            try:
                json.loads(path.read_text())
            except json.JSONDecodeError as e:
                errors.append(f"INVALID JSON: features/{path.name} — {e}")


def check_feature_files_per_user(errors: list[str]) -> None:
    trades_path = _trades_file()
    if not trades_path.exists():
        return
    trades_data = json.loads(trades_path.read_text())
    user_ids = {t["user_id"] for t in trades_data.get("trades", [])}
    features_dir = ARTIFACTS / "features"
    for uid in sorted(user_ids):
        if not (features_dir / f"{uid}.json").exists():
            errors.append(f"MISSING feature file: features/{uid}.json")


def check_stage_ordering(errors: list[str]) -> None:
    state_file = ARTIFACTS / ".pipeline_state.json"
    if state_file.exists():
        state = json.loads(state_file.read_text())
        history = state.get("history", [])
        stage_names = [h["stage"] for h in history]
        required_order = [
            "INPUTS_LOADED",
            "DATASET_EXTENDED_OR_VALIDATED",
            "FEATURES_COMPUTED",
            "PATTERNS_CLASSIFIED",
            "RISK_SCORES_COMPUTED",
            "INTERVENTIONS_GENERATED",
        ]
        prev_idx = -1
        for stage in required_order:
            if stage in stage_names:
                idx = stage_names.index(stage)
                if idx <= prev_idx:
                    errors.append(f"STAGE ORDER VIOLATION: {stage} out of order")
                prev_idx = idx
        return

    # No state file → fall back to mtime ordering on the artifacts themselves.
    features_dir = ARTIFACTS / "features"
    patterns = ARTIFACTS / "patterns.json"
    risk = ARTIFACTS / "risk_scores.json"
    interventions = ARTIFACTS / "interventions.json"
    if not all(p.exists() for p in (features_dir, patterns, risk, interventions)):
        return
    feature_mtime = max(
        (p.stat().st_mtime for p in features_dir.glob("*.json")), default=0.0
    )
    chain = [
        ("features/", feature_mtime),
        ("patterns.json", patterns.stat().st_mtime),
        ("risk_scores.json", risk.stat().st_mtime),
        ("interventions.json", interventions.stat().st_mtime),
    ]
    for (a_name, a_mt), (b_name, b_mt) in zip(chain, chain[1:]):
        if a_mt > b_mt:
            errors.append(
                f"STAGE ORDER VIOLATION (mtime): {a_name} newer than {b_name}"
            )


def check_risk_reproducibility(errors: list[str]) -> None:
    risk_path = ARTIFACTS / "risk_scores.json"
    patterns_path = ARTIFACTS / "patterns.json"
    features_dir = ARTIFACTS / "features"

    if not all(p.exists() for p in [risk_path, patterns_path, features_dir]):
        return

    risk_records = json.loads(risk_path.read_text())
    patterns_list = json.loads(patterns_path.read_text())
    patterns_by_user = {p["user_id"]: p["patterns"] for p in patterns_list}

    for rec in risk_records:
        uid = rec["user_id"]
        fpath = features_dir / f"{uid}.json"
        if not fpath.exists():
            continue
        features = json.loads(fpath.read_text())
        recomputed = score_user(uid, features, patterns_by_user.get(uid, ["normal"]))
        if recomputed["risk_score"] != rec["risk_score"]:
            errors.append(
                f"RISK NOT REPRODUCIBLE for {uid}: "
                f"on-disk={rec['risk_score']} "
                f"recomputed={recomputed['risk_score']}"
            )


def check_patterns_vocab(errors: list[str]) -> None:
    patterns_path = ARTIFACTS / "patterns.json"
    if not patterns_path.exists():
        return
    for rec in json.loads(patterns_path.read_text()):
        for pat in rec.get("patterns", []):
            if pat not in PATTERNS:
                errors.append(f"Unknown pattern '{pat}' for user {rec.get('user_id')}")


def check_patterns_evidence_trade_ids(errors: list[str]) -> None:
    """Non-trivial pattern classifications must cite supporting trade_ids."""
    patterns_path = ARTIFACTS / "patterns.json"
    trades_path = _trades_file()
    if not patterns_path.exists() or not trades_path.exists():
        return
    valid_trade_ids = {
        t["trade_id"] for t in json.loads(trades_path.read_text()).get("trades", [])
    }
    trivial = {"normal", "insufficient_evidence"}
    for rec in json.loads(patterns_path.read_text()):
        uid = rec.get("user_id")
        for ev in rec.get("evidence", []):
            pat = ev.get("pattern")
            if pat in trivial:
                continue
            tids = ev.get("trade_ids", [])
            _check(
                bool(tids),
                f"pattern evidence missing trade_ids: {uid}/{pat}",
                errors,
            )
            for tid in tids:
                _check(
                    tid in valid_trade_ids,
                    f"pattern evidence references unknown trade {tid} "
                    f"({uid}/{pat})",
                    errors,
                )


def check_interventions_ranked_by_risk(errors: list[str]) -> None:
    interventions_path = ARTIFACTS / "interventions.json"
    risk_path = ARTIFACTS / "risk_scores.json"
    if not interventions_path.exists() or not risk_path.exists():
        return
    score_map = {
        r["user_id"]: r["risk_score"] for r in json.loads(risk_path.read_text())
    }
    interventions = json.loads(interventions_path.read_text())
    scores = [score_map.get(rec["user_id"], 0.0) for rec in interventions]
    _check(
        scores == sorted(scores, reverse=True),
        f"interventions not ranked by risk_score desc: got {scores}",
        errors,
    )


def check_interventions_reference_valid_users(errors: list[str]) -> None:
    trades_path = _trades_file()
    interventions_path = ARTIFACTS / "interventions.json"
    if not trades_path.exists() or not interventions_path.exists():
        return

    user_ids = {
        t["user_id"] for t in json.loads(trades_path.read_text()).get("trades", [])
    }
    patterns_path = ARTIFACTS / "patterns.json"
    patterns_by_user: dict[str, list[str]] = {}
    if patterns_path.exists():
        for p in json.loads(patterns_path.read_text()):
            patterns_by_user[p["user_id"]] = p["patterns"]

    for rec in json.loads(interventions_path.read_text()):
        uid = rec.get("user_id")
        _check(
            uid in user_ids,
            f"intervention user_id not in trades: {uid}",
            errors,
        )
        itype = rec.get("intervention_type", "")
        _check(
            itype in INTERVENTIONS,
            f"invalid intervention_type '{itype}' for {uid}",
            errors,
        )
        trig = set(rec.get("triggering_patterns", []))
        invalid_pats = trig - PATTERNS
        _check(
            not invalid_pats,
            f"unknown triggering_patterns {invalid_pats} for {uid}",
            errors,
        )
        _check(
            bool(rec.get("evidence_summary")),
            f"missing evidence_summary for {uid}",
            errors,
        )


def check_llm_call_log(errors: list[str]) -> None:
    log_path = ARTIFACTS / "llm_calls.jsonl"
    if not log_path.exists():
        errors.append("MISSING: llm_calls.jsonl")
        return

    trades_path = _trades_file()
    if not trades_path.exists():
        return

    raw = json.loads(trades_path.read_text()).get("trades", [])
    user_ids = sorted({t["user_id"] for t in raw})
    records = read_jsonl(log_path)

    pattern_records = [r for r in records if r.get("stage") == "patterns"]
    logged_users = sorted(str(r.get("user_id", "")) for r in pattern_records)
    _check(
        logged_users == user_ids,
        f"llm_calls.jsonl: expected one 'patterns' record per user. "
        f"Expected {user_ids}, got {logged_users}",
        errors,
    )

    intervention_records = [r for r in records if r.get("stage") == "interventions"]
    _check(
        len(intervention_records) >= 1,
        "llm_calls.jsonl: missing 'interventions' record",
        errors,
    )


def check_u001_sample_detection(errors: list[str]) -> None:
    trades_path = _trades_file()
    patterns_path = ARTIFACTS / "patterns.json"
    audit_path = ARTIFACTS / "false_positive_audit.json"

    if not trades_path.exists() or not patterns_path.exists():
        return

    user_ids = {
        t["user_id"] for t in json.loads(trades_path.read_text()).get("trades", [])
    }
    if "u_001" not in user_ids:
        return

    patterns_list = json.loads(patterns_path.read_text())
    u001_rec = next((p for p in patterns_list if p["user_id"] == "u_001"), None)
    if u001_rec is None:
        errors.append("u_001 present in trades but missing from patterns.json")
        return

    u001_patterns = set(u001_rec.get("patterns", []))
    _check(
        bool(u001_patterns & {"martingale", "position_doubling"}),
        "u_001 not classified as martingale or position_doubling",
        errors,
    )

    if audit_path.exists():
        audit = json.loads(audit_path.read_text())
        if audit.get("user_id") == "u_001":
            _check(
                audit.get("verified") is True,
                "false_positive_audit: u_001 martingale not verified",
                errors,
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    errors: list[str] = []

    print("Running pipeline validation...\n")

    check_required_files(errors)
    check_json_valid(errors)
    check_feature_files_per_user(errors)
    check_stage_ordering(errors)
    check_patterns_vocab(errors)
    check_patterns_evidence_trade_ids(errors)
    check_risk_reproducibility(errors)
    check_interventions_reference_valid_users(errors)
    check_interventions_ranked_by_risk(errors)
    check_llm_call_log(errors)
    check_u001_sample_detection(errors)

    if errors:
        print(f"VALIDATION FAILED — {len(errors)} error(s):\n")
        for e in errors:
            print(f"  x {e}")
        print()
        return 1

    print("VALIDATION PASSED — all checks green.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

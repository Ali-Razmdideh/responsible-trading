#!/usr/bin/env python3
"""
Responsible-Trading Behavioural Pipeline — CLI entrypoint.

Usage:
    python run.py                    # full pipeline, real LLM
    python run.py --mock-llm         # full pipeline, deterministic mock
    python run.py --stage features   # run up to and including a stage
    python run.py --seed 123         # synthetic data seed (default 42)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src.pipeline.audit import run_audit
from src.pipeline.cohort import compute_cohort_insights
from src.pipeline.copy import generate_and_save_copy
from src.pipeline.dataset import validate_and_extend
from src.pipeline.features import compute_features
from src.pipeline.interventions import generate_interventions
from src.pipeline.io import dump_json, ensure_dir, load_json
from src.pipeline.patterns import classify_all_users
from src.pipeline.regulatory import generate_regulatory_mapping
from src.pipeline.risk import score_user
from src.pipeline.state import Stage, StateMachine


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Responsible-trading pipeline")
    p.add_argument(
        "--mock-llm",
        action="store_true",
        default=os.environ.get("PIPELINE_MOCK_LLM", "").lower() == "true",
        help="Use deterministic mock LLM (no API calls)",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=int(os.environ.get("PIPELINE_SEED", "42")),
        help="Random seed for synthetic data (default: 42)",
    )
    p.add_argument(
        "--stage",
        default=None,
        help="Stop after this stage (e.g. features, patterns, risk)",
    )
    p.add_argument(
        "--reset",
        action="store_true",
        help="Reset pipeline state before running",
    )
    return p.parse_args()


STAGE_ALIASES = {
    "inputs": Stage.INPUTS_LOADED,
    "dataset": Stage.DATASET_EXTENDED_OR_VALIDATED,
    "features": Stage.FEATURES_COMPUTED,
    "patterns": Stage.PATTERNS_CLASSIFIED,
    "risk": Stage.RISK_SCORES_COMPUTED,
    "interventions": Stage.INTERVENTIONS_GENERATED,
    "validation": Stage.VALIDATION_COMPLETE,
    "final": Stage.RESULTS_FINALISED,
}


def _stop_after(stage: Stage, stop: Stage | None) -> bool:
    if stop is None:
        return False
    from src.pipeline.state import STAGE_ORDER

    return STAGE_ORDER.index(stage) >= STAGE_ORDER.index(stop)


def main() -> None:
    args = _parse_args()
    mock = args.mock_llm

    stop_stage: Stage | None = None
    if args.stage:
        key = args.stage.lower().replace("-", "_")
        stop_stage = STAGE_ALIASES.get(key) or Stage(args.stage.upper())

    sm = StateMachine(base_dir=ROOT)
    if args.reset:
        sm.reset()

    # Truncate llm_calls.jsonl at the start of every run so per-user
    # uniqueness checks in validate.py reflect *this* run, not history.
    llm_log = ROOT / "llm_calls.jsonl"
    if llm_log.exists():
        llm_log.unlink()

    # ------------------------------------------------------------------ INIT
    sm.advance(Stage.INPUTS_LOADED)

    # ---------------------------------------------------- INPUTS_LOADED
    print("[run] Loading inputs...")
    raw_trades = load_json(ROOT / "trades.json")
    calendar = load_json(ROOT / "economic_calendar.json")
    if _stop_after(Stage.INPUTS_LOADED, stop_stage):
        return

    # ----------------------------------------- DATASET_EXTENDED_OR_VALIDATED
    print("[run] Validating / extending dataset...")
    original_trades = list(raw_trades.get("trades", []))
    all_trades = validate_and_extend(raw_trades, calendar, seed=args.seed)
    # Never overwrite the user-supplied input. If extension occurred, write the
    # extended ledger to artifacts/ so the input swap workflow is preserved.
    if len(all_trades) != len(original_trades):
        dump_json(ROOT / "artifacts" / "trades_extended.json", {"trades": all_trades})
    sm.advance(Stage.DATASET_EXTENDED_OR_VALIDATED)
    if _stop_after(Stage.DATASET_EXTENDED_OR_VALIDATED, stop_stage):
        return

    # --------------------------------------------------- FEATURES_COMPUTED
    print("[run] Computing features...")
    trades_by_user: dict[str, list[dict[str, Any]]] = {}
    for t in all_trades:
        trades_by_user.setdefault(t["user_id"], []).append(t)

    features_dir = ensure_dir(ROOT / "features")
    features_by_user: dict[str, dict[str, Any]] = {}
    for user_id in sorted(trades_by_user.keys()):
        f = compute_features(trades_by_user[user_id], calendar)
        f["user_id"] = user_id
        features_by_user[user_id] = f
        dump_json(features_dir / f"{user_id}.json", f)
        print(f"  [features] {user_id}: {f['total_trades']} trades")

    sm.advance(Stage.FEATURES_COMPUTED)
    if _stop_after(Stage.FEATURES_COMPUTED, stop_stage):
        return

    # ------------------------------------------------- PATTERNS_CLASSIFIED
    print("[run] Classifying patterns (Stage 1 LLM)...")
    patterns_list = classify_all_users(trades_by_user, features_by_user, mock=mock)
    dump_json(ROOT / "patterns.json", patterns_list)
    patterns_by_user = {p["user_id"]: p["patterns"] for p in patterns_list}

    sm.advance(Stage.PATTERNS_CLASSIFIED)
    if _stop_after(Stage.PATTERNS_CLASSIFIED, stop_stage):
        return

    # -------------------------------------------------- RISK_SCORES_COMPUTED
    print("[run] Computing risk scores (deterministic)...")
    risk_records = []
    for user_id in sorted(features_by_user.keys()):
        rec = score_user(
            user_id,
            features_by_user[user_id],
            patterns_by_user.get(user_id, ["normal"]),
        )
        risk_records.append(rec)
        print(f"  [risk] {user_id}: {rec['risk_score']:.1f} " f"({rec['risk_tier']})")

    dump_json(ROOT / "risk_scores.json", risk_records)
    sm.advance(Stage.RISK_SCORES_COMPUTED)
    if _stop_after(Stage.RISK_SCORES_COMPUTED, stop_stage):
        return

    # ----------------------------------------------- INTERVENTIONS_GENERATED
    print("[run] Generating intervention plan (Stage 2 LLM)...")
    interventions = generate_interventions(
        features_by_user, patterns_by_user, risk_records, mock=mock
    )
    dump_json(ROOT / "interventions.json", interventions)
    sm.advance(Stage.INTERVENTIONS_GENERATED)
    if _stop_after(Stage.INTERVENTIONS_GENERATED, stop_stage):
        return

    # ---------------------------------------------- SHOULD-ATTEMPT: audit
    print("[run] Running false-positive audit...")
    audit_result = run_audit(trades_by_user, patterns_by_user)
    dump_json(ROOT / "false_positive_audit.json", audit_result)

    # ---------------------------------------------- SHOULD-ATTEMPT: cohort
    print("[run] Computing cohort insights...")
    cohort_insights = compute_cohort_insights(
        features_by_user, patterns_by_user, risk_records
    )
    dump_json(ROOT / "cohort_insights.json", cohort_insights)

    # ---------------------------------------------- STRETCH: copy
    print("[run] Generating responsible-trading copy (stretch)...")
    generate_and_save_copy(ROOT / "messages", mock=mock)

    # ---------------------------------------------- STRETCH: regulatory
    print("[run] Generating regulatory mapping (stretch)...")
    reg_mapping = generate_regulatory_mapping(mock=mock)
    dump_json(ROOT / "regulatory_mapping.json", reg_mapping)

    # ----------------------------------------------- VALIDATION_COMPLETE
    sm.advance(Stage.VALIDATION_COMPLETE)

    # ----------------------------------------------- RESULTS_FINALISED
    sm.advance(Stage.RESULTS_FINALISED)

    n_users = len(features_by_user)
    n_trades = len(all_trades)
    print(f"\n[run] Done. {n_users} users, {n_trades} trades. " f"Mock LLM: {mock}")


if __name__ == "__main__":
    main()

from __future__ import annotations

from typing import Any

from .llm import plan_interventions_llm
from .vocab import INTERVENTIONS


def _build_profiles(
    features_by_user: dict[str, dict[str, Any]],
    patterns_by_user: dict[str, list[str]],
    risk_scores: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Assemble compact profiles sorted by risk_score descending."""
    score_map = {r["user_id"]: r for r in risk_scores}
    profiles: list[dict[str, Any]] = []
    for user_id in sorted(features_by_user.keys()):
        score_rec = score_map.get(user_id, {})
        f = features_by_user[user_id]
        profiles.append(
            {
                "user_id": user_id,
                "risk_score": score_rec.get("risk_score", 0.0),
                "risk_tier": score_rec.get("risk_tier", "low"),
                "patterns": patterns_by_user.get(user_id, ["normal"]),
                "features_summary": {
                    "average_stake": f.get("average_stake"),
                    "stake_escalation_ratio_after_losses": f.get(
                        "stake_escalation_ratio_after_losses"
                    ),
                    "trades_per_minute": f.get("trades_per_minute"),
                    "pct_news_adjacent": f.get(
                        "pct_trades_within_5min_of_high_impact_news"
                    ),
                    "win_rate": f.get("win_rate"),
                    "longest_losing_streak": f.get("longest_losing_streak"),
                    "total_net_pnl_usd": f.get("total_net_pnl_usd"),
                },
            }
        )
    profiles.sort(key=lambda p: p["risk_score"], reverse=True)
    return profiles


def _validate_interventions(
    interventions: list[dict[str, Any]],
    valid_user_ids: set[str],
    patterns_by_user: dict[str, list[str]],
    risk_scores: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Cross-validate and fix interventions:
    - Ensure user_id is valid.
    - Ensure intervention_type is in the controlled vocab.
    - Ensure risk_tier matches the deterministic score.
    - Ensure triggering_patterns ⊆ patterns for that user.
    """
    tier_map = {r["user_id"]: r["risk_tier"] for r in risk_scores}
    score_map = {r["user_id"]: r["risk_score"] for r in risk_scores}
    validated: list[dict[str, Any]] = []
    for rec in interventions:
        uid = rec.get("user_id")
        if uid not in valid_user_ids:
            continue  # drop invalid

        itype = rec.get("intervention_type", "")
        if itype not in INTERVENTIONS:
            rec["intervention_type"] = _tier_default(tier_map.get(uid, "low"))

        # Override risk_tier with deterministic value
        rec["risk_tier"] = tier_map.get(uid, rec.get("risk_tier", "low"))

        # Filter triggering_patterns to only known patterns for that user
        user_patterns = set(patterns_by_user.get(uid, []))
        trig = [p for p in rec.get("triggering_patterns", []) if p in user_patterns]
        rec["triggering_patterns"] = trig if trig else list(user_patterns)[:1]

        validated.append(rec)

    # Ensure every user has an intervention
    covered = {r["user_id"] for r in validated}
    for uid in sorted(valid_user_ids - covered):
        tier = tier_map.get(uid, "low")
        validated.append(
            {
                "user_id": uid,
                "risk_tier": tier,
                "intervention_type": _tier_default(tier),
                "triggering_patterns": patterns_by_user.get(uid, ["normal"])[:1],
                "evidence_summary": "Auto-generated: missing from LLM output.",
                "recommended_action": f"Apply {_tier_default(tier)}.",
            }
        )

    validated.sort(key=lambda r: (-score_map.get(r["user_id"], 0.0), r["user_id"]))
    return validated


def _tier_default(tier: str) -> str:
    return {
        "critical": "human_outreach",
        "high": "cooling_off_period",
        "medium": "deposit_limit_prompt",
        "low": "soft_nudge",
    }.get(tier, "soft_nudge")


def generate_interventions(
    features_by_user: dict[str, dict[str, Any]],
    patterns_by_user: dict[str, list[str]],
    risk_scores: list[dict[str, Any]],
    mock: bool = False,
) -> list[dict[str, Any]]:
    """
    Stage 2: one combined LLM call, then validate and sort.
    """
    profiles = _build_profiles(features_by_user, patterns_by_user, risk_scores)
    raw = plan_interventions_llm(profiles, mock=mock)
    valid_ids = set(features_by_user.keys())
    return _validate_interventions(raw, valid_ids, patterns_by_user, risk_scores)

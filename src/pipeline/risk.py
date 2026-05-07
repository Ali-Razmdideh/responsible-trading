from __future__ import annotations

from typing import Any

FORMULA_VERSION = "v1"

# Each numeric weight entry has: threshold key + "cap".
# Pattern scores map pattern name → points.
WEIGHTS: dict[str, Any] = {
    "pattern_scores": {
        "martingale": 25,
        "revenge_trading": 20,
        "position_doubling": 20,
        "news_chasing": 15,
        "anti_martingale": 10,
        "scalping": 5,
        "normal": 0,
        "insufficient_evidence": 0,
    },
    "stake_escalation_after_losses": {"per_unit_above_1": 10, "cap": 25},
    "trades_per_minute": {"per_unit_above_0.5": 8, "cap": 15},
    "pct_news_adjacent": {"per_10_pct": 5, "cap": 15},
    "longest_losing_streak": {"per_loss_above_3": 3, "cap": 15},
    "recent_net_loss": {"per_100_usd_loss": 2, "cap": 10},
}


def tier_for(score: float) -> str:
    if score >= 75:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


def score_user(
    user_id: str,
    features: dict[str, Any],
    patterns: list[str],
) -> dict[str, Any]:
    """Pure, deterministic risk scoring. Returns full record with audit trail."""
    factors: list[dict[str, Any]] = []
    total = 0.0

    pat_scores: dict[str, int] = WEIGHTS["pattern_scores"]
    for pat in sorted(set(patterns)):
        pts = pat_scores.get(pat, 0)
        factors.append(
            {
                "factor": pat,
                "value": pat,
                "weight": pts,
                "contribution": float(pts),
            }
        )
        total += pts

    # Stake escalation: score excess above 1.0
    escalation = float(features.get("stake_escalation_ratio_after_losses", 0.0))
    w = WEIGHTS["stake_escalation_after_losses"]
    contrib = min(max(escalation - 1.0, 0.0) * w["per_unit_above_1"], w["cap"])
    factors.append(
        {
            "factor": "stake_escalation_after_losses",
            "value": round(escalation, 6),
            "weight": w["per_unit_above_1"],
            "contribution": round(contrib, 6),
        }
    )
    total += contrib

    # Trades per minute: score excess above 0.5
    tpm = float(features.get("trades_per_minute", 0.0))
    w = WEIGHTS["trades_per_minute"]
    contrib = min(max(tpm - 0.5, 0.0) * w["per_unit_above_0.5"], w["cap"])
    factors.append(
        {
            "factor": "trades_per_minute",
            "value": round(tpm, 6),
            "weight": w["per_unit_above_0.5"],
            "contribution": round(contrib, 6),
        }
    )
    total += contrib

    # News adjacency: per 10 percentage points
    pct_news = float(features.get("pct_trades_within_5min_of_high_impact_news", 0.0))
    w = WEIGHTS["pct_news_adjacent"]
    contrib = min((pct_news * 100 / 10) * w["per_10_pct"], w["cap"])
    factors.append(
        {
            "factor": "pct_news_adjacent",
            "value": round(pct_news, 6),
            "weight": w["per_10_pct"],
            "contribution": round(contrib, 6),
        }
    )
    total += contrib

    # Longest losing streak: per loss above 3
    streak = int(features.get("longest_losing_streak", 0))
    w = WEIGHTS["longest_losing_streak"]
    contrib = min(max(streak - 3, 0) * w["per_loss_above_3"], w["cap"])
    factors.append(
        {
            "factor": "longest_losing_streak",
            "value": streak,
            "weight": w["per_loss_above_3"],
            "contribution": round(contrib, 6),
        }
    )
    total += contrib

    # Recent net loss (positive contribution only when PnL is negative)
    net_pnl = float(features.get("total_net_pnl_usd", 0.0))
    w = WEIGHTS["recent_net_loss"]
    contrib = min((max(-net_pnl, 0.0) / 100) * w["per_100_usd_loss"], w["cap"])
    factors.append(
        {
            "factor": "recent_net_loss",
            "value": round(net_pnl, 6),
            "weight": w["per_100_usd_loss"],
            "contribution": round(contrib, 6),
        }
    )
    total += contrib

    risk_score = round(max(0.0, min(100.0, total)), 6)

    return {
        "user_id": user_id,
        "risk_score": risk_score,
        "risk_tier": tier_for(risk_score),
        "contributing_factors": factors,
        "formula_version": FORMULA_VERSION,
    }

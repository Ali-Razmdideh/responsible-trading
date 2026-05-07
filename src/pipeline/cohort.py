from __future__ import annotations

from typing import Any


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def compute_cohort_insights(
    features_by_user: dict[str, dict[str, Any]],
    patterns_by_user: dict[str, list[str]],
    risk_scores: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Pure, deterministic cohort insight computation. No LLM involvement."""
    score_map = {r["user_id"]: r["risk_score"] for r in risk_scores}
    insights: list[dict[str, Any]] = []

    # Insight 1: loss rate for news-adjacent vs non-news-adjacent users
    news_loss_rates = []
    other_loss_rates = []
    for uid, f in features_by_user.items():
        pct_news = f.get("pct_trades_within_5min_of_high_impact_news", 0.0)
        win_rate = f.get("win_rate", 0.0)
        loss_rate = round(1.0 - win_rate, 6)
        if pct_news > 0.2:
            news_loss_rates.append(loss_rate)
        else:
            other_loss_rates.append(loss_rate)

    insights.append(
        {
            "metric": "loss_rate",
            "cohort": "users with >20% trades near high-impact news",
            "comparison_group": "users with ≤20% trades near high-impact news",
            "values": {
                "cohort": _mean(news_loss_rates),
                "comparison": _mean(other_loss_rates),
            },
            "conclusion": (
                "Users trading near high-impact news had a "
                + (
                    "higher"
                    if _mean(news_loss_rates) > _mean(other_loss_rates)
                    else "lower or equal"
                )
                + " loss rate than other users."
            ),
        }
    )

    # Insight 2: revenge interval for high-escalation vs low-escalation users
    high_esc_revenge = []
    low_esc_revenge = []
    for uid, f in features_by_user.items():
        escalation = f.get("stake_escalation_ratio_after_losses", 0.0)
        revenge = f.get("revenge_interval_seconds_avg", 0.0)
        if escalation > 1.5:
            high_esc_revenge.append(revenge)
        else:
            low_esc_revenge.append(revenge)

    insights.append(
        {
            "metric": "revenge_interval_seconds_avg",
            "cohort": "users with stake escalation ratio > 1.5",
            "comparison_group": "users with stake escalation ratio ≤ 1.5",
            "values": {
                "cohort": _mean(high_esc_revenge),
                "comparison": _mean(low_esc_revenge),
            },
            "conclusion": (
                "Users with high stake escalation after losses had "
                + (
                    "shorter"
                    if _mean(high_esc_revenge) < _mean(low_esc_revenge)
                    else "longer or equal"
                )
                + " revenge intervals on average."
            ),
        }
    )

    # Insight 3: mean risk score for martingale-classified vs rest
    martingale_scores = []
    other_scores = []
    for uid, pats in patterns_by_user.items():
        score = score_map.get(uid, 0.0)
        if "martingale" in pats:
            martingale_scores.append(score)
        else:
            other_scores.append(score)

    insights.append(
        {
            "metric": "mean_risk_score",
            "cohort": "martingale-classified users",
            "comparison_group": "non-martingale users",
            "values": {
                "cohort": _mean(martingale_scores),
                "comparison": _mean(other_scores),
            },
            "conclusion": (
                "Martingale-classified users had a mean risk score of "
                f"{_mean(martingale_scores):.1f} vs "
                f"{_mean(other_scores):.1f} for others."
            ),
        }
    )

    return insights

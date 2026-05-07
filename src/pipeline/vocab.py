from __future__ import annotations

PATTERNS: frozenset[str] = frozenset(
    {
        "martingale",
        "anti_martingale",
        "revenge_trading",
        "news_chasing",
        "scalping",
        "position_doubling",
        "normal",
        "insufficient_evidence",
    }
)

INTERVENTIONS: frozenset[str] = frozenset(
    {
        "soft_nudge",
        "deposit_limit_prompt",
        "cooling_off_period",
        "human_outreach",
    }
)

TIERS: tuple[str, ...] = ("low", "medium", "high", "critical")

CONFIDENCE_LEVELS: tuple[str, ...] = ("low", "medium", "high")

PATTERN_DEFINITIONS: dict[str, str] = {
    "martingale": (
        "Doubling (or multiplying) stake after each loss to recover losses. "
        "Key signal: stake_escalation_ratio_after_losses > 1.8 "
        "and longest_losing_streak >= 3."
    ),
    "anti_martingale": (
        "Increasing stake after wins, reducing after losses. "
        "Key signal: stake increases following wins, decreases following losses."
    ),
    "revenge_trading": (
        "Placing trades very quickly after a loss, driven by emotion. "
        "Key signal: revenge_interval_seconds_avg < 30 and win_rate < 0.45."
    ),
    "news_chasing": (
        "Clustering trades immediately around high-impact news events. "
        "Key signal: pct_trades_within_5min_of_high_impact_news > 0.30."
    ),
    "scalping": (
        "Very high frequency of short-duration trades. "
        "Key signal: trades_per_minute > 2.0."
    ),
    "position_doubling": (
        "Doubling stake on a single position without a full martingale sequence — "
        "one or two large doublings rather than a systematic escalation chain. "
        "Key signal: isolated stake doublings after losses, "
        "stake_escalation_ratio_after_losses between 1.8 and 2.5."
    ),
    "normal": (
        "No strong behavioural risk pattern detected. "
        "Stake and timing are consistent and not significantly influenced "
        "by losses or news events."
    ),
    "insufficient_evidence": (
        "Too few trades or contradictory signals to assign a reliable classification."
    ),
}

BANNED_COPY_PHRASES: list[str] = [
    "you should",
    "stop losing",
    "you are losing",
    "guarantee",
    "promise",
    "you must",
    "shameful",
    "irresponsible",
    "reckless",
    "foolish",
    "you need to stop",
    "financial advice",
]

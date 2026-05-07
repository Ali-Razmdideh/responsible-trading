from __future__ import annotations

from typing import Any

_MIN_QUALIFYING_PAIRS = 3
_ESCALATION_THRESHOLD = 1.5


def verify_martingale(
    user_id: str,
    trades: list[dict[str, Any]],
    patterns: list[str],
) -> dict[str, Any]:
    """
    Verify in deterministic code that stake escalation follows losses.

    Returns a record with verified=True if ≥3 qualifying post-loss
    escalation pairs exist (stake_n >= 1.5 * stake_{n-1} after a loss).
    Returns verified=False with an explanatory note otherwise.
    """
    if "martingale" not in patterns and "position_doubling" not in patterns:
        return {
            "user_id": user_id,
            "pattern": None,
            "verified": False,
            "supporting_trade_sequence": [],
            "calculation": "",
            "eligible": False,
            "note": (
                f"User {user_id} is not classified as martingale or "
                "position_doubling — audit skipped."
            ),
        }

    sorted_trades = sorted(trades, key=lambda t: t["open_ts"])
    qualifying_pairs: list[tuple[str, str, float, float]] = []

    for i in range(1, len(sorted_trades)):
        prev = sorted_trades[i - 1]
        curr = sorted_trades[i]
        if prev.get("result") == "loss" and prev["stake_usd"] > 0:
            ratio = curr["stake_usd"] / prev["stake_usd"]
            if ratio >= _ESCALATION_THRESHOLD:
                qualifying_pairs.append(
                    (
                        prev["trade_id"],
                        curr["trade_id"],
                        prev["stake_usd"],
                        curr["stake_usd"],
                    )
                )

    verified = len(qualifying_pairs) >= _MIN_QUALIFYING_PAIRS
    supporting_ids: list[str] = []
    for prev_id, curr_id, _, _ in qualifying_pairs:
        if prev_id not in supporting_ids:
            supporting_ids.append(prev_id)
        if curr_id not in supporting_ids:
            supporting_ids.append(curr_id)

    calc_parts = [
        f"{prev_id}(stake={ps}) → {curr_id}(stake={cs})" f" ratio={round(cs/ps, 3)}"
        for prev_id, curr_id, ps, cs in qualifying_pairs
    ]
    calculation = (
        f"Found {len(qualifying_pairs)} post-loss escalation pair(s) "
        f"with ratio ≥ {_ESCALATION_THRESHOLD}: " + "; ".join(calc_parts)
        if qualifying_pairs
        else f"No qualifying post-loss escalation pairs found "
        f"(threshold: ratio ≥ {_ESCALATION_THRESHOLD})."
    )

    pattern_used = "martingale" if "martingale" in patterns else "position_doubling"

    return {
        "user_id": user_id,
        "pattern": pattern_used,
        "verified": verified,
        "supporting_trade_sequence": supporting_ids,
        "calculation": calculation,
    }


def run_audit(
    all_trades_by_user: dict[str, list[dict[str, Any]]],
    patterns_by_user: dict[str, list[str]],
) -> dict[str, Any]:
    """
    Run the false-positive audit across all users.

    Picks the first user (alphabetically) classified as martingale
    or position_doubling. If none, returns a not-eligible record.
    """
    eligible = sorted(
        uid
        for uid, pats in patterns_by_user.items()
        if "martingale" in pats or "position_doubling" in pats
    )

    if not eligible:
        return {
            "user_id": None,
            "pattern": None,
            "verified": False,
            "supporting_trade_sequence": [],
            "calculation": "",
            "note": "No user classified as martingale or position_doubling.",
        }

    user_id = eligible[0]
    return verify_martingale(
        user_id,
        all_trades_by_user[user_id],
        patterns_by_user[user_id],
    )

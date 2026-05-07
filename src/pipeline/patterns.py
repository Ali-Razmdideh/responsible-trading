from __future__ import annotations

from typing import Any

from .llm import LLMValidationError, classify_patterns_llm
from .vocab import CONFIDENCE_LEVELS, PATTERNS


def _validate(result: dict[str, Any], user_id: str, trade_ids: set[str]) -> list[str]:
    """Return a list of validation errors (empty = valid)."""
    errors = []
    if result.get("user_id") != user_id:
        errors.append(f"user_id mismatch: got {result.get('user_id')}")

    for pat in result.get("patterns", []):
        if pat not in PATTERNS:
            errors.append(f"unknown pattern: {pat}")

    if result.get("confidence") not in CONFIDENCE_LEVELS:
        errors.append(f"invalid confidence: {result.get('confidence')}")

    for ev in result.get("evidence", []):
        for tid in ev.get("trade_ids", []):
            if tid and tid not in trade_ids:
                errors.append(f"unknown trade_id in evidence: {tid}")

    return errors


def _fallback(user_id: str, reason: str) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "patterns": ["insufficient_evidence"],
        "evidence": [
            {
                "pattern": "insufficient_evidence",
                "triggering_features": [],
                "trade_ids": [],
                "explanation": reason,
            }
        ],
        "confidence": "low",
    }


def classify_user(
    user_id: str,
    features: dict[str, Any],
    trades: list[dict[str, Any]],
    mock: bool = False,
) -> dict[str, Any]:
    """
    Classify one user. Makes one LLM call; retries once on schema failure.
    Falls back to insufficient_evidence on second failure.
    """
    trade_ids = {t["trade_id"] for t in trades}
    last_30 = sorted(trades, key=lambda t: t["open_ts"])[-30:]

    try:
        result = classify_patterns_llm(user_id, features, last_30, mock=mock)
        errors = _validate(result, user_id, trade_ids)
    except LLMValidationError as e:
        result, errors = None, [str(e)]

    if errors:
        try:
            retry_result = classify_patterns_llm(
                user_id, features, last_30, mock=mock
            )
            retry_errors = _validate(retry_result, user_id, trade_ids)
        except LLMValidationError as e:
            return _fallback(
                user_id,
                f"LLM parse failure after retry: {e}",
            )
        if retry_errors:
            return _fallback(
                user_id,
                f"Schema validation failed after retry: {'; '.join(retry_errors)}",
            )
        return retry_result

    return result


def classify_all_users(
    trades_by_user: dict[str, list[dict[str, Any]]],
    features_by_user: dict[str, dict[str, Any]],
    mock: bool = False,
) -> list[dict[str, Any]]:
    """Classify all users in sorted order. Returns list for patterns.json."""
    results: list[dict[str, Any]] = []
    for user_id in sorted(trades_by_user.keys()):
        features = features_by_user[user_id]
        trades = trades_by_user[user_id]
        result = classify_user(user_id, features, trades, mock=mock)
        results.append(result)
        print(f"[patterns] {user_id}: {result['patterns']}")
    return results

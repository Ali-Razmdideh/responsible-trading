from __future__ import annotations

import datetime
import hashlib
import json
import os
from typing import Any

from .io import ROOT, append_jsonl, dump_json

LLM_RAW_DIR = ROOT / "artifacts" / "llm_raw"
LLM_LOG_PATH = ROOT / "llm_calls.jsonl"

MODEL = os.environ.get("PIPELINE_MODEL", "gpt-4o-mini")
PROVIDER = "openai"


class LLMValidationError(Exception):
    """Raised when an LLM response cannot be parsed or fails schema/vocab checks."""


_client = None


def _get_client() -> Any:
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI()
    return _client


# ---------------------------------------------------------------------------
# Mock implementations (deterministic, no API calls)
# ---------------------------------------------------------------------------


def _martingale_trade_ids(trades: list[dict[str, Any]]) -> list[str]:
    """Return ordered trade_ids forming post-loss stake-escalation pairs."""
    ordered = sorted(trades, key=lambda t: t["open_ts"])
    ids: list[str] = []
    for prev, curr in zip(ordered, ordered[1:]):
        if (
            prev.get("result") == "loss"
            and prev.get("stake_usd", 0) > 0
            and curr.get("stake_usd", 0) >= prev.get("stake_usd", 0) * 1.5
        ):
            if not ids or ids[-1] != prev["trade_id"]:
                ids.append(prev["trade_id"])
            ids.append(curr["trade_id"])
    return ids


def _news_chasing_trade_ids(trades: list[dict[str, Any]]) -> list[str]:
    """Return trade_ids flagged as adjacent to high-impact news."""
    ids = [
        t["trade_id"]
        for t in sorted(trades, key=lambda t: t["open_ts"])
        if t.get("near_high_impact_news") is True
    ]
    return ids[:10]


def _scalping_trade_ids(trades: list[dict[str, Any]]) -> list[str]:
    """Return trade_ids with very short open-to-close duration."""
    ordered = sorted(trades, key=lambda t: t["open_ts"])
    return [t["trade_id"] for t in ordered[-10:]]


def _revenge_trade_ids(trades: list[dict[str, Any]]) -> list[str]:
    """Trades that immediately follow a losing trade."""
    ordered = sorted(trades, key=lambda t: t["open_ts"])
    ids: list[str] = []
    for prev, curr in zip(ordered, ordered[1:]):
        if prev.get("result") == "loss":
            ids.append(curr["trade_id"])
        if len(ids) >= 10:
            break
    return ids


def _mock_classify_patterns(
    user_id: str,
    features: dict[str, Any],
    trades: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    escalation = features.get("stake_escalation_ratio_after_losses", 0.0)
    streak = features.get("longest_losing_streak", 0)
    tpm = features.get("trades_per_minute", 0.0)
    pct_news = features.get("pct_trades_within_5min_of_high_impact_news", 0.0)
    revenge = features.get("revenge_interval_seconds_avg", 999.0)
    total_trades = features.get("total_trades", 0)
    trades = trades or []

    patterns: list[str] = []
    evidence: list[dict[str, Any]] = []

    if escalation >= 1.8 and streak >= 3:
        patterns.append("martingale")
        evidence.append(
            {
                "pattern": "martingale",
                "triggering_features": [
                    "stake_escalation_ratio_after_losses",
                    "longest_losing_streak",
                ],
                "trade_ids": _martingale_trade_ids(trades),
                "explanation": (
                    f"Escalation ratio {escalation:.2f} with streak "
                    f"{streak} indicates systematic doubling after losses."
                ),
            }
        )
    if tpm > 2.0:
        patterns.append("scalping")
        evidence.append(
            {
                "pattern": "scalping",
                "triggering_features": ["trades_per_minute"],
                "trade_ids": _scalping_trade_ids(trades),
                "explanation": (f"High trade frequency: {tpm:.2f} trades/min."),
            }
        )
    if pct_news > 0.30:
        patterns.append("news_chasing")
        evidence.append(
            {
                "pattern": "news_chasing",
                "triggering_features": ["pct_trades_within_5min_of_high_impact_news"],
                "trade_ids": _news_chasing_trade_ids(trades),
                "explanation": (
                    f"{pct_news*100:.0f}% of trades near high-impact " "news events."
                ),
            }
        )
    if 0.0 < revenge < 30:
        patterns.append("revenge_trading")
        evidence.append(
            {
                "pattern": "revenge_trading",
                "triggering_features": ["revenge_interval_seconds_avg"],
                "trade_ids": _revenge_trade_ids(trades),
                "explanation": (
                    f"Average post-loss interval: {revenge:.1f}s — " "rapid re-entry."
                ),
            }
        )

    if not patterns:
        if total_trades < 5:
            patterns.append("insufficient_evidence")
            evidence.append(
                {
                    "pattern": "insufficient_evidence",
                    "triggering_features": ["total_trades"],
                    "trade_ids": [],
                    "explanation": (
                        f"Only {total_trades} trades — too few to classify."
                    ),
                }
            )
        else:
            patterns.append("normal")
            evidence.append(
                {
                    "pattern": "normal",
                    "triggering_features": [],
                    "trade_ids": [],
                    "explanation": "No strong risk pattern detected.",
                }
            )

    confidence = (
        "high"
        if patterns and patterns[0] not in ("normal", "insufficient_evidence")
        else "medium"
    )
    return {
        "user_id": user_id,
        "patterns": patterns,
        "evidence": evidence,
        "confidence": confidence,
    }


def _mock_interventions(
    profiles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    tier_map = {
        "critical": "human_outreach",
        "high": "cooling_off_period",
        "medium": "deposit_limit_prompt",
        "low": "soft_nudge",
    }
    results: list[dict[str, Any]] = []
    for p in profiles:
        tier = p["risk_tier"]
        patterns = p.get("patterns", ["normal"])
        results.append(
            {
                "user_id": p["user_id"],
                "risk_tier": tier,
                "intervention_type": tier_map[tier],
                "triggering_patterns": patterns[:2],
                "evidence_summary": (
                    f"Risk score {p['risk_score']:.1f} ({tier}). "
                    f"Patterns: {', '.join(patterns)}."
                ),
                "recommended_action": (
                    f"Apply {tier_map[tier]} based on "
                    f"{patterns[0]} pattern detection."
                ),
            }
        )
    return results


def _mock_copy(intervention_types: list[str]) -> dict[str, str]:
    templates = {
        "soft_nudge": (
            "We noticed your recent trading activity. "
            "Taking a moment to review your approach can help you trade "
            "more mindfully. Our support team is here if you need guidance."
        ),
        "deposit_limit_prompt": (
            "Setting a deposit limit can be a helpful way to stay within "
            "your comfort zone. You can update this at any time in your "
            "account settings."
        ),
        "cooling_off_period": (
            "A short break from trading can offer valuable perspective. "
            "We have options to help you step back temporarily — "
            "our team is available to help you find what works for you."
        ),
        "human_outreach": (
            "One of our player protection specialists would like to connect "
            "with you for a confidential, supportive conversation. "
            "We are here to help."
        ),
    }
    return {itype: templates.get(itype, "") for itype in intervention_types}


def _mock_regulatory() -> list[dict[str, Any]]:
    return [
        {
            "intervention_type": "soft_nudge",
            "regulator_or_framework": "UKGC",
            "obligation_name": "Consumer Interaction",
            "explanation": (
                "UKGC requires operators to use behavioural data to "
                "identify and interact with at-risk players."
            ),
            "citation": "UKGC Social Responsibility Code 3.4.3",
        },
        {
            "intervention_type": "deposit_limit_prompt",
            "regulator_or_framework": "MGA",
            "obligation_name": "Responsible Gaming Tools",
            "explanation": (
                "MGA operators must offer and promote deposit-limit tools "
                "to players showing signs of problem gambling."
            ),
            "citation": "MGA Player Protection Directive 2018, Art. 12",
        },
        {
            "intervention_type": "cooling_off_period",
            "regulator_or_framework": "GamStop / UKGC",
            "obligation_name": "Self-Exclusion and Time-Out",
            "explanation": (
                "Operators must provide time-out and cooling-off mechanisms "
                "and must not market to players during these periods."
            ),
            "citation": "UKGC Social Responsibility Code 3.5.1",
        },
        {
            "intervention_type": "human_outreach",
            "regulator_or_framework": "UKGC",
            "obligation_name": "Customer Interaction — High Risk",
            "explanation": (
                "High-risk players must receive a direct interaction from "
                "a trained responsible-gambling specialist."
            ),
            "citation": "UKGC Customer Interaction Guidance 2019",
        },
    ]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _hash_prompt(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _log_call(
    stage: str,
    user_id: str | None,
    prompt_hash: str,
    input_artifacts: list[str],
    output_artifact: str,
    mock: bool = False,
) -> None:
    append_jsonl(
        LLM_LOG_PATH,
        {
            "stage": stage,
            "user_id": user_id,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "provider": "mock" if mock else PROVIDER,
            "model": "mock" if mock else MODEL,
            "prompt_hash": prompt_hash,
            "input_artifacts": input_artifacts,
            "output_artifact": output_artifact,
        },
    )


def _save_raw(stage: str, user_id: str | None, data: dict[str, Any]) -> str:
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    uid_part = user_id or "batch"
    filename = f"{stage}_{uid_part}_{ts}.json"
    path = LLM_RAW_DIR / filename
    LLM_RAW_DIR.mkdir(parents=True, exist_ok=True)
    dump_json(path, data)
    return str(path.relative_to(ROOT))


def _call_real_llm(prompt: str, system: str = "") -> str:
    client = _get_client()
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_patterns_llm(
    user_id: str,
    features: dict[str, Any],
    last_30_trades: list[dict[str, Any]],
    mock: bool = False,
) -> dict[str, Any]:
    from .prompts import build_pattern_prompt

    prompt = build_pattern_prompt(user_id, features, last_30_trades)
    prompt_hash = _hash_prompt(prompt)

    if mock:
        result: dict[str, Any] = _mock_classify_patterns(
            user_id, features, last_30_trades
        )
    else:
        raw_text = _call_real_llm(
            prompt,
            system=(
                "You are a responsible-trading behaviour analyst. "
                "Respond with valid JSON only."
            ),
        )
        try:
            result = json.loads(raw_text)
        except (json.JSONDecodeError, TypeError) as e:
            raise LLMValidationError(
                f"Pattern LLM returned invalid JSON for {user_id}: {e}"
            ) from e
        if not isinstance(result, dict):
            raise LLMValidationError(
                f"Pattern LLM did not return a JSON object for {user_id}"
            )

    raw_path = _save_raw(
        "patterns", user_id, {"prompt_hash": prompt_hash, "result": result}
    )
    _log_call(
        stage="patterns",
        user_id=user_id,
        prompt_hash=prompt_hash,
        input_artifacts=[f"features/{user_id}.json"],
        output_artifact=raw_path,
        mock=mock,
    )
    return result


def plan_interventions_llm(
    profiles: list[dict[str, Any]],
    mock: bool = False,
) -> list[dict[str, Any]]:
    from .prompts import build_interventions_prompt

    prompt = build_interventions_prompt(profiles)
    prompt_hash = _hash_prompt(prompt)

    if mock:
        result: list[dict[str, Any]] = _mock_interventions(profiles)
    else:
        raw_text = _call_real_llm(
            prompt,
            system=(
                "You are a responsible-trading intervention specialist. "
                'Respond with JSON: {"interventions": [...]}'
            ),
        )
        try:
            parsed = json.loads(raw_text)
        except (json.JSONDecodeError, TypeError) as e:
            raise LLMValidationError(
                f"Intervention LLM returned invalid JSON: {e}"
            ) from e
        if isinstance(parsed, list):
            result = parsed
        elif isinstance(parsed, dict) and isinstance(
            parsed.get("interventions"), list
        ):
            result = parsed["interventions"]
        else:
            raise LLMValidationError(
                "Intervention LLM did not return a list or "
                "{interventions: [...]} object"
            )

    raw_path = _save_raw(
        "interventions",
        None,
        {"prompt_hash": prompt_hash, "result": result},
    )
    _log_call(
        stage="interventions",
        user_id=None,
        prompt_hash=prompt_hash,
        input_artifacts=["patterns.json", "risk_scores.json"],
        output_artifact=raw_path,
        mock=mock,
    )
    return result


def generate_copy_llm(
    intervention_types: list[str],
    mock: bool = False,
) -> dict[str, str]:
    from .prompts import build_copy_prompt

    prompt = build_copy_prompt(intervention_types)
    prompt_hash = _hash_prompt(prompt)

    if mock:
        result: dict[str, str] = _mock_copy(intervention_types)
    else:
        raw_text = _call_real_llm(
            prompt,
            system=(
                "You are a responsible-trading copywriter. "
                "Respond with a valid JSON object."
            ),
        )
        result = json.loads(raw_text)

    raw_path = _save_raw("copy", None, {"prompt_hash": prompt_hash, "result": result})
    _log_call(
        stage="copy",
        user_id=None,
        prompt_hash=prompt_hash,
        input_artifacts=["interventions.json"],
        output_artifact=raw_path,
        mock=mock,
    )
    return result


def generate_regulatory_llm(
    intervention_types: list[str],
    mock: bool = False,
) -> list[dict[str, Any]]:
    from .prompts import build_regulatory_prompt

    prompt = build_regulatory_prompt(intervention_types)
    prompt_hash = _hash_prompt(prompt)

    if mock:
        result: list[dict[str, Any]] = _mock_regulatory()
    else:
        raw_text = _call_real_llm(
            prompt,
            system=(
                "You are a gambling regulatory compliance expert. "
                'Respond with JSON: {"mappings": [...]}'
            ),
        )
        parsed = json.loads(raw_text)
        result = parsed if isinstance(parsed, list) else parsed.get("mappings", parsed)

    raw_path = _save_raw(
        "regulatory",
        None,
        {"prompt_hash": prompt_hash, "result": result},
    )
    _log_call(
        stage="regulatory",
        user_id=None,
        prompt_hash=prompt_hash,
        input_artifacts=["interventions.json"],
        output_artifact=raw_path,
        mock=mock,
    )
    return result

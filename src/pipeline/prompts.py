from __future__ import annotations

import json
from typing import Any

from .vocab import INTERVENTIONS, PATTERN_DEFINITIONS, PATTERNS


def build_pattern_prompt(
    user_id: str,
    features: dict[str, Any],
    last_30_trades: list[dict[str, Any]],
) -> str:
    compact_trades = [
        {
            "id": t["trade_id"],
            "open": t["open_ts"],
            "stake": t["stake_usd"],
            "payout": t["payout_usd"],
            "result": t["result"],
        }
        for t in last_30_trades[-30:]
    ]

    feature_display = {
        k: v for k, v in features.items() if not k.startswith("session_durations")
    }

    vocab_block = "\n".join(
        f"- {name}: {defn}" for name, defn in PATTERN_DEFINITIONS.items()
    )

    return f"""You are analysing anonymised trading behaviour for user {user_id}.

## Computed feature vector (deterministic — do not modify these values)
{json.dumps(feature_display, indent=2)}

## Last {len(compact_trades)} trades (compact format)
{json.dumps(compact_trades, indent=2)}

## Pattern vocabulary (you must only use labels from this list)
{json.dumps(sorted(PATTERNS), indent=2)}

## Pattern definitions
{vocab_block}

## Task
Classify this user's trading behaviour. Assign one or more labels from the vocabulary.
Cite specific features and trade IDs as evidence.

Respond ONLY with a JSON object matching this schema exactly:
{{
  "user_id": "{user_id}",
  "patterns": ["<label>"],
  "evidence": [
    {{
      "pattern": "<label>",
      "triggering_features": ["<feature_name>"],
      "trade_ids": ["<trade_id>"],
      "explanation": "<concise explanation citing the feature values>"
    }}
  ],
  "confidence": "low | medium | high"
}}"""


def build_interventions_prompt(profiles: list[dict[str, Any]]) -> str:
    vocab_list = "\n".join(f"- {i}" for i in sorted(INTERVENTIONS))

    return f"""You are a responsible-trading intervention specialist.

Below are user profiles with deterministic risk scores and detected behavioural patterns.
Your job is to produce a tiered intervention plan.

## User profiles (sorted by risk_score descending)
{json.dumps(profiles, indent=2)}

## Allowed intervention types (use only these exact labels)
{vocab_list}

## Rules
- Map each risk tier to an appropriate intervention type.
- Each recommendation must reference the user's specific patterns and feature evidence.
- Do not invent statistics or override the risk_tier or risk_score values.
- Copy must be empathetic, non-judgmental, and non-blaming.
- Do not produce medical, legal, or financial advice.

Respond ONLY with a JSON array matching this schema for every user:
[
  {{
    "user_id": "<string>",
    "risk_tier": "<low|medium|high|critical>",
    "intervention_type": "<one of the allowed types>",
    "triggering_patterns": ["<pattern>"],
    "evidence_summary": "<concise summary citing computed features>",
    "recommended_action": "<specific recommended action>"
  }}
]"""


def build_copy_prompt(intervention_types: list[str]) -> str:
    return f"""You are a responsible-trading copywriter.

Write short, empathetic user-facing messages for each of the following intervention types:
{json.dumps(intervention_types, indent=2)}

Rules:
- Be empathetic and supportive, never judgmental or blaming.
- Do not use shame-based language or pressure tactics.
- Do not make financial promises or give financial advice.
- Keep each message under 80 words.
- Do not use phrases like "you should", "stop losing", "guarantee", or "promise".

Respond ONLY with a JSON object mapping intervention_type to message text:
{{
  "<intervention_type>": "<message text>",
  ...
}}"""


def build_regulatory_prompt(intervention_types: list[str]) -> str:
    return f"""You are a gambling regulatory compliance expert.

Map each of the following responsible-trading intervention types to relevant
regulatory obligations from frameworks such as UKGC, MGA, GamblingAware, etc.

Intervention types:
{json.dumps(intervention_types, indent=2)}

For each mapping include:
- regulator_or_framework
- obligation_name
- explanation (1–2 sentences)
- citation (standard reference label)

Respond ONLY with a JSON array:
[
  {{
    "intervention_type": "<string>",
    "regulator_or_framework": "<string>",
    "obligation_name": "<string>",
    "explanation": "<string>",
    "citation": "<string>"
  }}
]"""

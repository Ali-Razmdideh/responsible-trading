# SPEC — Responsible-Trading Behavioural Pipeline

## Goal

Build a replayable pipeline that ingests anonymised trading-session data, computes deterministic behavioural features, uses staged LLM calls to classify trading behaviour from a controlled vocabulary, calculates auditable risk scores in code, and produces a responsible-trading intervention plan ranked by risk.

This is **not** a one-shot profiling report. The evaluator runs the pipeline from a clean checkout, may replace input data with equivalent fixtures, and verifies that features and risk scores are computed deterministically rather than delegated to the LLM.

## Inputs

Read from disk at the repo root:

- `trades.json` — `{ "trades": [ {...} ] }`
- `economic_calendar.json` — `[ { datetime_utc, event, impact } ]`

Trade record schema:

```
user_id, trade_id, open_ts, close_ts, instrument, direction,
stake_usd, payout_usd, result ("win" | "loss"), session_id
```

The bundled sample is a seed fixture only. The pipeline must extend or generate synthetic anonymised data to **≥ 8 users** and **≥ 800 trades** before feature computation. Extension is deterministic given a fixed seed and never overwrites real input rows.

## Pipeline stages (enforced in code)

```
INIT
 → INPUTS_LOADED
 → DATASET_EXTENDED_OR_VALIDATED
 → FEATURES_COMPUTED
 → PATTERNS_CLASSIFIED
 → RISK_SCORES_COMPUTED
 → INTERVENTIONS_GENERATED
 → VALIDATION_COMPLETE
 → RESULTS_FINALISED
```

A stage may not run before its predecessor's artifacts exist on disk. Final intervention rankings must not be produced before features and risk scores are persisted.

## Stage 1 — Feature engineering (deterministic)

Per user, compute and persist to `features/{user_id}.json`:

| Feature | Notes |
|---|---|
| `total_trades` | count |
| `average_stake` | mean of `stake_usd` |
| `stake_escalation_ratio_after_losses` | mean of `stake_n / stake_{n-1}` where trade `n-1` was a loss |
| `trades_per_minute` | trade count / active minutes spanned |
| `pct_trades_within_5min_of_high_impact_news` | from `economic_calendar.json`, `impact == "high"` |
| `win_rate` | wins / total_trades |
| `revenge_interval_seconds_avg` | mean seconds from a losing trade's `close_ts` to the next trade's `open_ts` |
| `longest_losing_streak` | longest run of consecutive losses |
| `total_net_pnl_usd` | Σ(payout − stake) |
| `average_session_duration_seconds` | mean of (max close_ts − min open_ts) per `session_id` |

Each file must include the **source counts / supporting values** used in the calculation (e.g. `n_loss_to_next_trade_pairs`, `total_active_seconds`, etc.) to make it auditable.

**Forbidden:** asking the LLM to compute any of these values.

## Stage 2 — Pattern classification (LLM, per user)

One LLM call per user. The prompt must include:

- the user's feature vector
- the user's last 30 trades in compact form
- the controlled pattern vocabulary
- a short definition for each pattern

Controlled vocabulary:

```
martingale, anti_martingale, revenge_trading, news_chasing,
scalping, position_doubling, normal, insufficient_evidence
```

Output (validated against schema and vocabulary):

```json
{
  "user_id": "string",
  "patterns": ["martingale"],
  "evidence": [
    {
      "pattern": "martingale",
      "triggering_features": ["stake_escalation_ratio_after_losses", "longest_losing_streak"],
      "trade_ids": ["t_00001", "t_00002"],
      "explanation": "string"
    }
  ],
  "confidence": "low | medium | high"
}
```

Aggregate to `patterns.json` (list of records, one per user).

If output fails validation, retry once. If it fails again, record the user as `insufficient_evidence` with a note in `evidence`.

## Stage 3 — Risk scoring (deterministic)

Compute a risk score in [0, 100] per user in code. Weights live in `src/pipeline/risk.py` and are documented in [risk_model.md](risk_model.md). The formula has a `FORMULA_VERSION` constant; bump on any weight change.

Score must consider:

- detected patterns (weight per pattern)
- feature severity (escalation ratio, trades per minute)
- frequency of rapid repeat trading
- stake escalation after losses
- news-event trading concentration
- longest losing streak
- recent net loss

Tier mapping (also in `risk.py`):

```
0–24   low
25–49  medium
50–74  high
75–100 critical
```

Output `risk_scores.json`, one record per user:

```json
{
  "user_id": "...",
  "risk_score": 0,
  "risk_tier": "low | medium | high | critical",
  "contributing_factors": [
    {"factor": "stake_escalation", "value": 2.1, "weight": 15, "contribution": 12}
  ],
  "formula_version": "v1"
}
```

**Forbidden:** asking the LLM to assign risk scores. Repeated runs on identical inputs must produce byte-identical `risk_scores.json`.

## Stage 4 — Intervention plan (LLM, single combined call)

One LLM call. Input bundle: all user profiles + features summary + detected patterns + deterministic risk scores. Output is a tiered intervention plan, sorted by `risk_score` descending.

Allowed intervention types:

```
soft_nudge, deposit_limit_prompt, cooling_off_period, human_outreach
```

Per-user intervention record:

```json
{
  "user_id": "string",
  "risk_tier": "low | medium | high | critical",
  "intervention_type": "string",
  "triggering_patterns": ["string"],
  "evidence_summary": "string",
  "recommended_action": "string"
}
```

Persisted to `interventions.json`. Each record must reference real user IDs, real patterns from Stage 2, and feature evidence.

## Stage 5 — False-positive audit (should attempt)

Pick at least one user classified as `martingale`. In deterministic code, walk the trade ledger and verify that stake escalates after losses. Output `false_positive_audit.json`:

```json
{
  "user_id": "string",
  "pattern": "martingale",
  "verified": true,
  "supporting_trade_sequence": ["trade_id"],
  "calculation": "string"
}
```

If no user is classified as `martingale`, the audit must explicitly state that no eligible user was available.

For the public sample, `u_001` must be flagged and verified.

## Stage 6 — Cohort insights (should attempt)

Computed in deterministic code. Each insight:

```json
{
  "metric": "string",
  "cohort": "string",
  "comparison_group": "string",
  "values": {"cohort": 0, "comparison": 0},
  "conclusion": "string"
}
```

Persisted to `cohort_insights.json`. The LLM does not invent statistics — values must be computed.

## Stage 7 — Responsible-trading copy (stretch)

Per intervention type, generate user-facing copy. Save under `messages/{intervention_type}.md` (or `.json`).

Copy must be empathetic, non-judgmental, non-blaming, concise, free of financial promises, and free of shame-based language.

## Stage 8 — Regulatory mapping (stretch)

`regulatory_mapping.json`. Per intervention type:

```json
{
  "intervention_type": "string",
  "regulator_or_framework": "string",
  "obligation_name": "string",
  "explanation": "string",
  "citation": "string"
}
```

## Required artifacts

```
trades.json
economic_calendar.json
features/{user_id}.json   (one per user)
patterns.json
risk_scores.json
risk_model.md
interventions.json
false_positive_audit.json   (if attempted)
cohort_insights.json        (if attempted)
messages/                   (if attempted)
regulatory_mapping.json     (if attempted)
llm_calls.jsonl
```

## `llm_calls.jsonl`

One JSON object per line, per LLM call:

```json
{
  "stage": "string",
  "user_id": "string | null",
  "timestamp": "ISO-8601",
  "provider": "string",
  "model": "string",
  "prompt_hash": "sha256 hex",
  "input_artifacts": ["path"],
  "output_artifact": "path"
}
```

Required entries: one per per-user pattern classification, one for the combined intervention call, plus one each for copy generation and regulatory mapping if attempted.

## Validation (`python validate.py`)

Must check:

- all required artifacts exist
- every JSON file parses
- a feature file exists for every user_id present in `trades.json`
- features were written before `patterns.json` (mtime check + state log)
- `risk_scores.json` is reproducible: re-run risk scoring deterministically and compare
- `risk_scores.json` was produced before `interventions.json`
- every intervention's `user_id` exists in the user set
- every intervention references at least one pattern present in `patterns.json` for that user
- `llm_calls.jsonl` contains exactly one pattern-classification record per user
- `llm_calls.jsonl` contains an interventions record
- if `u_001` is present, it is flagged as `martingale` or `position_doubling` with evidence

Exit non-zero on any failure and print a clear diagnostic.

## Execution

- Run from clean checkout: `python run.py`
- Validate: `python validate.py`
- The evaluator may delete generated artifacts and re-run.
- The evaluator may replace inputs with equivalent fixtures.
- Static precomputed outputs are not sufficient.

## Constraints (recap)

- Feature engineering: deterministic code only.
- Risk scoring: deterministic code only.
- Pattern classification: controlled vocabulary, with cited features and trade IDs.
- Intervention copy: no shame, no blame, no pressure, no financial promises.
- No real personal data.
- No inference of protected/demographic attributes.
- No medical, legal, or per-user financial advice.
- Sample `u_001` must be detected when present.

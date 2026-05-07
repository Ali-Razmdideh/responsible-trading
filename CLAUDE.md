# CLAUDE.md

Guidance for Claude Code working in this repo. Keep it terse, follow KISS.

## Project

A replayable pipeline that ingests anonymised trading-session data, computes deterministic behavioural features, uses staged LLM calls to classify trading patterns from a controlled vocabulary, scores risk in deterministic code, and produces a ranked responsible-trading intervention plan.

See [SPEC.md](SPEC.md) for the full problem statement and acceptance contract.

## Golden rules

1. **Determinism over LLMs.** Features and risk scores are computed in pure Python. The LLM classifies patterns and drafts interventions — it does NOT compute numbers.
2. **Stage separation is enforced in code.** No stage may run before its predecessor's artifacts exist on disk. State machine: `INIT → INPUTS_LOADED → DATASET_EXTENDED_OR_VALIDATED → FEATURES_COMPUTED → PATTERNS_CLASSIFIED → RISK_SCORES_COMPUTED → INTERVENTIONS_GENERATED → VALIDATION_COMPLETE → RESULTS_FINALISED`.
3. **Replayable from a clean checkout.** The evaluator may delete generated artifacts and may swap `trades.json` / `economic_calendar.json` for equivalent fixtures. Never hardcode user IDs, trade IDs, or final outputs.
4. **Every LLM call is logged** to `llm_calls.jsonl` with stage, user_id, timestamp, provider, model, prompt hash, input artifacts, output artifact.
5. **Interventions must be grounded** in computed evidence — cite user_id, triggering patterns, and feature/trade evidence.
6. **Controlled vocabularies are constants.** Patterns and intervention types are defined once in code; the LLM must pick from them.

## Layout

```
src/pipeline/
  stages.py          # state machine + stage runner
  io.py              # load/save JSON artifacts
  dataset.py         # extend/validate trades.json to ≥8 users / ≥800 trades
  features.py        # deterministic feature computation
  patterns.py        # Stage 1 LLM call (per user)
  risk.py            # deterministic risk scoring
  interventions.py   # Stage 2 LLM call (combined)
  audit.py           # false-positive audit
  cohort.py          # cohort insights
  copy.py            # message copy generation (stretch)
  regulatory.py      # regulatory mapping (stretch)
  llm.py             # LLM client wrapper + call logger
  vocab.py           # controlled vocabularies (PATTERNS, INTERVENTIONS, TIERS)
  validate.py        # post-run validation
run.py               # CLI entrypoint: `python run.py`
validate.py          # `python validate.py`
tests/
artifacts/           # generated outputs (gitignored except samples)
  features/
  messages/
  patterns.json
  risk_scores.json
  interventions.json
  false_positive_audit.json
  cohort_insights.json
  regulatory_mapping.json
  llm_calls.jsonl
trades.json
economic_calendar.json
risk_model.md        # documents weights + formula version
SPEC.md
README.md
```

Keep modules small and single-purpose. No premature abstraction.

## Commands

- `python run.py` — run the full pipeline end-to-end.
- `python run.py --stage features` — run a single stage (assumes prior stage artifacts exist).
- `python validate.py` — validate artifacts.
- `pytest` — unit tests for features, risk, audit.

## Determinism checklist

- Sort users and trades by ID before iterating.
- No `set()` ordering in outputs — use sorted lists.
- No `datetime.now()` in feature/risk code — use trade timestamps.
- Risk scoring uses fixed weights from `risk.py`; bump `FORMULA_VERSION` when weights change.
- Repeated runs over identical inputs must produce byte-identical `risk_scores.json` (LLM stages are allowed to vary, but cite evidence either way).

## LLM rules

- One Stage 1 call **per user** for pattern classification.
- One Stage 2 call total for the intervention plan, given all profiles + scores.
- Prompts must include: feature vector, last 30 trades (compact), the controlled vocabulary, and pattern definitions.
- Hash the rendered prompt (sha256) and log it. Save raw responses under `artifacts/llm_raw/` for replay.
- Validate LLM output against the controlled vocab; reject and retry once on schema/vocab violations; on second failure, mark `insufficient_evidence`.

## Don't

- Don't ask the LLM for numeric features or risk scores.
- Don't let the LLM invent cohort statistics — pass it computed values only.
- Don't write shaming, blaming, or pressuring copy. No financial promises. No medical/legal/financial advice.
- Don't infer protected/demographic attributes.
- Don't commit real personal data or secrets. `.env` is gitignored.
- Don't skip the state machine to "save a step."

## Testing the public sample

When the bundled sample fixture is in place, `u_001` must be flagged as `martingale` (or `position_doubling`) with verified stake escalation in the false-positive audit.

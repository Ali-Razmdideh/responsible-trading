# Responsible-Trading Behavioural Pipeline

A replayable pipeline that ingests anonymised trading-session data, computes
deterministic behavioural features, classifies trading patterns via staged LLM
calls, scores risk in pure code, and produces a ranked responsible-trading
intervention plan.

See [SPEC.md](SPEC.md) for the full problem statement and acceptance contract,
and [CLAUDE.md](CLAUDE.md) for codebase conventions.

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. (Real LLM only) set your OpenAI API key
cp .env.example .env
# edit .env → OPENAI_API_KEY=sk-...

# 3. Run end-to-end
python run.py --mock-llm    # deterministic, no API key
python run.py               # real LLM (requires OPENAI_API_KEY)

# 4. Validate artifacts
python validate.py

# 5. Run the unit suite
pytest -q
```

## Run with Docker

The image is multi-stage, runs as a non-root `app` user, and uses an isolated
`/opt/venv`.

```bash
# Build
docker build -t deriv-pipeline .

# Run with the deterministic mock (no API key needed).
# Mount the host directory so generated artifacts persist locally.
docker run --rm -v "$PWD":/app deriv-pipeline --mock-llm --reset

# Run with a real LLM
docker run --rm \
  -e OPENAI_API_KEY="$OPENAI_API_KEY" \
  -v "$PWD":/app \
  deriv-pipeline --reset

# Run validation inside the container
docker run --rm -v "$PWD":/app --entrypoint python deriv-pipeline validate.py
```

## Pipeline stages

```
INIT → INPUTS_LOADED → DATASET_EXTENDED_OR_VALIDATED → FEATURES_COMPUTED
     → PATTERNS_CLASSIFIED → RISK_SCORES_COMPUTED → INTERVENTIONS_GENERATED
     → VALIDATION_COMPLETE → RESULTS_FINALISED
```

A stage may not run before its predecessor's artifacts are on disk. State is
persisted in `.pipeline_state.json` (gitignored). The `FEATURES_COMPUTED` guard
also rejects an empty `features/` directory.

## CLI flags

| Flag | Description |
|------|-------------|
| `--mock-llm` | Deterministic mock classifier — no API calls |
| `--seed N` | Synthetic data seed (default `42`; keep fixed for reproducibility) |
| `--stage NAME` | Stop after this stage (`inputs`, `dataset`, `features`, `patterns`, `risk`, `interventions`) |
| `--reset` | Clear pipeline state before running |

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | Required for real LLM mode |
| `PIPELINE_MODEL` | `gpt-4o-mini` | OpenAI model name |
| `PIPELINE_MOCK_LLM` | `false` | Set `true` to enable mock mode |
| `PIPELINE_SEED` | `42` | Synthetic data RNG seed |

## Generated artifacts

| Artifact | Description |
|----------|-------------|
| `features/{user_id}.json` | Per-user deterministic feature vector + audit counts |
| `patterns.json` | LLM pattern classifications (Stage 1) |
| `risk_scores.json` | Deterministic risk scores (0–100) with formula version |
| `risk_model.md` | Risk weights and formula documentation |
| `interventions.json` | Ranked intervention plan (Stage 2) |
| `false_positive_audit.json` | Martingale escalation audit |
| `cohort_insights.json` | Cohort-level computed statistics |
| `messages/` | Responsible-trading copy per intervention type |
| `regulatory_mapping.json` | Regulatory obligation mapping |
| `llm_calls.jsonl` | Log of every LLM call (truncated at the start of each run) |
| `artifacts/trades_extended.json` | Extended ledger when synthetic users were generated — input `trades.json` is **never** overwritten |
| `artifacts/llm_raw/` | Raw LLM responses for replay |

## Determinism & safety

- Features and risk scores are pure Python — no randomness, no LLM, no
  `datetime.now()` in feature/risk code.
- `trades_per_minute` uses the **sum of session durations**, not wall-clock
  span — long inter-session gaps don't deflate the metric.
- Repeated runs over identical inputs produce byte-identical
  `risk_scores.json`.
- LLM responses are validated against the controlled vocabulary; on schema /
  parse failure the call is retried once, then falls back to
  `insufficient_evidence`.
- Every LLM call is logged with stage, user_id, prompt sha256, input
  artifacts, and output artifact path.
- IDs (`user_id`, `trade_id`, `session_id`) are validated against
  `^[A-Za-z0-9_\-]{1,64}$` to prevent path traversal when writing per-user
  files.
- Banned-phrase filter blocks shaming, blaming, or financial-promise copy
  before it reaches `messages/`.

## Evaluator checklist

```bash
# Clean run from scratch
rm -rf features/ patterns.json risk_scores.json interventions.json \
       false_positive_audit.json cohort_insights.json messages/ \
       regulatory_mapping.json llm_calls.jsonl artifacts/ .pipeline_state.json

python run.py --mock-llm --reset
python validate.py          # must exit 0

# Determinism check
sha256sum risk_scores.json > /tmp/hash1
rm -rf features/ patterns.json risk_scores.json interventions.json \
       llm_calls.jsonl artifacts/ .pipeline_state.json
python run.py --mock-llm --reset
sha256sum risk_scores.json > /tmp/hash2
diff /tmp/hash1 /tmp/hash2  # must be empty

# Unit tests
pytest -q
```

The evaluator may swap `trades.json` and `economic_calendar.json` for
equivalent fixtures — the pipeline preserves the input file and writes any
extension to `artifacts/trades_extended.json`.

## Layout

```
src/pipeline/
  state.py           state machine + stage guards
  io.py              JSON/JSONL load/save helpers
  dataset.py         input validation + synthetic extension to ≥8 users / ≥800 trades
  features.py        deterministic feature computation
  patterns.py        Stage 1 LLM call (per user) + retry / vocab validation
  risk.py            deterministic risk scoring
  interventions.py   Stage 2 LLM call (combined)
  audit.py           false-positive audit
  cohort.py          cohort insights
  copy.py            responsible-trading message copy
  regulatory.py      regulatory mapping
  llm.py             LLM client wrapper + call logger + mock implementations
  vocab.py           controlled vocabularies (PATTERNS, INTERVENTIONS, TIERS)
  prompts.py         prompt templates
run.py               CLI entrypoint
validate.py          artifact validator
tests/               unit tests for features, risk, audit, dataset, state, validate
```

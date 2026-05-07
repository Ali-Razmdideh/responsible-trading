# Responsible-Trading Behavioural Pipeline

A replayable pipeline that ingests anonymised trading-session data, computes deterministic behavioural features, classifies trading patterns via staged LLM calls, scores risk in pure code, and produces a ranked responsible-trading intervention plan.

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set your OpenAI API key
cp .env.example .env
# Edit .env and add: OPENAI_API_KEY=sk-...

# 3. Run the full pipeline (real LLM)
python run.py

# Or run with the deterministic mock (no API key needed)
python run.py --mock-llm

# 4. Validate all artifacts
python validate.py

# 5. Run unit tests
pytest
```

## Pipeline stages

```
INIT → INPUTS_LOADED → DATASET_EXTENDED_OR_VALIDATED → FEATURES_COMPUTED
     → PATTERNS_CLASSIFIED → RISK_SCORES_COMPUTED → INTERVENTIONS_GENERATED
     → VALIDATION_COMPLETE → RESULTS_FINALISED
```

Each stage only runs after its predecessor's artifacts are on disk. State is persisted to `artifacts/.pipeline_state.json`.

## Flags

| Flag | Description |
|------|-------------|
| `--mock-llm` | Use deterministic mock classifier (no API calls) |
| `--seed N` | Synthetic data seed (default: 42, must stay fixed for reproducibility) |
| `--stage NAME` | Stop after this stage (inputs, dataset, features, patterns, risk, interventions) |
| `--reset` | Clear pipeline state before running |

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | Required for real LLM mode |
| `PIPELINE_MODEL` | `gpt-5` | OpenAI model name |
| `PIPELINE_MOCK_LLM` | `false` | Set to `true` to enable mock mode |
| `PIPELINE_SEED` | `42` | Synthetic data RNG seed |

## Generated artifacts

| Artifact | Description |
|----------|-------------|
| `features/{user_id}.json` | Per-user deterministic feature vector |
| `patterns.json` | LLM pattern classifications (Stage 1) |
| `risk_scores.json` | Deterministic risk scores (0–100) |
| `risk_model.md` | Risk formula documentation |
| `interventions.json` | Ranked intervention plan (Stage 2) |
| `false_positive_audit.json` | Martingale audit results |
| `cohort_insights.json` | Cohort-level computed statistics |
| `messages/` | Responsible-trading copy per intervention type |
| `regulatory_mapping.json` | Regulatory obligation mapping |
| `llm_calls.jsonl` | Log of every LLM call |

## Evaluator checklist

```bash
# Clean run from scratch
rm -rf features/ patterns.json risk_scores.json interventions.json \
       false_positive_audit.json cohort_insights.json messages/ \
       regulatory_mapping.json llm_calls.jsonl artifacts/

python run.py --mock-llm
python validate.py          # must exit 0

# Determinism check
sha256sum risk_scores.json > /tmp/hash1
rm -rf features/ patterns.json risk_scores.json interventions.json llm_calls.jsonl artifacts/
python run.py --mock-llm
sha256sum risk_scores.json > /tmp/hash2
diff /tmp/hash1 /tmp/hash2  # must be empty

# Unit tests
pytest -q
```

## Design principles

- **Determinism:** features and risk scores are pure Python — no randomness, no LLM.
- **Stage separation:** the state machine enforces ordering in code.
- **Auditability:** every feature file includes source counts; every risk record includes contributing factors.
- **Grounded interventions:** the LLM must cite computed features and detected patterns; the pipeline cross-validates before writing.
- **Safe copy:** banned-phrase filter guards against shaming or pressuring language.

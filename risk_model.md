# Risk Model — Formula Documentation

**Formula version:** `v1`  
**Source of truth:** `src/pipeline/risk.py` — `WEIGHTS` and `score_user()`

---

## Overview

Risk scores are computed deterministically in pure Python. The LLM is **not** involved in scoring. Repeated runs on identical inputs produce byte-identical `risk_scores.json`.

Scores range from **0 to 100** and map to four tiers:

| Score range | Tier     |
|-------------|----------|
| 0 – 24      | low      |
| 25 – 49     | medium   |
| 50 – 74     | high     |
| 75 – 100    | critical |

---

## Components

### 1. Pattern contributions

Each detected pattern adds a fixed number of points. All patterns for a user are summed.

| Pattern              | Points |
|----------------------|--------|
| martingale           | 25     |
| revenge_trading      | 20     |
| position_doubling    | 20     |
| news_chasing         | 15     |
| anti_martingale      | 10     |
| scalping             | 5      |
| normal               | 0      |
| insufficient_evidence| 0      |

### 2. Stake escalation after losses

`excess = max(stake_escalation_ratio_after_losses − 1.0, 0)`  
`contribution = min(excess × 10, 25)`

Cap: **25 points**

### 3. Trades per minute

`excess = max(trades_per_minute − 0.5, 0)`  
`contribution = min(excess × 8, 15)`

Cap: **15 points**

### 4. News adjacency

`contribution = min((pct_trades_within_5min_of_high_impact_news × 100 / 10) × 5, 15)`

Cap: **15 points**

### 5. Longest losing streak

`excess = max(longest_losing_streak − 3, 0)`  
`contribution = min(excess × 3, 15)`

Cap: **15 points**

### 6. Recent net loss

`loss_usd = max(−total_net_pnl_usd, 0)`  
`contribution = min((loss_usd / 100) × 2, 10)`

Cap: **10 points**

---

## Total

`risk_score = clamp(sum_of_all_contributions, 0, 100)`

Each record in `risk_scores.json` includes a `contributing_factors` list with per-factor `value`, `weight`, and `contribution` for full auditability.

---

## Reproducibility guarantee

`score_user()` is a pure function with no random state or I/O. Given the same `features` dict and `patterns` list, it always produces the same `risk_score`. The validation script (`validate.py`) re-runs scoring and asserts byte-identical output.

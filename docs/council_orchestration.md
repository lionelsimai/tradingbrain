# TradingBrain Council Orchestration

TradingBrain now has a schema-enforced multi-agent council supervisor. The goal is to avoid the classic failure mode of large agent teams: more voices, more latency, and more false confidence without better evidence.

This implementation treats the council as a measurable operating system:

- typed role contracts;
- operating modes with required agents;
- machine-readable reviews;
- hard-veto precedence;
- confidence ceilings;
- evidence-quality scorecards;
- fail-closed CEO synthesis;
- audit artifacts under `reports/council/<run_id>/`.

Research/paper-only. No live execution authority.

## Core files

- `agents/schemas.py`
  - `tradingbrain_council_agent_review.v1`
  - `tradingbrain_council_decision.v1`
  - validators for reviews/final decisions
  - mode definitions and hard-veto precedence

- `scripts/agents/council_orchestrator.py`
  - collects read/propose-only evidence
  - creates schema-valid reviews for required roles
  - applies fail-closed veto precedence
  - writes JSON/Markdown artifacts

- `scripts/agent/hermes_tools.py`
  - exposes `get_council_orchestration`

- `config/hermes_agent.yaml`
  - declares operating model, real worker lanes, operating modes, hard-veto rules

- `tests/test_council_orchestrator.py`
  - verifies schemas, nested forbidden fields, hard vetoes, artifact writes, tool registry, config

## Operating modes

### `fast_quorum`

Required agents:

- 01 CEO Decision Agent
- 02 Red Team Agent
- 03 Data Integrity Agent
- 04 Risk Manager Agent
- 15 Kill Switch Agent

Use for quick Telegram decisions and fast research checks.

### `market_open`

Required agents:

- 01 CEO Decision Agent
- 03 Data Integrity Agent
- 04 Risk Manager Agent
- 05 Macro/Rates Agent
- 06 News/Catalyst Agent
- 07 Technical Pattern Agent
- 09 Sentiment/Manipulation Agent
- 15 Kill Switch Agent

Use for US open watchlists, gap risk, premarket confirmation, and fade/chase detection.

### `full_ai_stock`

Required agents:

- 01 CEO Decision Agent
- 02 Red Team Agent
- 03 Data Integrity Agent
- 04 Risk Manager Agent
- 05 Macro/Rates Agent
- 06 News/Catalyst Agent
- 07 Technical Pattern Agent
- 08 Fundamental Quality Agent
- 09 Sentiment/Manipulation Agent
- 10 AI Sector Specialist
- 15 Kill Switch Agent

Use for serious single-name or multi-name AI stock reviews.

### `proof_heavy`

Required agents:

- 01 CEO Decision Agent
- 02 Red Team Agent
- 03 Data Integrity Agent
- 04 Risk Manager Agent
- 11 Paper Trading Agent
- 12 Forward Evidence Agent
- 13 Backtest Gauntlet Agent
- 15 Kill Switch Agent

Use for validation, proof-gate, recommender self-audits, and go-live blockers.

### `portfolio`

Required agents:

- 01 CEO Decision Agent
- 03 Data Integrity Agent
- 04 Risk Manager Agent
- 05 Macro/Rates Agent
- 08 Fundamental Quality Agent
- 10 AI Sector Specialist
- 14 Portfolio Construction Agent
- 15 Kill Switch Agent

Use for basket, concentration, cluster, and exposure questions.

### `cross_asset`

Required agents:

- 01 CEO Decision Agent
- 02 Red Team Agent
- 03 Data Integrity Agent
- 04 Risk Manager Agent
- 05 Macro/Rates Agent
- 07 Technical Pattern Agent
- 09 Sentiment/Manipulation Agent
- 20 Crypto/Gold Cross-Asset Agent
- 15 Kill Switch Agent

Use for crypto/gold/equity macro crossover questions.

## Hard-veto precedence

Majority never overrides the following open hard vetoes:

1. `paper_safety`
2. `data_integrity`
3. `risk`
4. `red_team`
5. `proof`
6. `kill_switch`

If any open hard veto exists, the final decision cannot be `bullish_watch`; the supervisor fails closed to `stand_aside` or an equivalent non-bullish verdict.

## Agent review schema

Every council worker must return:

- `schema_version`
- `run_id`
- `mode`
- `role`
- `scope`
- `verdict`
- `confidence_range`
- `evidence_quality`
- `scorecard`
- `evidence_used`
- `missing_evidence`
- `vetoes_or_penalties`
- `next_action`
- `audit`

Forbidden executable fields are rejected even when nested:

- `order`
- `submit`
- `position_size`
- `qty`
- `broker`

This prevents an agent from smuggling an executable instruction inside a research note.

## Run from CLI

```bash
cd /Users/lionel/.hermes/tradingbrain/TradingBrain
source .venv/bin/activate
export TRADINGBRAIN_ROOT="$PWD"
export TB_MODE=paper
export HERMES_TRADING_MODE=paper

python -m scripts.agents.council_orchestrator \
  "Evaluate NVDA as a research-only market-open watch" \
  --mode market_open \
  --tickers NVDA \
  --horizon intraday
```

## Run through Hermes tool registry

Tool name:

```text
get_council_orchestration
```

Arguments:

```json
{
  "question": "Evaluate NVDA, MU, and ARM for market-open upside",
  "tickers": ["NVDA", "MU", "ARM"],
  "mode": "market_open",
  "asset_class": "equity",
  "horizon": "intraday"
}
```

## Artifacts

Each run writes:

- `reports/council/<run_id>/evidence.json`
- `reports/council/<run_id>/agent-XX-<role>.json`
- `reports/council/<run_id>/council-decision.json`
- `reports/council/<run_id>/summary.md`

## Verification

Validated with:

```text
pytest -q tests/test_council_orchestrator.py tests/test_agent_permissions.py tests/test_hermes_agent.py
30 passed

pytest -q
374 passed

python -m scripts.validate_all
Validation infrastructure: HEALTHY
Go-live: BLOCKED
Validation gauntlet: REJECTED
World-class readiness: RESEARCH_ONLY
```

The system remains research/paper-only and fail-closed.

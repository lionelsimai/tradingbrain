# TradingBrain — Repository Build Audit (Section 4)

Pre-change inventory used to plan the V3 safety build. Generated 2026-05-30.

## File inventory (production, excl. `reference/` archive + `__pycache__`)
- Python files: 115 total (≈ 90 production, ≈ 25 tests)
- Top-level packages: `safety/ execution/ journal/ data/ lab/ portfolio/ strategies/
  agents/ monitoring/ operator/ db/ scorecards/ backtest/ scripts/ loops/`
- Archived (NOT production, excluded from CI safety scans): `reference/`, `deprecated/`

## Architecture decision
The V3 prompt (Section 3) specifies a nested `tradingbrain/` package tree. We keep
the **flat top-level layout** instead (same module names, no `tradingbrain.` prefix)
to honor Section 3's explicit rule *"do not move everything blindly; preserve current
working behavior; add adapter layers first."* A wholesale move would break ~90 working
imports for zero safety gain. Every required module from the Section-3 tree exists as
a flat package module.

## Unsafe paths (found → status)
| Path | Issue | Status |
|---|---|---|
| `scripts/wrappers/alpaca.sh` | direct order/cancel/close/close-all | ✅ quarantined to `deprecated/unsafe_wrappers/`, replaced read-only |
| `scripts/broker_alpaca.py` | submitted orders w/o gate | ✅ now routes via `OrderManager` + `risk_gate` |
| `routines/market-open.md`, `routines/midday.md` | told user to place/close via wrapper | ✅ rewritten to operator/order_manager |
| `reference/phase1-skeleton/agent/broker.py` | order-capable | ⚪ archived, excluded from CI; not importable in prod path |

## Order Path Matrix
| entry point | file | function | action | paper/live | current checks | missing | severity | patch | test |
|---|---|---|---|---|---|---|---|---|---|
| signal→order | `execution/order_manager.py` | `submit` | propose→submit | paper | config,kill,quote,risk,portfolio,journal,idempotency | partial-fill SM | — | built | `test_order_manager`, `test_safety_invariants` |
| broker mirror | `scripts/broker_alpaca.py` | `main` | mirror paper→broker | paper | routes via OrderManager | — | low | done | `test_red_team` |
| paper engine | `scripts/paper_broker.py` | `main` | open/close paper | paper | policy-sourced sizing | not yet via OrderManager | P1 | planned | — |
| wrapper | `scripts/wrappers/alpaca.sh` | n/a | read-only | n/a | read-only | — | — | done | `test_no_unsafe_wrappers` |

## Config Matrix
| file | setting | value | active? | conflict | canonical dest | migration |
|---|---|---|---|---|---|---|
| `config/risk_policy.yaml` | all risk | canonical | ACTIVE | — | self | — |
| `config/session.yaml` | max_position_pct, heat | 10, 4 | PASSIVE | resolved | risk_policy.yaml | aligned + marked passive |
| `config/sources.yaml` | risk_rules | various | PASSIVE | — | risk_policy.yaml | read-only legacy |

## Scorecard Matrix
| file | evidence | used by calibration | used by gating | safe? | patch |
|---|---|---|---|---|---|
| `reports/scorecard-replay.json` | replay | yes (suppress-only) | no live gate | ✅ | source-tagged |
| `reports/scorecard-live.json` | live (empty) | live gate only | yes (needs n≥30) | ✅ | created |
| `reports/scorecard-paper.json` | paper (empty) | no | no | ✅ | created |
| `reports/live-scorecard.json` | legacy replay | fallback | no | ⚪ | superseded |

## SQL schema mismatches (found → status)
- `loops/eod_close.py` queried `open_count/open_risk_R/closed_today` vs schema
  `n_open/total_risk/closed` → ✅ fixed via SELECT aliases.
- `kb()` never applied `KB_SCHEMA` (docstring lied) → ✅ fixed; multi-statement exec.
- `paper_positions`, `paper_account` had no DDL anywhere → ✅ added to schema.
- `documents` table failed to create (split-on-`;` fragility) → ✅ fixed.

## Dependency gaps
- Clean sandbox lacked `duckdb` → ✅ `requirements.txt` + `constraints.txt` pinned;
  clean-venv proof passes 54 safety tests.

## Hardcoded paths
- 63 production files still hardcode the repo root (legacy loops/scripts).
- Safety-critical core (`safety/ execution/ journal/ data/ paths.py`) = **0 literals**.
- Remainder tracked as **P2** (portability migration via `paths.py`).

## Tests
- Baseline at audit start: 74 passing (39 pre-V3 + 35 V3 safety/governance).
- Target: full Section-35 plan (~28 files).

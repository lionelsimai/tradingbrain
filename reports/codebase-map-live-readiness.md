# TradingBrain Codebase Map for Live-Readiness Hardening

_generated 2026-06-02_

This map is an engineering review aid. It is not a live-trading approval.

| Area | Key files | Current strength | Current weakness / missing proof | Live-risk surface | Required next tests / code / reports |
|---|---|---|---|---|---|
| Core trading engine | `scripts/recommend.py`, `loops/realtime_picks.py`, `loops/desk_signals.py` | Produces scored ideas and defined-risk plans. | Edge is still replay/backtest-led. | AI or strategy confidence can overstate thin evidence. | Keep conviction cap; add forward-paper drift gates. |
| Backtest | `backtest/`, `lab/gauntlet.py`, `lab/validate.py` | Cost, validation, no-lookahead, gauntlet reports exist. | Survivorship-free point-in-time universe remains unproven. | False edge from biased history. | Add delisted-inclusive/PIT data proof report. |
| Stress test | `lab/live_readiness_stress.py`, `lab/scenario_factory.py` | Live-readiness stress runner and scenario inventory now exist. | Many data scenarios are registered inventory, not full synthetic mutations yet. | Untested data and market microstructure failures. | Expand each inventory case into deterministic mutation tests. |
| Walk-forward | `reports/walk-forward.json`, `lab/gauntlet.py` | Walk-forward report exists and feeds go-live. | Overfitting gate still blocks. | IS/OOS decay masked by blended metrics. | Add strategy-by-regime walk-forward regression cases. |
| Risk policy | `config/risk_policy.yaml`, `safety/risk_policy.py`, `safety/risk_gate.py` | Canonical policy validates as `rp_c1b79487863d`. | Policy cannot prove profitability. | Oversizing, heat, drawdown, weak confidence. | Continue forbidden weakening scan and risk-gate regression tests. |
| Safety | `safety/config_guard.py`, `safety/kill_switch.py`, `safety/live_readiness.py` | Fail-closed checks and live-readiness authority exist. | Live status remains blocked by evidence. | Any bypass of mode, kill switch, go-live, stale state. | Add more unreadable/corrupt state tests. |
| Execution | `execution/order_manager.py`, `execution/order_lifecycle.py` | Single sanctioned order submit path. | Broker chaos is simulated, not broker-sandbox proven. | Duplicate orders, broker rejects/timeouts, bad fills. | Keep red-team submit invariant; add sandbox paper replay. |
| Broker adapters | `execution/broker_base.py`, `execution/paper_adapter.py`, `execution/fake_broker_chaos.py` | Fake hostile broker now covers major bad broker behaviors. | No live broker path enabled; paper broker evidence thin. | Disconnects, duplicates, partial fills, unknown state. | Add broker sandbox forward-paper scorecard. |
| Paper trading | `loops/signal_tracker.py`, `reports/scorecard-paper.json` | Paper/live/replay provenance now separated. | 0 resolved forward paper trades. | Replay accidentally satisfying paper gate. | Run paper runner until 50, then 200 resolved observations. |
| Reconciliation | `execution/reconciliation.py`, `loops/reconcile.py` | Reconciliation tests exist and score is tracked. | Needs more hostile broker-state fixtures. | Ghost/missing positions, cash/qty mismatch. | Add broker chaos reconciliation matrix. |
| Protective orders | `execution/protective_orders.py`, `execution/order_manager.py` | Stops and targets checked in order flow. | Stop attachment failure is simulated, not externally proven. | Filled position without stop. | Add incident-to-runbook-to-recovery verification. |
| Journal | `safety/trade_journal.py`, `journal/event_store.py`, `reports/journal/` | Rejections and order events are journaled. | Forward paper lifecycle journal is still thin. | Missing audit trail for decisions and failures. | Require journal completeness in scorecard. |
| Monitoring | `monitoring/live_readiness_dashboard.py`, `monitoring/alerts.py`, `monitoring/health.py` | Dashboard JSON exposes blockers, evidence, hashes. | Alert routing is local/report-based. | Stale dashboard or missed critical alert. | Add dashboard freshness and alert delivery tests. |
| Dashboard / app | `app/`, `scripts/export_app.py` | App export validates and separates paper/live/replay evidence. | UI still depends on local/export freshness when Supabase absent. | Showing fake readiness or replay as paper. | Add UI truthfulness screenshot/browser checks. |
| Config | `config/`, `scripts/ci_forbidden_live_weakening.sh` | Static safety and forbidden live weakening scans pass. | Threshold changes still need human approval process metadata. | Live enablement or weaker risk defaults. | Add approval-bound threshold-change workflow. |
| Tests | `tests/` | Full pytest passes with live-readiness additions. | Test count differs between direct pytest and validate harness due harness scope. | Safety regressions hidden by partial runs. | Keep direct pytest and validate_all both in CI. |
| Report generation | `scripts/validate_all.py`, `lab/live_readiness_dossier.py` | Stress, dashboard, dossier, scorecards, go-live reports exist. | Dedicated red-team live-readiness JSON still pending. | Missing report accidentally counted as pass. | Add `scripts/red_team_live_readiness.py`. |
| Self-improvement | `loops/harden_live_readiness.py`, `loops/improve.py` | Bounded loop refuses forbidden live-enablement fixes. | It ranks blockers but does not auto-patch evidence gaps. | Agent self-modifies safety thresholds. | Add patch classifier audit output per iteration. |
| Agents | `scripts/agents/`, `scripts/collective/` | Multi-agent review layer exists. | AI outputs still need stricter schema/source validation. | Hallucinated quote, earnings, confidence, or live request. | Add AI stress schema tests and red-team findings report. |
| Runbooks | `docs/RUNBOOK_LIVE_READINESS.md`, `docs/runbook.md` | Live-readiness incident runbook exists. | Needs operator drills from real paper incidents. | Slow recovery during unprotected/unknown state. | Add post-incident test links per runbook section. |

## Bottom line

TradingBrain is materially stronger as a live-like paper stress platform, but the correct live verdict remains blocked. The next hardening jump is not more indicators; it is real forward paper evidence, broker-sandbox fills, and point-in-time/delisted-inclusive data proof.

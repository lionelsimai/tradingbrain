"""TradingBrain safety core — the layer that stands between a proposed trade and
a real order. Nothing here generates alpha; everything here prevents catastrophe.

Modules:
  config_guard  — trading mode (paper default), config validation, live fails closed.
  kill_switch   — master halt + granular pause (all / strategy / symbol). File-backed.
  risk_gate     — the single pre-trade decision point. Every order must pass.
  trade_journal — append-only audit trail: idea -> risk -> order -> fill -> exit.
  order         — order schema + deterministic idempotency keys + state machine.
  logging_setup — structured JSON logging.
  operator      — human-control CLI (status/pause/resume/kill/close_all/...).

Design rule: the AI proposes, the risk_gate decides size, execution places orders,
and the human/policy layer approves anything risky. No component may skip the gate.
"""

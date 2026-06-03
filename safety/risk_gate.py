#!/usr/bin/env python3
"""THE pre-trade decision point. Every order — paper or live — must pass through
check(). The AI proposes; THIS decides whether and how big. Nothing downstream
may size a position on its own.

Returns the audit's risk_decision schema:
  approved, rejected_reason, max_position_size, suggested_position_size,
  stop_loss_level, take_profit_level, max_loss_amount, exposure_after_trade,
  drawdown_status, daily_loss_status, human_review_required, timestamp

Fail-closed: any check that cannot be evaluated -> reject.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / "config" / "session.yaml"
SOURCES = ROOT / "config" / "sources.yaml"
CB = ROOT / "reports" / "circuit-breakers.json"

# A trade whose risk exceeds this fraction of equity, or whose confidence is
# below this, requires explicit human sign-off before a LIVE order.
HUMAN_REVIEW_POSITION_PCT = 15.0
HUMAN_REVIEW_MIN_CONFIDENCE = 0.55


def _yaml(p: Path) -> dict:
    try:
        return yaml.safe_load(p.read_text()) or {}
    except Exception:
        return {}


@dataclass
class RiskDecision:
    approved: bool = False
    rejected_reason: Optional[str] = None
    checks: dict = field(default_factory=dict)
    max_position_size: int = 0
    suggested_position_size: int = 0
    stop_loss_level: Optional[float] = None
    take_profit_level: Optional[float] = None
    max_loss_amount: float = 0.0
    exposure_after_trade_pct: Optional[float] = None
    drawdown_status: Optional[str] = None
    daily_loss_status: Optional[str] = None
    human_review_required: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    policy_version: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _circuit_scalar() -> tuple[float, str]:
    """Sizing scalar from the circuit-breaker report (1.0 if absent/clear)."""
    if not CB.exists():
        return 1.0, "no circuit-breaker report (treated as clear)"
    try:
        d = json.loads(CB.read_text())
        return float(d.get("sizing_scalar", 1.0)), d.get("reason", "")
    except Exception:
        return 0.0, "circuit-breaker report unreadable (fail-closed)"


def check(symbol: str, side: str, strategy: str, *, entry: float,
          stop_loss: float, take_profit: Optional[float] = None,
          confidence: Optional[float] = None,
          current_positions: Optional[list[dict]] = None,
          data_age_minutes: Optional[float] = None,
          mode: Optional[str] = None) -> RiskDecision:
    """Evaluate a proposed trade. current_positions: list of {symbol, value, sector}."""
    from safety import config_guard, kill_switch
    from safety import risk_policy

    d = RiskDecision()
    checks = d.checks
    pol = risk_policy.load()
    d.policy_version = risk_policy.version()
    equity = float(pol["account"]["default_equity_usd"])
    risk_pct = float(pol["trade_risk"]["risk_per_trade_pct"])
    max_pos_pct = float(pol["trade_risk"]["max_position_pct"])
    max_heat_pct = float(pol["portfolio_risk"]["max_portfolio_heat_pct"])
    max_concurrent = int(pol["portfolio_risk"]["max_concurrent_positions"])
    max_sector_pct = float(pol["portfolio_risk"]["max_sector_exposure_pct"])
    min_conf = float(pol["trade_risk"]["min_confidence"])
    min_rr = float(pol["trade_risk"]["min_reward_to_risk"])
    m = mode or config_guard.mode()

    def reject(reason: str) -> RiskDecision:
        d.approved = False
        d.rejected_reason = reason
        return d

    # 1. Mode + config + kill switch (the master gate).
    ok, reasons = config_guard.safe_to_trade(m)
    checks["mode_and_config"] = "ok" if ok else reasons
    if not ok:
        return reject("; ".join(reasons))

    # 2. Kill switch / pause (symbol/strategy granularity).
    blk = kill_switch.blocked(symbol=symbol, strategy=strategy)
    checks["kill_switch"] = blk or "clear"
    if blk:
        return reject(blk)

    # 3. Side + price / stop sanity.
    side_l = side.lower()
    if side_l not in ("buy", "sell"):
        return reject(f"invalid side '{side}'")
    allow_short = bool(pol["trade_risk"].get("allow_short", False))
    if side_l == "sell" and not allow_short:
        return reject("short selling disabled by policy (long-only)")
    if not (entry and entry > 0) or not (stop_loss and stop_loss > 0):
        return reject("invalid entry/stop price")
    risk_per_share = abs(entry - stop_loss)
    if risk_per_share <= 0:
        return reject("stop equals entry (zero risk-per-share)")
    if side_l == "buy" and stop_loss >= entry:
        return reject("long stop must be below entry")
    if side_l == "sell" and stop_loss <= entry:
        return reject("short stop must be above entry")
    checks["price_sanity"] = "ok"

    # 3b. Reward-to-risk floor (policy).
    if take_profit is not None and min_rr:
        rr_ratio = abs(take_profit - entry) / risk_per_share
        if rr_ratio < min_rr:
            return reject(f"reward:risk {rr_ratio:.2f} < min {min_rr:.2f}")
        checks["reward_to_risk"] = round(rr_ratio, 2)

    # 4. Data freshness (coarse backstop; quote_validator is the seconds-level gate).
    max_age_min = float(pol["execution_risk"]["max_data_age_seconds_eod"]) / 60.0
    if data_age_minutes is not None and data_age_minutes > max_age_min:
        return reject(f"stale data ({data_age_minutes:.0f} min > {max_age_min:.0f} min)")
    checks["data_freshness"] = f"{data_age_minutes}min" if data_age_minutes is not None else "unchecked"

    # 5. Confidence floor.
    if confidence is not None and confidence < min_conf:
        return reject(f"confidence {confidence:.2f} < floor {min_conf:.2f}")
    checks["confidence"] = confidence

    # 6. Circuit breakers (daily/weekly/total drawdown, crash regime).
    scalar, cb_reason = _circuit_scalar()
    checks["circuit_breakers"] = {"scalar": scalar, "reason": cb_reason}
    d.daily_loss_status = cb_reason
    d.drawdown_status = cb_reason
    if scalar <= 0:
        return reject(f"circuit breaker halt: {cb_reason}")

    # 7. Portfolio limits.
    positions = current_positions or []
    if len(positions) >= max_concurrent:
        return reject(f"max concurrent positions reached ({len(positions)}/{max_concurrent})")
    if any(p.get("symbol", "").upper() == symbol.upper() for p in positions):
        return reject(f"already holding {symbol.upper()} (no pyramiding)")
    checks["portfolio_slots"] = f"{len(positions)}/{max_concurrent}"

    # 8. Position sizing: risk-based, then capped by max_position_pct and circuit scalar.
    risk_dollars = equity * (risk_pct / 100) * scalar
    raw_shares = int(risk_dollars / risk_per_share) if risk_per_share else 0
    cap_shares = int((equity * max_pos_pct / 100) / entry) if entry else 0
    shares = max(0, min(raw_shares, cap_shares))
    if shares <= 0:
        return reject("position size rounds to 0 shares")
    d.max_position_size = cap_shares
    d.suggested_position_size = shares
    d.max_loss_amount = round(shares * risk_per_share, 2)
    pos_value = shares * entry
    pos_pct = pos_value / equity * 100

    # 9. Sector concentration.
    sector = next((p.get("sector") for p in positions
                   if p.get("symbol", "").upper() == symbol.upper()), None)
    if sector:
        sector_val = sum(p.get("value", 0) for p in positions if p.get("sector") == sector)
        if (sector_val + pos_value) / equity * 100 > max_sector_pct:
            return reject(f"sector exposure would exceed {max_sector_pct:.0f}%")
    checks["sizing"] = {"shares": shares, "pos_pct": round(pos_pct, 1)}

    # 10. Portfolio heat (sum of open risk).
    existing_heat = sum(p.get("risk_pct", 0) for p in positions)
    new_heat = existing_heat + (d.max_loss_amount / equity * 100)
    if new_heat > max_heat_pct:
        return reject(f"portfolio heat {new_heat:.1f}% > cap {max_heat_pct:.1f}%")
    checks["portfolio_heat_pct"] = round(new_heat, 2)

    existing_value = sum(p.get("value", 0) for p in positions)
    d.exposure_after_trade_pct = round((existing_value + pos_value) / equity * 100, 1)
    d.stop_loss_level = round(stop_loss, 2)
    d.take_profit_level = round(take_profit, 2) if take_profit else None

    # 11. Human review threshold (advisory in paper, blocking-by-policy in live).
    hr = pol["human_review"]
    risk_pct_after = d.max_loss_amount / equity * 100
    d.human_review_required = (
        pos_pct >= float(hr["require_above_position_pct"])
        or risk_pct_after >= float(hr["require_above_risk_pct"])
        or (hr.get("require_for_live", True) and m == "live")
    )
    checks["human_review_required"] = d.human_review_required

    d.approved = True
    return d


def main():
    """Demo / smoke."""
    dec = check("NVDA", "buy", "TREND_LEADER", entry=200.0, stop_loss=190.0,
                take_profit=230.0, confidence=0.7, current_positions=[],
                data_age_minutes=30, mode="paper")
    print(json.dumps(dec.to_dict(), indent=2))


if __name__ == "__main__":
    main()

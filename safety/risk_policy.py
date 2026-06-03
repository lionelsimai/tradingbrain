#!/usr/bin/env python3
"""Canonical risk policy — the ONLY active risk source.

Loads config/risk_policy.yaml, validates schema + bounds, computes a stable
policy version hash, exposes typed accessors, and detects conflicts with the
legacy session.yaml / sources.yaml risk values (which must be passive).

CLI: python3 -m safety.risk_policy   (prints version + validation + conflicts)
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

try:
    from paths import CONFIG_DIR, REPORTS_DIR
except Exception:  # pragma: no cover - fallback if run oddly
    CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
    REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"

POLICY_FILE = CONFIG_DIR / "risk_policy.yaml"

_REQUIRED = {
    "environment": ["default_mode", "allowed_modes", "live_trading_enabled",
                    "require_explicit_live_flag", "require_human_approval_for_live",
                    "fail_closed_on_unknown"],
    "account": ["default_equity_usd", "currency"],
    "trade_risk": ["risk_per_trade_pct", "max_risk_per_trade_pct", "max_position_pct",
                   "min_reward_to_risk", "min_confidence", "allow_pyramiding"],
    "portfolio_risk": ["max_portfolio_heat_pct", "max_concurrent_positions",
                       "max_sector_exposure_pct", "max_correlated_exposure_pct",
                       "max_daily_loss_pct", "max_weekly_loss_pct",
                       "max_total_drawdown_pct", "stop_after_loss_streak"],
    "execution_risk": ["require_stop_loss", "max_spread_bps", "min_avg_dollar_volume",
                       "max_data_age_seconds_intraday", "require_market_open_for_entry"],
    "scorecard_policy": ["unknown_setup_policy", "unknown_setup_size_cap",
                         "replay_not_allowed_for_live_gate",
                         "paper_not_allowed_for_live_gate"],
    "human_review": ["require_above_position_pct", "require_above_risk_pct",
                     "require_for_live"],
    "kill_switch": ["enabled", "fail_closed_if_missing", "fail_closed_if_unreadable"],
}

_cache: dict | None = None


class PolicyError(ValueError):
    """Raised when the policy is missing, malformed, or internally inconsistent."""


def load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    if not POLICY_FILE.exists():
        raise PolicyError(f"Canonical risk policy missing: {POLICY_FILE}")
    data = yaml.safe_load(POLICY_FILE.read_text())
    _validate(data)
    data["_version"] = version()
    _cache = data
    return data


def _validate(d: dict) -> None:
    for section, keys in _REQUIRED.items():
        if section not in d:
            raise PolicyError(f"risk_policy.yaml missing section [{section}]")
        for k in keys:
            if k not in d[section]:
                raise PolicyError(f"risk_policy.yaml [{section}] missing key '{k}'")
    tr = d["trade_risk"]
    if not (0 < tr["risk_per_trade_pct"] <= tr["max_risk_per_trade_pct"]):
        raise PolicyError("risk_per_trade_pct must be >0 and <= max_risk_per_trade_pct")
    if not (0 < tr["max_position_pct"] <= 100):
        raise PolicyError("max_position_pct out of bounds")
    if not (0 <= tr["min_confidence"] <= 1):
        raise PolicyError("min_confidence must be in [0,1]")
    pr = d["portfolio_risk"]
    if pr["max_concurrent_positions"] < 1:
        raise PolicyError("max_concurrent_positions must be >= 1")
    if d["environment"]["default_mode"] not in d["environment"]["allowed_modes"]:
        raise PolicyError("default_mode not in allowed_modes")


def version() -> str:
    raw = POLICY_FILE.read_text().encode()
    return "rp_" + hashlib.sha256(raw).hexdigest()[:12]


def get(section: str, key: str, default: Any = None) -> Any:
    return load().get(section, {}).get(key, default)


def conflicts() -> list[str]:
    """Detect ACTIVE legacy risk values that disagree with the canonical policy.
    Legacy files may keep values for reference, but if a loop still reads them and
    they disagree, that is a policy conflict the operator must resolve."""
    out = []
    p = load()
    legacy = {}
    for fn in ("session.yaml", "sources.yaml"):
        fp = CONFIG_DIR / fn
        if fp.exists():
            try:
                legacy[fn] = yaml.safe_load(fp.read_text()) or {}
            except Exception:
                out.append(f"{fn}: unparseable")
    # Compare a few high-stakes values that historically lived in session.yaml
    sess = legacy.get("session.yaml", {})
    checks = [
        ("max_position_pct", sess.get("max_position_pct"), p["trade_risk"]["max_position_pct"]),
        ("max_portfolio_heat_pct", sess.get("max_portfolio_heat_pct"),
         p["portfolio_risk"]["max_portfolio_heat_pct"]),
        ("max_concurrent_positions", sess.get("max_concurrent_positions"),
         p["portfolio_risk"]["max_concurrent_positions"]),
    ]
    for name, legacy_v, canon_v in checks:
        if legacy_v is not None and float(legacy_v) != float(canon_v):
            out.append(
                f"session.yaml {name}={legacy_v} conflicts with canonical {name}={canon_v}")
    return out


def live_prerequisites(env: dict) -> list[str]:
    """Reasons live trading must NOT proceed. Empty list = prerequisites met
    (still requires the operator's explicit action elsewhere)."""
    p = load()["environment"]
    reasons = []
    if not p["live_trading_enabled"]:
        reasons.append("policy: live_trading_enabled=false")
    if p["require_explicit_live_flag"] and env.get("TB_ALLOW_LIVE") != "1":
        reasons.append("env: TB_ALLOW_LIVE!=1")
    if env.get("TB_MODE") != "live":
        reasons.append("env: TB_MODE!=live")
    if p["require_human_approval_for_live"] and env.get("TB_HUMAN_APPROVED") != "1":
        reasons.append("env: TB_HUMAN_APPROVED!=1")
    return reasons


def report() -> dict:
    r = {
        "policy_file": str(POLICY_FILE),
        "version": version(),
        "valid": True,
        "conflicts": [],
        "error": None,
    }
    try:
        load()
        r["conflicts"] = conflicts()
        r["valid"] = not r["conflicts"]
    except PolicyError as e:
        r["valid"] = False
        r["error"] = str(e)
    (REPORTS_DIR / "risk-policy-report.json").write_text(json.dumps(r, indent=2))
    return r


if __name__ == "__main__":
    r = report()
    print(json.dumps(r, indent=2))

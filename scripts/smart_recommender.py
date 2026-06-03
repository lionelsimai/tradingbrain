#!/usr/bin/env python3
"""TradingBrain — Smart Recommender (Adaptive Intelligence overlay).

A composable layer on top of scripts/recommend.py. It reuses the base engine's
candidate loading, six-pillar scoring and defined-risk plan building UNCHANGED,
then enriches each pick with the Adaptive Intelligence Core:

  * regime-adaptive pillar tilts (lean into trend in a stable bull, fade momentum
    and sentiment in a bear),
  * uncertainty-aware conviction (cross-pillar disagreement lowers the score),
  * outcome calibration (Bayesian shrinkage over the REAL track record; the
    reliability curve auto-activates once a forward-paper ledger exists),
  * a position-size THROTTLE (<= 1.0) that can only reduce risk.

It changes nothing about safety: it does not execute, it preserves the honest
moderate cap (only LIVE evidence lifts it), and it never sizes UP. Research-only.

CLI:
  python3 -m scripts.smart_recommender              # enriched top picks + watch
  python3 -m scripts.smart_recommender --json       # raw structured output
  python3 -m scripts.smart_recommender --equity 50000 --top 5
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import recommend  # the honest base engine — reused, never mutated
from intelligence import (smart_core, conviction_calibration as cc,
                          outcomes as outcomes_mod, relative_strength as rs_mod)

ROOT = recommend.ROOT
REPORTS = ROOT / "reports"
CONFIG = recommend.CONFIG

DISCLAIMER = (
    "Research-only decision support, not financial advice or an instruction to trade. "
    "Adaptive intelligence refines the honest base engine; it never executes, never "
    "sizes up, and keeps conviction capped at moderate until a live track record exists."
)


def _atr_pct(c: dict) -> float | None:
    """Trailing volatility proxy for the size throttle. Prefers a real ATR field;
    falls back to the stop distance (~1.5*ATR for these setups). None => no vol
    adjustment (the throttle then leaves size unchanged on the volatility axis)."""
    entry = c.get("entry") or c.get("close")
    atr = c.get("atr") or c.get("atr14")
    try:
        if atr and entry:
            return float(atr) / float(entry) * 100.0
        stop = c.get("stop")
        if entry and stop and entry > stop:
            return (float(entry) - float(stop)) / float(entry) * 100.0 / 1.5
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return None


def recommend_smart(equity: float, top: int) -> dict:
    cands = recommend._json("swing-setups.json", {}).get("candidates", [])
    regime = recommend._json("hmm-regime.json", {})
    stress = recommend._json("stress-test.json", {})
    lib, memory = recommend._setup_history()
    x_sent = recommend._latest_x_sentiment()
    social = recommend._latest_social_sentiment()
    macro = recommend._macro_context()
    macro_penalty = recommend._macro_penalty(macro)
    risk_pct = float(recommend._find(recommend._yaml(CONFIG / "risk_policy.yaml"), "risk_per_trade_pct", 0.5) or 0.5)
    min_rr = float(recommend._find(recommend._yaml(CONFIG / "session.yaml"), "min_reward_risk", 2.0) or 2.0)
    max_heat = float(recommend._find(recommend._yaml(CONFIG / "risk_policy.yaml"), "max_portfolio_heat_pct", 6.0) or 6.0)
    live_n = recommend._live_trade_count()

    oc = outcomes_mod.load(REPORTS)
    calibrator = cc.load(REPORTS, outcomes=oc)

    # peer/sector relative strength (best-effort; empty => simply omitted)
    peer_rs_map = {}
    try:
        universe = recommend._yaml(CONFIG / "universe.yaml")
        sector_map = rs_mod.sector_map_from_universe(universe)
        cand_tickers = [str(c.get("ticker", "")).upper() for c in cands]
        peer_rs_map = rs_mod.compute_peer_rs(ROOT / "data" / "prices.duckdb",
                                             cand_tickers, sector_map)
    except Exception:
        peer_rs_map = {}
    vix = None
    try:
        vix = float((macro.get("vix") or macro.get("VIX")))
    except (TypeError, ValueError):
        vix = None

    picks, watch = [], []
    for c in cands:
        setup = c.get("setup", "")
        status = (lib.get(setup) or {}).get("status", "")
        reads, raw, missing = recommend.score_pillars(c, regime, lib, x_sent, social)
        if status == "Broken":
            watch.append({"ticker": c.get("ticker"), "setup": setup,
                          "why_not": f"{setup} marked BROKEN by research — excluded."})
            continue
        plan_res = recommend.build_plan(c, equity, risk_pct, min_rr)
        if plan_res is None:
            continue
        if isinstance(plan_res, tuple) and plan_res[0] is None:
            watch.append({"ticker": c.get("ticker"), "setup": setup,
                          "why_not": f"reward:risk {plan_res[1]:.2f} below minimum {min_rr}"})
            continue
        plan, rr = plan_res

        # base honesty path (unchanged), then intelligence enrichment
        base_adjusted = max(0, raw - macro_penalty)
        smart = smart_core.score_smart(
            c, regime, raw_score=base_adjusted, missing=missing,
            calibrator=calibrator, outcomes=oc, lib=lib,
            x_sentiment=x_sent, social_sentiment=social,
            live_n=live_n, atr_pct=_atr_pct(c), vix=vix,
            peer_rs=peer_rs_map.get(str(c.get("ticker", "")).upper()))

        # SAFE sizing: throttle can only reduce shares, never increase them.
        throttle = smart["size_throttle"]
        base_shares = plan["position_size"]["shares_or_units"]
        applied_shares = int(math.floor(base_shares * throttle))
        per_share_risk = (c.get("entry") or c.get("close", 0)) - plan["stop_loss"]
        applied_pct = round(plan["position_size"]["percent_of_equity"] * throttle, 3)

        if smart["smart_band"] in ("strong", "moderate") and applied_shares > 0:
            picks.append({
                "ticker": c.get("ticker"), "asset_class": "equity", "direction": "long",
                "conviction_score": smart["smart_conviction"], "conviction_band": smart["smart_band"],
                "base_conviction": smart["base_conviction"],
                "conviction_interval": smart["conviction_interval"],
                "p_win": smart["p_win"], "expected_R": smart["expected_R"],
                "evidence": f"{smart['evidence_n']} {smart['evidence_source']} trades",
                "time_horizon": "5-15 trading days",
                "entry_zone": plan["entry_zone"], "stop_loss": plan["stop_loss"],
                "targets": plan["targets"], "reward_to_risk": plan["reward_to_risk"],
                "position_size": {
                    "shares_or_units": applied_shares,
                    "percent_of_equity": applied_pct,
                    "dollar_risk": round(applied_shares * max(per_share_risk, 0), 2),
                    "base_shares": base_shares, "size_throttle": throttle,
                },
                "regime": smart["regime_profile"],
                "thesis": f"{setup}: {c.get('reason','')}.",
                "intelligence_notes": smart["intelligence_notes"],
                "invalidation": f"a close below the stop at {plan['stop_loss']}.",
                "pillar_agreement": smart["pillar_agreement"],
                "cap_active": smart["cap_active"],
            })
        else:
            watch.append({"ticker": c.get("ticker"), "setup": setup,
                          "why_not": f"smart conviction {smart['smart_conviction']} ({smart['smart_band']})",
                          "notes": smart["intelligence_notes"]})

    picks.sort(key=lambda r: (r["conviction_score"], r["reward_to_risk"]), reverse=True)
    chosen, heat = [], 0.0
    for r in picks:
        add = r["position_size"]["percent_of_equity"]
        if len(chosen) >= top or heat + add > max_heat:
            continue
        chosen.append(r)
        heat += add

    rlabel = regime.get("acted_label") or regime.get("raw_label") or "Unknown"
    return {
        "asof": datetime.now(timezone.utc).isoformat(),
        "engine": "smart_recommender (adaptive intelligence overlay)",
        "equity": equity, "live_trades_on_record": live_n,
        "conviction_cap_active": live_n == 0,
        "regime": {"label": rlabel, "stability": regime.get("stability"),
                   "target_exposure": regime.get("target_exposure")},
        "calibration": {
            "evidence": "live" if oc.live_n else ("replay" if oc.replay_n else "none"),
            "live_trades": oc.live_n, "replay_trades": oc.replay_n,
            "base_rate": round(oc.base_rate, 3),
            "reliability_curve_active": bool(calibrator.reliability_knots),
        },
        "picks": chosen,
        "watch_list": watch[:12],
        "open_heat_pct": round(heat, 2),
        "max_heat_pct": max_heat,
        "survivorship": recommend._survivorship(),
        "disclaimer": DISCLAIMER,
    }


def _render_md(rep: dict) -> str:
    L = ["# TradingBrain — Smart Picks (Adaptive Intelligence)", "",
         f"_As of {rep['asof']}_  ·  regime **{rep['regime']['label']}**  ·  "
         f"calibration evidence **{rep['calibration']['evidence']}** "
         f"({rep['calibration']['live_trades']} live / {rep['calibration']['replay_trades']} replay)", ""]
    if rep["conviction_cap_active"]:
        L.append(f"> Honest cap active: nothing rated above moderate until live trades exist.\n")
    if not rep["picks"]:
        L.append("**No qualifying setups** after intelligence screening.\n")
    for p in rep["picks"]:
        L += [f"## {p['ticker']} — {p['conviction_band'].upper()} ({p['conviction_score']})",
              f"- Conviction interval: {p['conviction_interval']}  ·  p(win) {p['p_win']:.0%}  ·  "
              f"exp {p['expected_R']:+.2f}R  ·  evidence: {p['evidence']}",
              f"- Entry {p['entry_zone']}  ·  stop {p['stop_loss']}  ·  R:R {p['reward_to_risk']}",
              f"- Size: {p['position_size']['shares_or_units']} sh "
              f"(throttle x{p['position_size']['size_throttle']}, from {p['position_size']['base_shares']})",
              "- " + "; ".join(p["intelligence_notes"]), ""]
    L += ["---", f"_{rep['disclaimer']}_"]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="TradingBrain adaptive-intelligence recommender (research-only).")
    ap.add_argument("--equity", type=float, default=None)
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--json", action="store_true", help="emit raw JSON only")
    args = ap.parse_args()

    equity = args.equity
    if equity is None:
        equity = float(recommend._find(recommend._yaml(CONFIG / "session.yaml"), "account_equity", 50000) or 50000)

    rep = recommend_smart(equity, args.top)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "smart-recommendations.json").write_text(json.dumps(rep, indent=2))
    md = _render_md(rep)
    (REPORTS / "smart-recommendations.md").write_text(md)
    print(json.dumps(rep, indent=2) if args.json else md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

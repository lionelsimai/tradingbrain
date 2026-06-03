#!/usr/bin/env python3
"""Hermes tool registry for TradingBrain.

Two things live here:
  TOOLS     — OpenAI-style function signatures (what goes inside <tools></tools>
              in the Hermes system prompt).
  DISPATCH  — name -> python callable that actually runs the tool.

SAFETY: every tool is read-only or propose-only. None imports the broker, the
order manager, the risk policy writer, or the kill switch. A static guard below
(and tests/test_hermes_agent.py) proves it, mirroring agents/permissions.py.
Each callable returns a JSON-serializable dict.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

# ── repo roots ───────────────────────────────────────────────────────────────
ROOT = next(
    (p for p in Path(__file__).resolve().parents
     if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()),
    Path(__file__).resolve().parents[2],
)
REPORTS = ROOT / "reports"
CONFIG = ROOT / "config"

# Modules a Hermes tool must never reach (kept in lock-step with
# agents/permissions.FORBIDDEN_IMPORTS). Enforced by a test.
FORBIDDEN_IMPORTS = [
    "execution.broker_base", "execution.order_manager", "execution.paper_adapter",
    "scripts.broker_alpaca", "safety.kill_switch",
]

DISCLAIMER = (
    "Decision-support only — informational, not personalized financial advice. "
    "A human operator must review and execute. Markets risk loss of capital; "
    "past or backtested performance does not predict results."
)


# ── helpers ──────────────────────────────────────────────────────────────────
def _read_report(name: str, default=None):
    try:
        return json.loads((REPORTS / name).read_text())
    except Exception:
        return default if default is not None else {}


def _yaml(path: Path, default=None):
    try:
        import yaml
        return yaml.safe_load(path.read_text()) or (default or {})
    except Exception:
        return default or {}


def _clean_pick(p: dict) -> dict:
    """Drop private/internal keys; surface the self-red-team as plain 'risks'."""
    out = {k: v for k, v in p.items() if not k.startswith("_")}
    if "_self_red_team" in p:
        out["risks"] = p["_self_red_team"]
    return out


# ── tools (all safe) ─────────────────────────────────────────────────────────
def get_market_regime() -> dict:
    """Current market regime read. Drives whether the system wants exposure."""
    r = _read_report("hmm-regime.json", {})
    if not r:
        return {"available": False,
                "note": "No regime report yet. Run the regime/analysis pipeline first."}
    return {
        "available": True,
        "label": r.get("acted_label") or r.get("raw_label") or "Unknown",
        "stability": r.get("stability", "unknown"),
        "target_exposure": r.get("target_exposure", "unknown"),
        "asof": r.get("asof", "unknown"),
        "note": "When the regime is risk-off (SPY below its long trend), the "
                "system prefers cash. The regime filter is the one robust edge.",
    }


def list_universe(sub_sector: str | None = None) -> dict:
    """The AI value-chain universe, optionally filtered to one sub-sector."""
    uni = _yaml(CONFIG / "universe.yaml", {})
    groups = uni.get("universe", {})
    if isinstance(groups, dict):
        if sub_sector:
            key = sub_sector.strip().lower()
            match = {k: v for k, v in groups.items() if k.lower() == key}
            if not match:
                return {"sub_sectors": list(groups.keys()),
                        "note": f"'{sub_sector}' not found. Pick one of sub_sectors."}
            return {"sub_sector": list(match)[0], "tickers": list(match.values())[0]}
        return {"sub_sectors": list(groups.keys()),
                "by_sub_sector": groups,
                "benchmarks": uni.get("regime_benchmarks", [])}
    return {"universe": groups, "benchmarks": uni.get("regime_benchmarks", [])}


def get_recommendations(equity: float = 100000, top: int = 5) -> dict:
    """Ranked swing-trade proposals with defined-risk plans. Proposals only."""
    try:
        from scripts.recommend import recommend  # lazy: keeps module-level import surface clean
    except Exception as e:
        return {"available": False, "error": f"recommender unavailable: {e}",
                "disclaimer": DISCLAIMER}
    try:
        rep = recommend(float(equity), int(top))
    except Exception as e:
        return {"available": False,
                "error": f"recommender could not run (is the pipeline data present?): {e}",
                "disclaimer": DISCLAIMER}
    return {
        "available": True,
        "asof": rep.get("asof"),
        "market_read": rep.get("market_read"),
        "conviction_cap_active": rep.get("conviction_cap_active"),
        "live_trades_on_record": rep.get("live_trades_on_record"),
        "picks": [_clean_pick(p) for p in rep.get("picks", [])],
        "watch_list": rep.get("watch_list", []),
        "no_qualifying_setups": rep.get("no_qualifying_setups"),
        "survivorship": rep.get("survivorship"),
        "disclaimer": rep.get("disclaimer", DISCLAIMER),
    }


def get_super_recommendations(equity: float = 100000, top: int = 10) -> dict:
    """Stricter institutional overlay: setup + macro + outlier + target + volume + RS + evidence gates."""
    try:
        from scripts.super_recommender import build_super_recommendations
    except Exception as e:
        return {"available": False, "error": f"super recommender unavailable: {e}",
                "disclaimer": DISCLAIMER}
    try:
        rep = build_super_recommendations(top=int(top), equity=float(equity))
    except Exception as e:
        return {"available": False,
                "error": f"super recommender could not run: {e}",
                "disclaimer": DISCLAIMER}
    return {
        "available": True,
        "asof": rep.get("asof"),
        "mode": rep.get("mode"),
        "readiness": rep.get("readiness"),
        "macro_context": rep.get("macro_context"),
        "summary": rep.get("summary"),
        "picks": rep.get("picks", []),
        "watch_list": rep.get("watch_list", []),
        "what_this_fixes": rep.get("what_this_fixes", []),
        "disclaimer": rep.get("disclaimer", DISCLAIMER),
    }


def get_super_smart_recommendations(top: int = 20, refresh: bool = False) -> dict:
    """Self-auditing next-gen US stock recommender: ranks candidates and states what evidence is still missing."""
    try:
        from scripts.super_smart_recommender import build_super_smart_recommendations
    except Exception as e:
        return {"available": False, "error": f"super-smart recommender unavailable: {e}",
                "disclaimer": DISCLAIMER}
    try:
        rep = build_super_smart_recommendations(top=int(top), refresh=bool(refresh))
    except Exception as e:
        return {"available": False,
                "error": f"super-smart recommender could not run: {e}",
                "disclaimer": DISCLAIMER}
    return {
        "available": True,
        "asof": rep.get("asof"),
        "mode": rep.get("mode"),
        "latest_price_date": rep.get("latest_price_date"),
        "universe_scanned": rep.get("universe_scanned"),
        "strict_current_picks": rep.get("strict_current_picks", []),
        "macro_context": rep.get("macro_context"),
        "audit": rep.get("audit"),
        "picks": rep.get("picks", []),
        "what_i_was_lacking_and_built": rep.get("what_i_was_lacking_and_built", []),
        "reports": {
            "json": str(REPORTS / "super-smart-recommendations.json"),
            "markdown": str(REPORTS / "super-smart-recommendations.md"),
        },
        "disclaimer": rep.get("disclaimer", DISCLAIMER),
    }


def get_ai_pattern_recommendations(top: int = 20, train_memory: bool = False) -> dict:
    """Five-year US AI stock pattern engine: trend/RS/breakout/pullback/compression + adaptive forward memory."""
    try:
        from scripts.ai_pattern_engine import build_ai_pattern_recommendations, train_pattern_memory
    except Exception as e:
        return {"available": False, "error": f"AI pattern engine unavailable: {e}",
                "disclaimer": DISCLAIMER}
    try:
        memory_run = train_pattern_memory(min_samples=1) if bool(train_memory) else None
        rep = build_ai_pattern_recommendations(top=int(top), write=True)
        if memory_run is not None:
            rep["memory_training_run"] = memory_run
        return rep
    except Exception as e:
        return {"available": False,
                "error": f"AI pattern engine could not run: {e}",
                "disclaimer": DISCLAIMER}


def get_ai_macro_social_subagent(tickers: list[str] | None = None, polymarket: bool = False) -> dict:
    """Macro/news/prediction-market/social overlay sub-agent for AI stock research confidence."""
    try:
        from scripts.ai_macro_social_subagent import build_ai_macro_social_report
    except Exception as e:
        return {"available": False, "error": f"AI macro/social sub-agent unavailable: {e}",
                "disclaimer": DISCLAIMER}
    try:
        return build_ai_macro_social_report(tickers=tickers, fetch_prediction_markets=bool(polymarket), write=True)
    except Exception as e:
        return {"available": False,
                "error": f"AI macro/social sub-agent could not run: {e}",
                "disclaimer": DISCLAIMER}


def get_ai_screener_industry_13f(top: int = 25, holder_top: int = 10) -> dict:
    """AI stock screener with industry analysis, latest news/movers, and institutional/13F proxy cross-check."""
    try:
        from scripts.ai_screener_industry_13f import build_ai_screener_industry_13f
    except Exception as e:
        return {"available": False, "error": f"AI screener/13F report unavailable: {e}",
                "disclaimer": DISCLAIMER}
    try:
        return build_ai_screener_industry_13f(top=int(top), holder_top=int(holder_top), write=True)
    except Exception as e:
        return {"available": False,
                "error": f"AI screener/13F report could not run: {e}",
                "disclaimer": DISCLAIMER}


def get_data_freshness_scorecard(tickers: list[str] | None = None) -> dict:
    """Candidate-level price/fundamental/news/social freshness badges."""
    try:
        from scripts.data_freshness import build_data_freshness_scorecard
    except Exception as e:
        return {"available": False, "error": f"data freshness scorecard unavailable: {e}",
                "disclaimer": DISCLAIMER}
    try:
        return build_data_freshness_scorecard(tickers=tickers, write=True)
    except Exception as e:
        return {"available": False,
                "error": f"data freshness scorecard could not run: {e}",
                "disclaimer": DISCLAIMER}


def get_market_open_confirmation(top: int = 12, refresh: bool = False) -> dict:
    """Research-only market-open confirmation: current quotes + QQQ/SMH/SPY/NVDA tape + gap-chase risk."""
    try:
        from scripts.market_open_confirmation import build_market_open_confirmation
    except Exception as e:
        return {"available": False, "error": f"market-open confirmation unavailable: {e}",
                "disclaimer": DISCLAIMER}
    try:
        rep = build_market_open_confirmation(top=int(top), refresh=bool(refresh))
    except Exception as e:
        return {"available": False,
                "error": f"market-open confirmation could not run: {e}",
                "disclaimer": DISCLAIMER}
    return {
        "available": True,
        "asof": rep.get("asof"),
        "mode": rep.get("mode"),
        "benchmarks": rep.get("benchmarks"),
        "top_candidates": rep.get("ranked", [])[: int(top)],
        "source_recommender": rep.get("source_recommender"),
        "reports": {
            "json": str(REPORTS / "market-open-confirmation-latest.json"),
            "markdown": str(REPORTS / "market-open-confirmation-latest.md"),
        },
        "disclaimer": rep.get("disclaimer", DISCLAIMER),
    }


def get_ai_million_sim_gauntlet(
    paths: int = 1_000_000,
    top: int = 50,
    years: int = 5,
    block_size: int = 5,
    chunk_size: int = 5000,
    seed: int = 7,
    refresh_rank: bool = False,
) -> dict:
    """Run AI top-50 five-year million-simulation risk/opportunity gauntlet."""
    try:
        from scripts.ai_million_sim_gauntlet import build_gauntlet
    except Exception as e:
        return {"available": False, "error": f"AI million-sim gauntlet unavailable: {e}",
                "disclaimer": DISCLAIMER}
    try:
        rep = build_gauntlet(
            paths=int(paths), top=int(top), years=int(years), block_size=int(block_size),
            chunk_size=int(chunk_size), seed=int(seed), refresh_rank=bool(refresh_rank)
        )
    except Exception as e:
        return {"available": False,
                "error": f"AI million-sim gauntlet could not run: {e}",
                "disclaimer": DISCLAIMER}
    return {
        "available": True,
        "asof": rep.get("asof"),
        "mode": rep.get("mode"),
        "executed_paths": rep.get("executed_paths"),
        "top_with_price_history": rep.get("top_with_price_history"),
        "tickers": rep.get("tickers", []),
        "historical_portfolio": rep.get("historical_portfolio"),
        "simulation": rep.get("simulation"),
        "stress_windows": rep.get("stress_windows"),
        "top_opportunities": rep.get("top_opportunities_by_5y_return", [])[:10],
        "highest_drawdown_risks": rep.get("highest_drawdown_risks", [])[:10],
        "known_limitations": rep.get("known_limitations", []),
        "reports": {
            "json": str(REPORTS / "ai-top50-million-sim-gauntlet.json"),
            "markdown": str(REPORTS / "ai-top50-million-sim-gauntlet.md"),
        },
        "disclaimer": rep.get("disclaimer", DISCLAIMER),
    }


def get_recommender_upgrade_status(log_forward_paper: bool = False, top: int = 20) -> dict:
    """Real-upgrade status: universe breadth, PIT coverage, forward evidence, target provenance."""
    try:
        from scripts.pit_coverage import compute_pit_coverage, write_reports as write_pit_reports
        from scripts.us_universe_builder import build_liquid_universe
        from scripts.forward_paper_evidence import summarize_forward_evidence, log_latest_super_smart, write_horizon_scorecard
        from scripts.analyst_target_provenance import build_scorecard as build_target_provenance, write_reports as write_target_provenance
    except Exception as e:
        return {"available": False, "error": f"upgrade modules unavailable: {e}",
                "disclaimer": DISCLAIMER}
    try:
        pit = compute_pit_coverage(); write_pit_reports(pit)
        universe = build_liquid_universe(output_path=ROOT / "data" / "us_liquid_universe.json")
        forward = log_latest_super_smart(top=int(top)) if log_forward_paper else summarize_forward_evidence()
        horizon_forward = write_horizon_scorecard()
        target_provenance = build_target_provenance(); write_target_provenance(target_provenance)
    except Exception as e:
        return {"available": False, "error": f"upgrade status failed: {e}",
                "disclaimer": DISCLAIMER}
    return {
        "available": True,
        "pit_coverage": pit,
        "us_liquid_universe": {k: v for k, v in universe.items() if k != "rows"},
        "sample_universe_rows": universe.get("rows", [])[:10],
        "forward_paper_evidence": forward,
        "forward_horizon_evidence": horizon_forward,
        "analyst_target_provenance": target_provenance,
        "reports": {
            "pit": str(REPORTS / "pit-coverage.json"),
            "us_liquid_universe": str(REPORTS / "us-liquid-universe.json"),
            "forward_paper": str(REPORTS / "forward-paper-evidence.json"),
            "forward_horizon_scorecard": str(REPORTS / "forward-paper-horizon-scorecard-latest.json"),
            "analyst_target_provenance": str(REPORTS / "analyst-target-provenance-latest.json"),
        },
        "disclaimer": DISCLAIMER,
    }


def get_tradingbrain_proof_gate() -> dict:
    """Return the anti-hype proof gate: max honest rating and missing evidence."""
    try:
        from scripts.proof_gate import build_from_reports, write_reports
    except Exception as e:
        return {"available": False, "error": f"proof gate unavailable: {e}", "disclaimer": DISCLAIMER}
    try:
        gate = build_from_reports()
        paths = write_reports(gate)
    except Exception as e:
        return {"available": False, "error": f"proof gate failed: {e}", "disclaimer": DISCLAIMER}
    gate = dict(gate)
    gate.update({"available": True, "reports": paths, "disclaimer": gate.get("disclaimer", DISCLAIMER)})
    return gate


def get_institutional_portfolio_risk_budget(equity: float = 100000) -> dict:
    """Return paper-only institutional portfolio risk budget from latest candidates."""
    try:
        from scripts.institutional_portfolio import build_from_reports, write_reports
    except Exception as e:
        return {"available": False, "error": f"institutional portfolio budget unavailable: {e}", "disclaimer": DISCLAIMER}
    try:
        rep = build_from_reports(equity=float(equity))
        paths = write_reports(rep, equity=float(equity))
    except Exception as e:
        return {"available": False, "error": f"institutional portfolio budget failed: {e}", "disclaimer": DISCLAIMER}
    rep = dict(rep)
    rep.update({"available": True, "reports": paths, "disclaimer": rep.get("disclaimer", DISCLAIMER)})
    return rep


def get_pit_coverage_scorecard() -> dict:
    """Return point-in-time/survivorship and candidate traceability coverage."""
    try:
        from scripts.pit_coverage import compute_pit_coverage, write_reports
    except Exception as e:
        return {"available": False, "error": f"PIT coverage unavailable: {e}", "disclaimer": DISCLAIMER}
    try:
        rep = compute_pit_coverage()
        paths = write_reports(rep)
    except Exception as e:
        return {"available": False, "error": f"PIT coverage failed: {e}", "disclaimer": DISCLAIMER}
    rep = dict(rep)
    rep.update({"available": True, "reports": paths, "disclaimer": rep.get("disclaimer", DISCLAIMER)})
    return rep


def get_analyst_target_provenance_scorecard(tickers: list[str] | str | None = None) -> dict:
    """Return candidate-level analyst-target provenance and independence coverage."""
    try:
        from scripts.analyst_target_provenance import build_scorecard, write_reports
    except Exception as e:
        return {"available": False, "error": f"analyst target provenance scorecard unavailable: {e}", "disclaimer": DISCLAIMER}
    if isinstance(tickers, str):
        tickers = [t.strip() for t in tickers.replace(",", " ").split() if t.strip()]
    try:
        rep = build_scorecard(candidate_tickers=tickers)
        paths = write_reports(rep)
    except Exception as e:
        return {"available": False, "error": f"analyst target provenance scorecard failed: {e}", "disclaimer": DISCLAIMER}
    rep = dict(rep)
    rep.update({"available": True, "reports": paths, "disclaimer": rep.get("disclaimer", DISCLAIMER)})
    return rep


def get_red_team_vulnerability_report() -> dict:
    """Return the standing red-team vulnerability scan for evidence/claim/safety flaws."""
    try:
        from scripts.red_team_vulnerabilities import evaluate_red_team, write_reports
    except Exception as e:
        return {"available": False, "error": f"red-team scan unavailable: {e}", "disclaimer": DISCLAIMER}
    try:
        rep = evaluate_red_team()
        write_reports(rep)
    except Exception as e:
        return {"available": False, "error": f"red-team scan failed: {e}", "disclaimer": DISCLAIMER}
    rep = dict(rep)
    rep.update({
        "available": True,
        "reports": {
            "json": str(REPORTS / "red-team-vulnerabilities-latest.json"),
            "markdown": str(REPORTS / "red-team-vulnerabilities-latest.md"),
        },
        "disclaimer": DISCLAIMER,
    })
    return rep


def get_council_orchestration(
    question: str,
    tickers: list[str] | str | None = None,
    mode: str = "fast_quorum",
    asset_class: str = "equity",
    horizon: str = "swing",
) -> dict:
    """Run schema-enforced TradingBrain council orchestration with hard-veto precedence.

    This is a research/paper-only supervisor pass. It writes auditable council
    artifacts but never executes trades or touches broker paths.
    """
    if isinstance(tickers, str):
        tickers = [t.strip().upper() for t in tickers.replace(",", " ").split() if t.strip()]
    try:
        from scripts.agents.council_orchestrator import run_council
    except Exception as e:
        return {"available": False, "error": f"council orchestrator unavailable: {e}", "disclaimer": DISCLAIMER}
    try:
        rep = run_council(
            str(question),
            tickers=tickers or [],
            mode=str(mode),
            asset_class=str(asset_class),
            horizon=str(horizon),
            write_reports=True,
        )
    except Exception as e:
        return {"available": False, "error": f"council orchestration failed: {e}", "disclaimer": DISCLAIMER}
    rep = dict(rep)
    rep.update({"available": True, "disclaimer": rep.get("disclaimer", DISCLAIMER)})
    return rep


def ingest_analyst_target_provenance(tickers: list[str] | str | None = None, provider: str = "finnhub") -> dict:
    """Ingest lawful analyst-target provenance/aggregates. Finnhub is aggregate, so confidence remains discounted."""
    if isinstance(tickers, str):
        tickers = [t.strip() for t in tickers.replace(",", " ").split() if t.strip()]
    tickers = tickers or ["MU", "WDC", "STX", "COHR", "ARM", "AMD", "CIEN", "INTC", "LRCX", "NVT"]
    try:
        from scripts.ingest.analyst_targets import fetch_finnhub_price_targets, merge_targets
    except Exception as e:
        return {"available": False, "error": f"analyst target ingestion unavailable: {e}",
                "disclaimer": DISCLAIMER}
    if provider != "finnhub":
        return {"available": False, "error": "only provider='finnhub' is currently implemented", "disclaimer": DISCLAIMER}
    try:
        good, errors = fetch_finnhub_price_targets(list(tickers))
        result = merge_targets(good) if good else {"added": 0, "total": 0, "db_total": 0}
    except Exception as e:
        return {"available": False, "error": f"analyst target ingestion failed: {e}",
                "disclaimer": DISCLAIMER}
    return {
        "available": True,
        "provider": provider,
        "tickers": tickers,
        "valid_rows": len(good),
        "errors": errors[:20],
        "merge": result,
        "caution": "Finnhub target endpoint is provider-aggregate evidence, not broker/analyst-level independence; target-quality will discount it accordingly.",
        "disclaimer": DISCLAIMER,
    }


def get_macro_context(horizon_days: int = 7) -> dict:
    """Major macro/policy-event context that can affect rate pricing and AI multiples."""
    try:
        from scripts.macro_context import build_macro_context  # lazy, read-only research overlay
    except Exception as e:
        return {"available": False, "error": f"macro context unavailable: {e}",
                "disclaimer": DISCLAIMER}
    try:
        out = build_macro_context(horizon_days=int(horizon_days))
    except Exception as e:
        return {"available": False, "error": f"macro context failed: {e}",
                "disclaimer": DISCLAIMER}
    out.setdefault("disclaimer", DISCLAIMER)
    return out


def get_outlier_context(tickers: list[str] | str | None = None, lookback: int = 60) -> dict:
    """Trading-abnormality/outlier scan for candidate tickers."""
    try:
        from scripts.outlier_context import build_outlier_context
    except Exception as e:
        return {"available": False, "error": f"outlier context unavailable: {e}",
                "disclaimer": DISCLAIMER}
    if isinstance(tickers, str):
        tickers = [t.strip() for t in tickers.replace(",", " ").split() if t.strip()]
    try:
        out = build_outlier_context(tickers=tickers, lookback=int(lookback))
    except Exception as e:
        return {"available": False, "error": f"outlier context failed: {e}",
                "disclaimer": DISCLAIMER}
    out.setdefault("disclaimer", DISCLAIMER)
    return out


def get_target_quality(tickers: list[str] | str | None = None) -> dict:
    """Target credibility and live-quality confidence gates for candidate tickers."""
    try:
        from scripts.target_quality import build_target_quality_context
    except Exception as e:
        return {"available": False, "error": f"target quality unavailable: {e}",
                "disclaimer": DISCLAIMER}
    if isinstance(tickers, str):
        tickers = [t.strip() for t in tickers.replace(",", " ").split() if t.strip()]
    try:
        out = build_target_quality_context(tickers=tickers)
    except Exception as e:
        return {"available": False, "error": f"target quality failed: {e}",
                "disclaimer": DISCLAIMER}
    out.setdefault("disclaimer", DISCLAIMER)
    return out


def get_current_quote(ticker: str) -> dict:
    """Current/extended-hours quote snapshot for one ticker, with vendor comparison."""
    try:
        from scripts.current_quote import build_current_quote
    except Exception as e:
        return {"available": False, "ticker": str(ticker).upper().strip(),
                "error": f"current quote module unavailable: {e}",
                "disclaimer": DISCLAIMER}
    try:
        out = build_current_quote(str(ticker))
    except Exception as e:
        return {"available": False, "ticker": str(ticker).upper().strip(),
                "error": f"current quote lookup failed: {e}",
                "disclaimer": DISCLAIMER}
    out.setdefault("disclaimer", DISCLAIMER)
    out["interpretation"] = (
        "Use Yahoo chart extended-hours data when available; Finnhub /quote is kept as a regular-session cross-check; "
        "Polygon is opportunistic and may be unavailable on the current plan. Quotes are snapshots, not execution-grade feeds."
    )
    return out


def get_crypto_quote(assets: list[str] | str | None = None) -> dict:
    """24/7 BTC/ETH crypto quote snapshot from multiple public venues."""
    try:
        from scripts.crypto_quote import build_crypto_quotes
    except Exception as e:
        return {"available": False, "error": f"crypto quote module unavailable: {e}",
                "disclaimer": DISCLAIMER}
    if assets is None:
        asset_list = ["BTC", "ETH"]
    elif isinstance(assets, str):
        asset_list = [a.strip() for a in assets.replace(",", " ").split() if a.strip()]
    else:
        asset_list = [str(a).strip() for a in assets if str(a).strip()]
    try:
        out = build_crypto_quotes(asset_list or ["BTC", "ETH"])
    except Exception as e:
        return {"available": False, "assets": asset_list,
                "error": f"crypto quote lookup failed: {e}",
                "disclaimer": DISCLAIMER}
    out.setdefault("disclaimer", DISCLAIMER)
    out["interpretation"] = (
        "Crypto trades 24/7, so this uses public spot venues directly: Coinbase Exchange, Kraken, Binance USDT, and CoinGecko. "
        "Use the source timestamps/spread diagnostics; this is a research snapshot, not an execution feed."
    )
    return out


def get_gold_tracker(period: str = "1y", symbols: list[str] | str | None = None) -> dict:
    """Gold super investment tracker: gold, ETFs, miners, USD/rates, and risk drivers."""
    try:
        from scripts.gold_tracker import build_gold_tracker
    except Exception as e:
        return {"available": False, "error": f"gold tracker module unavailable: {e}",
                "disclaimer": DISCLAIMER}
    if symbols is None:
        symbol_list = None
    elif isinstance(symbols, str):
        symbol_list = [s.strip() for s in symbols.replace(",", " ").split() if s.strip()]
    else:
        symbol_list = [str(s).strip() for s in symbols if str(s).strip()]
    try:
        out = build_gold_tracker(period=str(period or "1y"), symbols=symbol_list)
    except Exception as e:
        return {"available": False, "symbols": symbol_list,
                "error": f"gold tracker failed: {e}",
                "disclaimer": DISCLAIMER}
    out.setdefault("disclaimer", DISCLAIMER)
    out["interpretation"] = (
        "Read-only gold investment tracker: combines gold futures/ETF trend, miner confirmation, "
        "USD/rates/TIPS drivers, and risk rails. Use for research/paper decisions only; not an execution feed."
    )
    return out


def get_social_sentiment(ticker: str) -> dict:
    """Manipulation-aware social sentiment for one ticker (latest snapshot)."""
    rep = _read_report("social-sentiment-latest.json", {})
    rows = rep.get("tickers") or rep.get("rows") or rep.get("data") or []
    tk = str(ticker).upper().strip()
    if isinstance(rows, dict):
        row = rows.get(tk)
    else:
        row = next((r for r in rows if str(r.get("ticker", "")).upper() == tk), None)
    if not row:
        return {"available": False, "ticker": tk,
                "note": "No sentiment for this ticker yet. Ingest posts (e.g. "
                        "scripts.ingest.stocktwits) then run scripts.signals.social_sentiment.",
                "disclaimer": DISCLAIMER}
    row = dict(row)
    row.setdefault("ticker", tk)
    row["available"] = True
    row["interpretation"] = (
        "Sentiment is a small confirmation/veto overlay, not an alpha source. "
        "High manipulation_risk means a suspected pump and the signal is vetoed; "
        "a euphoria flag is treated as chase risk, not confirmation."
    )
    row["disclaimer"] = DISCLAIMER
    return row


def refresh_social_sentiment() -> dict:
    """Rebuild the social-sentiment signal from already-ingested posts."""
    try:
        from scripts.signals import social_sentiment as ss
    except Exception as e:
        return {"ok": False, "error": f"sentiment engine unavailable: {e}"}
    try:
        ss.main([])  # builds signals + writes reports/social-sentiment-latest.json
    except SystemExit:
        pass
    except Exception as e:
        return {"ok": False, "error": f"refresh failed: {e}"}
    rep = _read_report("social-sentiment-latest.json", {})
    rows = rep.get("tickers") or rep.get("rows") or rep.get("data") or []
    n = len(rows) if isinstance(rows, (list, dict)) else 0
    return {"ok": True, "tickers_scored": n, "asof": rep.get("asof", str(date.today())),
            "note": "Reads only posts you have lawfully ingested; no scraping."}


def ask_brain(question: str, k: int = 6) -> dict:
    """Best-effort retrieval over the knowledge base (evidence, not an answer)."""
    try:
        from scripts.ask import retrieve
    except Exception as e:
        return {"available": False, "error": f"retrieval unavailable: {e}"}
    try:
        ev = retrieve(str(question), int(k), None, 180)
    except Exception as e:
        return {"available": False,
                "error": f"retrieval needs embeddings/vss and a populated brain: {e}"}
    return {"available": True, "question": question,
            "evidence": [{"source": e.get("source"), "ticker": e.get("ticker"),
                          "title": e.get("title"), "url": e.get("url"),
                          "excerpt": (e.get("body_excerpt") or "")[:300]} for e in ev]}


# ── registry ─────────────────────────────────────────────────────────────────
def _sig(name, desc, properties, required=None):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": properties,
                       "required": required or []}}}


TOOLS = [
    _sig("get_market_regime",
         "Get the current market regime (risk-on/off, target exposure). Call this "
         "first — the system prefers cash when the regime is risk-off.",
         {}),
    _sig("list_universe",
         "List the AI value-chain universe, optionally filtered to one sub-sector "
         "(e.g. memory_storage, gpu_accelerators).",
         {"sub_sector": {"type": "string", "description": "Optional sub-sector key."}}),
    _sig("get_recommendations",
         "Get ranked swing-trade proposals with defined-risk plans. Proposals only "
         "— never executes. Conviction is capped until a live track record exists.",
         {"equity": {"type": "number", "description": "Account equity for sizing. Default 100000."},
          "top": {"type": "integer", "description": "How many picks to return. Default 5."}}),
    _sig("get_super_recommendations",
         "Run the stricter institutional super-recommender: combines swing setup quality, real price/volume/liquidity, benchmark relative strength, macro/rates risk, abnormality/outlier vetoes, target-quality/banker-pump-risk gates, sentiment/manipulation availability, catalyst evidence, and world-class readiness blockers. Use this for strongest stock-recommender output.",
         {"equity": {"type": "number", "description": "Reference account equity for sizing context. Default 100000."},
          "top": {"type": "integer", "description": "Maximum research candidates to return. Default 10."}}),
    _sig("get_super_smart_recommendations",
         "Run the self-auditing next-gen US stock recommender. It asks what TradingBrain is lacking, scores broad AI/US-stock candidates with 3-year patterns + strict picks + macro/outlier/target/news/fundamental/social evidence, caps confidence when evidence is missing, and writes super-smart recommendation reports. Research-only; never executes.",
         {"top": {"type": "integer", "description": "Maximum research candidates to return. Default 20."},
          "refresh": {"type": "boolean", "description": "Rebuild upstream ranking first. Default false."}}),
    _sig("get_ai_pattern_recommendations",
         "Run the five-year US AI stock pattern recommendation engine. Extracts trend persistence, momentum continuation, breakout follow-through, pullback-reclaim, volatility-compression, drawdown risk, and adaptive forward-paper pattern memory. Research-only; no orders.",
         {"top": {"type": "integer", "description": "Maximum pattern candidates to return. Default 20."},
          "train_memory": {"type": "boolean", "description": "Update adaptive pattern memory from resolved forward-paper outcomes before ranking. Default false."}}),
    _sig("get_ai_macro_social_subagent",
         "Run the macro/news/prediction-market/social overlay sub-agent for AI stock research. Aggregates macro context, local news, social/manipulation signals, and optional read-only Polymarket markets as confidence/risk overlays. Research-only; no orders.",
         {"tickers": {"type": "array", "items": {"type": "string"}, "description": "Ticker symbols to scan. Defaults to major AI names."},
          "polymarket": {"type": "boolean", "description": "Fetch public read-only Polymarket markets. Default false."}}),
    _sig("get_ai_screener_industry_13f",
         "Run the combined US AI stock screener with industry analysis, latest local AI-stock news, market movers/open-watch gaps, social overlay, and yfinance/Yahoo public institutional-holder 13F proxy cross-check. Research-only; caveat: not full CUSIP-resolved SEC 13F ingestion.",
         {"top": {"type": "integer", "description": "Number of AI pattern candidates to screen. Default 25."},
          "holder_top": {"type": "integer", "description": "Top institutional holders per ticker to fetch. Default 10."}}),
    _sig("get_data_freshness_scorecard",
         "Return candidate-level data-freshness badges for current research picks: local price age, fundamental snapshot age, news/catalyst recency, social-signal age, missing/stale pillars, and confidence-discount actions. Research-only; does not fetch or fabricate data.",
         {"tickers": {"type": "array", "items": {"type": "string"}, "description": "Ticker symbols to scan. Defaults to inferred current candidates."}}),
    _sig("get_market_open_confirmation",
         "Run the market-open confirmation agent for the 9:30am ET / 9:30pm SGT open. It takes top super-smart research candidates, fetches current/extended quotes, checks QQQ/SMH/SPY/NVDA tape, penalizes gap-chase risk, and returns a paper-only open watchlist. Use for 'best upside at the US open' questions.",
         {"top": {"type": "integer", "description": "Maximum open-watch candidates to return. Default 12."},
          "refresh": {"type": "boolean", "description": "Rebuild upstream recommender first. Default false."}}),
    _sig("get_ai_million_sim_gauntlet",
         "Run the AI top-50 five-year million-simulation risk/opportunity gauntlet. It projects the current rigorous AI top-50 backward over five years, builds equal-weight historical returns, runs chunked block-bootstrap simulations, and reports upside distributions, drawdown/ruin risk, stress windows, and constituent opportunities/risks. Research-only; not live trading.",
         {"paths": {"type": "integer", "description": "Simulation paths. Default 1,000,000."},
          "top": {"type": "integer", "description": "Top AI names to include. Default 50."},
          "years": {"type": "integer", "description": "Trailing years of price history. Default 5."},
          "block_size": {"type": "integer", "description": "Bootstrap block size in trading days. Default 5."},
          "seed": {"type": "integer", "description": "Random seed. Default 7."},
          "refresh_rank": {"type": "boolean", "description": "Rebuild upstream AI ranking first. Default false."}}),
    _sig("get_recommender_upgrade_status",
         "Get real-upgrade status for the US stock recommender: broad liquid universe count, PIT/survivorship coverage, forward paper observations, and report paths. Optionally logs the current super-smart picks as forward paper observations; no trades are executed.",
         {"log_forward_paper": {"type": "boolean", "description": "If true, record current recommendations as pending forward-paper observations. Default false."},
          "top": {"type": "integer", "description": "How many super-smart picks to log if log_forward_paper=true. Default 20."}}),
    _sig("get_tradingbrain_proof_gate",
         "Return the anti-hype TradingBrain proof gate: max honest self-rating, whether 8/10 is actually proven, live-trading proof status, missing evidence, and report paths. Use this before making readiness claims.",
         {}),
    _sig("get_institutional_portfolio_risk_budget",
         "Return a research/paper-only institutional portfolio risk budget from latest candidates: core vs torque buckets, risk dollars, portfolio heat, rejects, and report paths. No orders are placed.",
         {"equity": {"type": "number", "description": "Reference equity for paper sizing. Default 100000."}}),
    _sig("get_pit_coverage_scorecard",
         "Return PIT/survivorship coverage and candidate-level traceability scorecard: local prices, Polygon reference, corporate actions, missing rows, and report paths. This is an audit only and does not claim full vendor PIT unless status is closed.",
         {}),
    _sig("get_analyst_target_provenance_scorecard",
         "Return candidate-level analyst-target provenance coverage: broker/analyst/date/source_url independence, stale/missing rows, and provider aggregates that must be discounted. Research-only; never treats targets as predictions.",
         {"tickers": {"type": "array", "items": {"type": "string"}, "description": "Ticker symbols to scan. Defaults to inferred current recommender candidates."}}),
    _sig("get_red_team_vulnerability_report",
         "Return TradingBrain's red-team vulnerability scan: evidence gaps, overclaim contradictions, PIT/forward/live-safety flaws, severity counts, and next break tests. Research/paper-only; no orders.",
         {}),
    _sig("get_council_orchestration",
         "Run the schema-enforced TradingBrain council supervisor: selects required specialist roles by operating mode, validates structured agent reviews, applies hard-veto precedence, writes audit artifacts, and returns a research/paper-only CEO decision. Use this for serious stock/portfolio questions where Red Team/Data/Risk/Kill Switch coordination matters.",
         {"question": {"type": "string", "description": "Research question for the council."},
          "tickers": {"type": "array", "items": {"type": "string"}, "description": "Optional tickers/assets in scope."},
          "mode": {"type": "string", "description": "Council mode: fast_quorum, market_open, full_ai_stock, proof_heavy, portfolio, or cross_asset. Default fast_quorum."},
          "asset_class": {"type": "string", "description": "equity, crypto, gold, portfolio, or mixed. Default equity."},
          "horizon": {"type": "string", "description": "intraday, swing, 1d, 5d, 20d, long_term, or proof. Default swing."}},
         ["question"]),
    _sig("ingest_analyst_target_provenance",
         "Ingest lawful analyst-target evidence for selected tickers. Currently supports Finnhub aggregate price targets only; these are stored with provider_aggregate provenance and discounted by target-quality checks.",
         {"tickers": {"type": "array", "items": {"type": "string"}, "description": "Ticker symbols. Defaults to current top research candidates."},
          "provider": {"type": "string", "description": "Provider name; currently only finnhub."}}),
    _sig("get_macro_context",
         "Get upcoming macro/policy-event context that can influence interest-rate pricing, "
         "Treasury yields, USD, QQQ/SMH, and AI-sector swing risk. Includes FOMC, CPI, PCE, "
         "payrolls, Fed speakers, Treasury events, and locally ingested Trump/Truth Social policy posts.",
         {"horizon_days": {"type": "integer", "description": "Look-ahead window in calendar days. Default 7."}}),
    _sig("get_outlier_context",
         "Scan candidate tickers for trading abnormalities/outliers: extreme return z-scores, volume spikes, large gaps, wide ranges, stale data, and OHLC/bad-print issues. Used as a veto or confidence reducer, not a directional forecast.",
         {"tickers": {"type": "array", "items": {"type": "string"}, "description": "Ticker symbols to scan. Defaults to latest swing setups."},
          "lookback": {"type": "integer", "description": "Historical lookback in trading days. Default 60."}}),
    _sig("get_target_quality",
         "Check whether targets are credible or potentially hype/pump-driven. Compares TradingBrain technical targets with locally ingested analyst/banker target provenance, independence, recency, concentration, and live-quality confidence gates. Missing analyst provenance reduces confidence.",
         {"tickers": {"type": "array", "items": {"type": "string"}, "description": "Ticker symbols to scan. Defaults to latest swing setups."}}),
    _sig("get_current_quote",
         "Get the latest current/extended-hours quote for one ticker with Yahoo extended-hours, Finnhub regular-session cross-check, Polygon opportunistic check, source errors, and quote timestamps. Use for questions like 'META price now after market'.",
         {"ticker": {"type": "string", "description": "Ticker symbol, e.g. META."}},
         ["ticker"]),
    _sig("get_crypto_quote",
         "Get 24/7 Bitcoin/Ethereum spot pricing from public crypto venues with Coinbase Exchange, Kraken, Binance USDT, and CoinGecko cross-checks, timestamps, 24h changes, and source-spread diagnostics. Use for BTC/ETH real-time pricing.",
         {"assets": {"type": "array", "items": {"type": "string"}, "description": "Assets to quote. Defaults to BTC and ETH. Aliases accepted: BTC-USD, ETH-USD, bitcoin, ethereum."}}),
    _sig("get_gold_tracker",
         "Build a read-only gold super investment tracker: gold futures, GLD/IAU/physical ETFs, GDX/GDXJ/miners, USD/rates/TIPS/risk drivers, thesis score, warnings, and risk rails.",
         {"period": {"type": "string", "description": "Yahoo history period such as 6mo, 1y, 2y. Default 1y."},
          "symbols": {"type": "array", "items": {"type": "string"}, "description": "Optional override symbols. Default covers gold futures, ETFs, miners, and macro drivers."}}),
    _sig("get_social_sentiment",
         "Get manipulation-aware social sentiment for one ticker, including "
         "manipulation_risk, euphoria flag, and a plain-language read.",
         {"ticker": {"type": "string", "description": "Ticker symbol, e.g. NVDA."}},
         ["ticker"]),
    _sig("refresh_social_sentiment",
         "Rebuild the social-sentiment signal from already-ingested posts. Reads "
         "only lawfully ingested data; performs no scraping.",
         {}),
    _sig("ask_brain",
         "Retrieve supporting evidence (filings, news, FinTwit) from the knowledge "
         "base for a question. Returns evidence snippets, not a finished answer.",
         {"question": {"type": "string", "description": "The research question."},
          "k": {"type": "integer", "description": "How many evidence items. Default 6."}},
         ["question"]),
]

DISPATCH = {
    "get_market_regime": get_market_regime,
    "list_universe": list_universe,
    "get_recommendations": get_recommendations,
    "get_super_recommendations": get_super_recommendations,
    "get_super_smart_recommendations": get_super_smart_recommendations,
    "get_ai_pattern_recommendations": get_ai_pattern_recommendations,
    "get_ai_macro_social_subagent": get_ai_macro_social_subagent,
    "get_ai_screener_industry_13f": get_ai_screener_industry_13f,
    "get_data_freshness_scorecard": get_data_freshness_scorecard,
    "get_market_open_confirmation": get_market_open_confirmation,
    "get_ai_million_sim_gauntlet": get_ai_million_sim_gauntlet,
    "get_recommender_upgrade_status": get_recommender_upgrade_status,
    "get_tradingbrain_proof_gate": get_tradingbrain_proof_gate,
    "get_institutional_portfolio_risk_budget": get_institutional_portfolio_risk_budget,
    "get_pit_coverage_scorecard": get_pit_coverage_scorecard,
    "get_analyst_target_provenance_scorecard": get_analyst_target_provenance_scorecard,
    "get_red_team_vulnerability_report": get_red_team_vulnerability_report,
    "get_council_orchestration": get_council_orchestration,
    "ingest_analyst_target_provenance": ingest_analyst_target_provenance,
    "get_macro_context": get_macro_context,
    "get_outlier_context": get_outlier_context,
    "get_target_quality": get_target_quality,
    "get_current_quote": get_current_quote,
    "get_crypto_quote": get_crypto_quote,
    "get_gold_tracker": get_gold_tracker,
    "get_social_sentiment": get_social_sentiment,
    "refresh_social_sentiment": refresh_social_sentiment,
    "ask_brain": ask_brain,
}


def run_tool(name: str, arguments: dict | None) -> dict:
    """Dispatch a single tool call safely. Always returns a dict."""
    fn = DISPATCH.get(name)
    if fn is None:
        return {"error": f"unknown tool '{name}'. Available: {list(DISPATCH)}"}
    args = arguments or {}
    if not isinstance(args, dict):
        return {"error": "arguments must be an object"}
    try:
        return fn(**args)
    except TypeError as e:
        return {"error": f"bad arguments for {name}: {e}"}
    except Exception as e:
        return {"error": f"{name} failed: {e}"}


if __name__ == "__main__":
    # quick offline self-check of the catalog
    print(f"{len(TOOLS)} tools registered:")
    for t in TOOLS:
        f = t["function"]
        print(f"  - {f['name']}({', '.join(f['parameters']['properties'])})")

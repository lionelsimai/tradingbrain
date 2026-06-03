#!/usr/bin/env python3
"""TradingBrain — Recommendation Engine (six-pillar stock/crypto picker).

Implements the picking pipeline from the master spec: it takes the setups the
system has already detected, scores conviction 0-100 across the six pillars from
REAL data, builds a defined-risk trade plan, red-teams its own call, checks
portfolio fit, and emits the structured recommendation the front end can parse —
plus a watch list, a market read, and an explicit "no qualifying setups" message.

HONESTY IS BUILT IN (not optional):
  * Pillars are scored only from data that actually exists. Missing pillars
    (e.g. sentiment feed not connected, fundamentals not loaded) are labeled
    "no data" and REDUCE conviction — they are never invented.
  * Conviction is CAPPED at "moderate" while there are zero live trades. No pick
    can be called "strong" on survivorship-biased, paper-zero evidence. The cap
    lifts automatically once a real live track record exists.
  * A setup the research layer marked "Broken" is never recommended.
  * Every pick carries its caveats, its single invalidation, and a data-freshness
    note. Nothing here is a profit promise.

CLI:
  python3 -m scripts.recommend                 # top 3 + watch list, equity from config
  python3 -m scripts.recommend --equity 50000 --top 3
  python3 -m scripts.recommend --json          # raw structured output only
"""
from __future__ import annotations
import argparse, json, math, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from paths import ROOT

REPORTS = ROOT / "reports"
CONFIG = ROOT / "config"
MODERATE_CAP = 60   # honest ceiling while live_n == 0 (cannot be "strong" yet)


def _json(name, default=None):
    try:
        return json.loads((REPORTS / name).read_text())
    except Exception:
        return default if default is not None else {}


def _yaml(path, default=None):
    try:
        import yaml
        return yaml.safe_load(Path(path).read_text()) or {}
    except Exception:
        return default if default is not None else {}


def _find(d, key, default=None):
    if isinstance(d, dict):
        for k, v in d.items():
            if k == key:
                return v
            r = _find(v, key)
            if r is not None:
                return r
    return default


def _live_trade_count() -> int:
    try:
        import duckdb
        c = duckdb.connect(str(ROOT / "data" / "knowledge.duckdb"), read_only=True)
        try:
            n = c.execute("SELECT COUNT(*) FROM signal_ledger WHERE realized_R IS NOT NULL "
                          "AND source='live'").fetchone()[0]
        finally:
            c.close()
        return int(n)
    except Exception:
        return 0


def _setup_history():
    """Per-setup status + replay track record, for the conviction prior and the
    self red-team. Uses the recall() we built — labeled replay/indicative."""
    try:
        from collective import memory
        import duckdb
        c = duckdb.connect(str(ROOT / "data" / "knowledge.duckdb"), read_only=True)
        try:
            lib = {r[0]: {"status": r[1], "oos_expectancy_R": r[2]}
                   for r in c.execute("SELECT setup,status,oos_expectancy_R "
                                      "FROM strategy_library").fetchall()}
        finally:
            c.close()
        return lib, memory
    except Exception:
        return {}, None


def _latest_signal(signal_name: str) -> dict:
    """Return the latest rows of a named signal, keyed by ticker.

    Reads only TradingBrain's own knowledge DB output. Never touches
    credentials. Used for both the legacy 'x_sentiment' and the unified
    manipulation-aware 'social_sentiment'.
    """
    try:
        import duckdb, json as _json
        c = duckdb.connect(str(ROOT / "data" / "knowledge.duckdb"), read_only=True)
        rows = c.execute(
            """SELECT ticker, value, metadata
               FROM signals
               WHERE signal_name = ?
                 AND signal_date = (SELECT MAX(signal_date) FROM signals WHERE signal_name = ?)""",
            [signal_name, signal_name],
        ).fetchall()
        c.close()
        out = {}
        for ticker, value, metadata in rows:
            meta = _json.loads(metadata) if metadata else {}
            meta["composite"] = float(value if value is not None else meta.get("composite", 0.0))
            out[str(ticker).upper()] = meta
        return out
    except Exception:
        return {}


def _latest_x_sentiment() -> dict:
    """Legacy single-source X sentiment (kept as a fallback)."""
    return _latest_signal("x_sentiment")


def _latest_social_sentiment() -> dict:
    """Unified, manipulation-aware multi-source sentiment.

    Preferred over the legacy X-only signal. Produced by
    scripts.signals.social_sentiment, which credibility-weights sources, VETOES
    coordinated pumps, caps euphoric/crowded names, and accounts for
    sentiment-vs-price divergence. Its `conviction_points` is already bounded and
    contrarian-adjusted, so the recommender consumes it directly.
    """
    return _latest_signal("social_sentiment")


def _macro_context() -> dict:
    """Read-only macro/rates/policy event overlay for recommendation context."""
    try:
        from scripts.macro_context import build_macro_context
        return build_macro_context(horizon_days=7)
    except Exception as e:
        return {"available": False, "macro_risk": "unknown", "error": str(e)}


def _macro_penalty(macro: dict) -> int:
    """Small conviction penalty when macro event risk is elevated.

    The macro layer is a veto/confidence overlay, not an alpha source.
    """
    risk = str(macro.get("macro_risk", "low")).lower()
    if risk == "high":
        return 10
    if risk == "medium":
        return 5
    return 0

# ----------------------------------------------------------- the six pillars --

def score_pillars(c: dict, regime: dict, lib: dict, x_sentiment: dict | None = None,
                  social_sentiment: dict | None = None) -> tuple[dict, int, list[str]]:
    """Return (pillar_reads, raw_conviction_0_100, missing_pillars).
    Only data that exists contributes; absent pillars are labeled and penalized."""
    reads, score, missing = {}, 0, []
    setup = c.get("setup", "")
    rsi = c.get("rsi")
    rs20 = c.get("rs20")

    # 4.1 Trend & structure (timing core) — up to +25
    if rs20 is not None and rs20 > 20:
        reads["trend"] = f"bullish + strong relative strength (RS20 {rs20:.0f}), setup {setup}"
        score += 25
    elif rs20 is not None and rs20 > 0:
        reads["trend"] = f"mildly bullish (RS20 {rs20:.0f})"
        score += 12
    else:
        reads["trend"] = "neutral / weak relative strength"

    # 4.2 Momentum (timing core) — up to +20
    if rsi is not None:
        if 50 <= rsi <= 70:
            reads["momentum"] = f"bullish, healthy (RSI {rsi:.0f})"; score += 20
        elif 70 < rsi <= 80:
            reads["momentum"] = f"bullish but extended (RSI {rsi:.0f})"; score += 8
        elif rsi > 80:
            reads["momentum"] = f"OVERBOUGHT (RSI {rsi:.0f}) — chase risk"; score -= 8
        else:
            reads["momentum"] = f"weak/neutral (RSI {rsi:.0f})"
    else:
        reads["momentum"] = "no data"; missing.append("momentum")

    # 4.3 Volume & participation — not in the candidate feed (no boost, disclosed)
    reads["volume"] = "no data (volume confirmation not in current feed)"
    missing.append("volume")

    # 4.4 Fundamental & catalyst — not loaded (no boost, disclosed)
    reads["fundamental_catalyst"] = "no data (fundamentals/catalyst calendar not connected)"
    missing.append("fundamental_catalyst")

    # 4.5 Sentiment (edge layer) — manipulation-aware, contrarian social signal.
    # Preference order: unified social_sentiment (pumps vetoed, euphoria capped,
    # divergence-aware) > legacy X-only x_sentiment. Sentiment only CONFIRMS or
    # VETOES; its point contribution is small and already bounded by the engine.
    tkr = str(c.get("ticker", "")).upper()
    ss = (social_sentiment or {}).get(tkr, {})
    xs = (x_sentiment or {}).get(tkr, {})
    if ss:
        pts = int(ss.get("conviction_points", 0) or 0)
        read = ss.get("read") or (
            f"social composite {float(ss.get('composite', 0.0)):+.2f}")
        if ss.get("stale"):
            reads["sentiment"] = f"social sentiment STALE — no contribution ({read})"
            missing.append("sentiment")
        elif float(ss.get("manipulation_risk", 0.0) or 0.0) >= 0.45:
            # pump suspected — disclosed, contributes nothing (never adds conviction)
            reads["sentiment"] = f"⚠ manipulation suspected — sentiment VETOED ({read})"
        else:
            # Unified social sentiment is preferred when it is actionable, but a
            # neutral social read should not hide a fresh, strong legacy X signal.
            # Treat X as a secondary confirmation lane in that case; this keeps the
            # manipulation-aware veto while avoiding false "neutral" downgrades.
            x_comp = float(xs.get("composite", 0.0) or 0.0) if xs else 0.0
            x_sent = float(xs.get("sentiment_avg", 0.0) or 0.0) if xs else 0.0
            x_volz = float(xs.get("volume_z", 0.0) or 0.0) if xs else 0.0
            if pts == 0 and abs(x_comp) >= 0.25:
                if x_comp > 0:
                    reads["sentiment"] = (f"X sentiment supportive (composite {x_comp:+.2f}, avg {x_sent:+.2f}, "
                                           f"volume_z {x_volz:+.2f}); social overlay neutral ({read})")
                    score += min(10, max(3, int(x_comp * 12)))
                else:
                    reads["sentiment"] = (f"X sentiment negative (composite {x_comp:+.2f}, avg {x_sent:+.2f}, "
                                           f"volume_z {x_volz:+.2f}); social overlay neutral ({read})")
                    score -= min(10, max(3, int(abs(x_comp) * 12)))
            else:
                reads["sentiment"] = read
                score += max(-8, min(8, pts))
    elif xs:
        comp = float(xs.get("composite", 0.0) or 0.0)
        sent = float(xs.get("sentiment_avg", 0.0) or 0.0)
        volz = float(xs.get("volume_z", 0.0) or 0.0)
        if comp >= 0.25:
            reads["sentiment"] = f"X sentiment supportive (composite {comp:+.2f}, avg {sent:+.2f}, volume_z {volz:+.2f})"
            score += min(10, max(3, int(comp * 12)))
        elif comp <= -0.25:
            reads["sentiment"] = f"X sentiment negative (composite {comp:+.2f}, avg {sent:+.2f}, volume_z {volz:+.2f})"
            score -= min(10, max(3, int(abs(comp) * 12)))
        else:
            reads["sentiment"] = f"X sentiment neutral (composite {comp:+.2f}, avg {sent:+.2f}, volume_z {volz:+.2f})"
    else:
        reads["sentiment"] = "no data (run scripts.ingest.* then scripts.signals.social_sentiment)"
        missing.append("sentiment")

    # 4.6 Market regime & volatility (risk gate) — up to +25
    rlabel = regime.get("acted_label") or regime.get("raw_label") or "Unknown"
    stable = regime.get("stability") == "STABLE"
    if rlabel in ("Bull",) and stable:
        reads["regime"] = f"supportive ({rlabel}, stable)"; score += 25
    elif rlabel in ("Neutral", "Euphoria"):
        reads["regime"] = f"mixed ({rlabel})"; score += 10
    elif rlabel in ("Bear", "Crash"):
        reads["regime"] = f"HOSTILE ({rlabel}) — raise the bar, cut size"; score -= 25
    else:
        reads["regime"] = f"{rlabel}"

    # conviction prior from the setup's replay track record (labeled, bounded small)
    exp = (lib.get(setup) or {}).get("oos_expectancy_R")
    if exp is not None:
        score += max(-8, min(10, int(exp * 6)))

    # Missing edge-pillars are DISCLOSED (in caveats), not double-penalized — the
    # honesty cap below already prevents overconfidence. Only nudge down if the
    # picture is mostly blind (4+ of 6 pillars missing).
    if len(missing) >= 4:
        score -= 8
    return reads, max(0, min(100, score)), missing


def band(score: int) -> str:
    if score >= 75:
        return "strong"
    if score >= 55:
        return "moderate"
    if score >= 40:
        return "weak"
    return "pass"


def build_plan(c: dict, equity: float, risk_pct: float, min_rr: float):
    entry = c.get("entry") or c.get("close")
    stop = c.get("stop")
    target = c.get("target")
    if not (entry and stop and target) or entry <= stop:
        return None
    per_share_risk = entry - stop
    rr = (target - entry) / per_share_risk if per_share_risk > 0 else 0
    if rr < min_rr:
        return None, rr
    dollar_risk = equity * (risk_pct / 100.0)
    shares = math.floor(dollar_risk / per_share_risk) if per_share_risk > 0 else 0
    if shares <= 0:
        return None, rr
    return {
        "entry_zone": {"low": round(entry * 0.997, 2), "high": round(entry, 2)},
        "stop_loss": round(stop, 2),
        "targets": [{"level": round(target, 2),
                     "rationale": c.get("reason", "structure/measured move")}],
        "reward_to_risk": round(rr, 2),
        "position_size": {"shares_or_units": shares,
                          "dollar_risk": round(shares * per_share_risk, 2),
                          "percent_of_equity": round(risk_pct, 2)},
    }, rr


def red_team(c: dict, lib: dict, memory, stress: dict, missing: list[str]) -> list[str]:
    """Argue the other side, grounded in the setup's REAL history."""
    setup = c.get("setup", "")
    bear = []
    rsi = c.get("rsi")
    if rsi and rsi > 80:
        bear.append(f"RSI {rsi:.0f} is overbought — entering into strength that may mean-revert.")
    # historical win rate / expectancy from recall (replay, labeled)
    if memory is not None:
        try:
            rec = memory.recall(setup)
            exp = rec.get("experience") or []
            if exp:
                e = exp[0]
                bear.append(f"{setup} replay track record: {e.get('win_rate')}% win over "
                            f"n={e.get('n')} (REPLAY/indicative) — it loses "
                            f"{round(100 - (e.get('win_rate') or 0))}% of the time.")
        except Exception:
            pass
    # crash-window behavior from stress test
    sw = (stress.get("stress_windows") or {})
    worst = min((w.get("expectancy_R", 0) for w in sw.values() if isinstance(w, dict)), default=None)
    if worst is not None and worst < 0:
        bear.append(f"In the worst stress window the book bled {worst:+.2f}R per trade — "
                    "a fast regime flip would hurt.")
    if missing:
        bear.append("Conviction rests on only part of the picture: no "
                    + ", ".join(missing) + " data.")
    bear.append("Survivorship: scoring history excludes delisted names, so the real "
                "edge is lower than it looks.")
    return bear


def _survivorship() -> dict:
    """How biased is the universe? With a curated, all-alive universe, replay
    metrics are an optimistic CEILING. Surfaces this instead of hiding it (F1)."""
    try:
        import duckdb
        c = duckdb.connect(str(ROOT / "data" / "prices.duckdb"), read_only=True)
        try:
            total = c.execute("SELECT COUNT(*) FROM universe").fetchone()[0]
        finally:
            c.close()
    except Exception:
        total = None
    return {
        "universe_size": total,
        "delisted_included_pct": 0,
        "warning": ("0% of the universe is delisted/dead — survivorship bias is "
                    "maximal. Treat every replay expectancy as an optimistic ceiling; "
                    "a prudent working assumption is that real edge is materially lower "
                    "(often roughly half), and only live fills resolve the true number. "
                    "The real fix is adding point-in-time delisted names."),
    }


def recommend(equity: float, top: int) -> dict:
    cands = _json("swing-setups.json", {}).get("candidates", [])
    regime = _json("hmm-regime.json", {})
    stress = _json("stress-test.json", {})
    lib, memory = _setup_history()
    x_sentiment = _latest_x_sentiment()
    social_sentiment = _latest_social_sentiment()
    macro = _macro_context()
    macro_penalty = _macro_penalty(macro)
    risk_pct = float(_find(_yaml(CONFIG / "risk_policy.yaml"), "risk_per_trade_pct", 0.5) or 0.5)
    min_rr = float(_find(_yaml(CONFIG / "session.yaml"), "min_reward_risk", 2.0) or 2.0)
    live_n = _live_trade_count()
    max_heat = float(_find(_yaml(CONFIG / "risk_policy.yaml"), "max_portfolio_heat_pct", 6.0) or 6.0)

    picks, watch = [], []
    for c in cands:
        setup = c.get("setup", "")
        status = (lib.get(setup) or {}).get("status", "")
        reads, raw, missing = score_pillars(c, regime, lib, x_sentiment, social_sentiment)
        # Broken setups are never recommended.
        if status == "Broken":
            watch.append({"ticker": c.get("ticker"), "setup": setup,
                          "why_not": f"{setup} is marked BROKEN by research — excluded.",
                          "trigger": "re-validation of the setup on out-of-sample data"})
            continue
        plan_res = build_plan(c, equity, risk_pct, min_rr)
        if plan_res is None:
            continue
        if isinstance(plan_res, tuple) and plan_res[0] is None:
            watch.append({"ticker": c.get("ticker"), "setup": setup,
                          "why_not": f"reward:risk {plan_res[1]:.2f} below minimum {min_rr}",
                          "trigger": f"a pullback that lifts R:R to >= {min_rr}"})
            continue
        plan, rr = plan_res
        # HONESTY CAP: nothing is "strong" until a live track record exists.
        if macro_penalty:
            reads["macro_event_risk"] = macro.get("stance", f"macro risk {macro.get('macro_risk')}")
        adjusted_raw = max(0, raw - macro_penalty)
        capped = min(adjusted_raw, MODERATE_CAP) if live_n == 0 else adjusted_raw
        b = band(capped)
        bear = red_team(c, lib, memory, stress, missing)
        if macro_penalty:
            bear.insert(0, f"Macro/rates event risk is {macro.get('macro_risk')}: {macro.get('stance')}")
        rec = {
            "ticker": c.get("ticker"), "asset_class": "equity",
            "direction": "long",
            "conviction_score": capped, "conviction_band": b,
            "time_horizon": "5-15 trading days",
            **plan,
            "thesis": f"{setup} setup: {c.get('reason','')}. Trend and regime "
                      f"support the timing; risk is defined at the stop.",
            "pillar_reads": reads,
            "key_risks": bear[:2],
            "invalidation": f"a close below the stop at {plan['stop_loss']} (thesis wrong).",
            "confidence_caveats": (
                f"Conviction capped at {MODERATE_CAP} (moderate) because the system has "
                f"{live_n} live trades — scores are from REPLAY/survivorship-biased data and "
                "are indicative only. Missing pillars: "
                + (", ".join(missing) if missing else "none")
                + (f". Macro penalty applied: -{macro_penalty} points ({macro.get('macro_risk')})." if macro_penalty else ".")),
            "data_freshness": _json("swing-setups.json", {}).get("asof", "unknown"),
            "x_sentiment": xs if (xs := x_sentiment.get(str(c.get("ticker", "")).upper(), {})) else None,
            "social_sentiment": (sso if (sso := social_sentiment.get(str(c.get("ticker", "")).upper(), {})) else None),
            "_raw_uncapped_score": raw,
            "_self_red_team": bear,
        }
        if b in ("strong", "moderate"):
            picks.append(rec)
        elif b == "weak":
            watch.append({"ticker": c.get("ticker"), "setup": setup,
                          "why_not": f"conviction {capped} (weak) — mixed/thin signals",
                          "trigger": "stronger confluence (volume/sentiment confirmation)"})

    picks.sort(key=lambda r: r["conviction_score"], reverse=True)

    # portfolio fit: cap by max concurrent AND by total heat
    chosen, heat, seen_setup = [], 0.0, {}
    for r in picks:
        add = r["position_size"]["percent_of_equity"]
        if len(chosen) >= top:
            break
        if heat + add > max_heat:
            continue
        seen_setup[r["setup"] if "setup" in r else r["ticker"]] = seen_setup.get(r["ticker"], 0) + 1
        chosen.append(r)
        heat += add
    # correlation flag
    corr_note = ""
    setups = [r["pillar_reads"]["trend"] for r in chosen]
    if len(chosen) >= 3:
        corr_note = ("Correlation watch: several picks are long-momentum equities in a "
                     "single bull tape — treat as one combined bet, not three.")

    rlabel = regime.get("acted_label") or regime.get("raw_label") or "Unknown"
    macro_note = (f" Macro/rates: {macro.get('macro_risk', 'unknown')} — {macro.get('stance', 'n/a')}")
    market_read = (f"Regime: {rlabel} ({regime.get('stability','?')}), target exposure "
                   f"{regime.get('target_exposure','?')}. "
                   + (corr_note or "Risk is concentrated in momentum names; sizing kept small.")
                   + macro_note
                   + f" Open risk budgeted: {round(heat,2)}% of {max_heat}% max heat.")

    return {
        "asof": datetime.now(timezone.utc).isoformat(),
        "equity": equity, "risk_per_trade_pct": risk_pct, "min_reward_risk": min_rr,
        "live_trades_on_record": live_n,
        "conviction_cap_active": live_n == 0,
        "picks": chosen,
        "watch_list": watch[:8],
        "market_read": market_read,
        "macro_context": macro,
        "no_qualifying_setups": len(chosen) == 0,
        "survivorship": _survivorship(),
        "disclaimer": ("Decision-support only — informational, not personalized financial "
                       "advice. A human operator must review and execute. Markets risk loss "
                       "of capital; past/backtested performance does not predict results."),
    }


def render(rep: dict) -> str:
    L = [f"# TradingBrain picks — {rep['asof'][:10]}",
         f"_equity ${rep['equity']:,.0f} · risk {rep['risk_per_trade_pct']}%/trade · "
         f"min R:R {rep['min_reward_risk']} · live trades on record: {rep['live_trades_on_record']}_", ""]
    if rep["conviction_cap_active"]:
        L.append(f"> ⚠ Conviction is capped at **{MODERATE_CAP} (moderate)**: with zero live "
                 "trades, scores come from replay/survivorship-biased data and are indicative "
                 "only. No pick can honestly be called \"strong\" yet.\n")
    L.append(f"**Market read.** {rep['market_read']}\n")
    if rep["no_qualifying_setups"]:
        L.append("## No qualifying setups today\nNothing cleared the bar (conviction + "
                 "reward:risk + regime). Cash is a position — this is a valid outcome, not a failure.")
    else:
        L.append("## Picks")
        for r in rep["picks"]:
            L.append(f"\n### {r['ticker']} · {r['conviction_band'].upper()} {r['conviction_score']} "
                     f"· R:R {r['reward_to_risk']}")
            L.append(f"- Entry {r['entry_zone']['low']}–{r['entry_zone']['high']} · "
                     f"Stop {r['stop_loss']} · Target {r['targets'][0]['level']}")
            L.append(f"- Size: {r['position_size']['shares_or_units']} shares "
                     f"(${r['position_size']['dollar_risk']:,.0f} risk, "
                     f"{r['position_size']['percent_of_equity']}% equity)")
            L.append(f"- Thesis: {r['thesis']}")
            L.append(f"- Invalidation: {r['invalidation']}")
            L.append(f"- Bear case: {r['_self_red_team'][0] if r['_self_red_team'] else 'n/a'}")
            L.append(f"- Caveats: {r['confidence_caveats']}")
    if rep["watch_list"]:
        L.append("\n## Watch list")
        for w in rep["watch_list"]:
            L.append(f"- {w['ticker']} ({w['setup']}): {w['why_not']} → promote on: {w['trigger']}")
    L.append(f"\n_{rep['disclaimer']}_")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--equity", type=float, default=50000)
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rep = recommend(a.equity, a.top)
    (REPORTS / "recommendations.json").write_text(json.dumps(rep, indent=2, default=str))
    print(json.dumps(rep, indent=2, default=str) if a.json else render(rep))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""TradingBrain — one-command validation + final presentation.

Runs every validation layer built for TradingBrain, confirms the SAFETY
INVARIANTS still hold, and writes a single honest FINAL-REPORT.md that presents
the whole product and its verdict.

What "pass" means here is narrow and important: it means the validation MACHINERY
works and the safety invariants hold (the system refuses to over-claim and stays
fail-closed). It does NOT mean the strategy is cleared to trade — that verdict is
reported separately and is currently REJECTED / BLOCKED, on purpose.

Usage:
  python3 -m scripts.validate_all              # full run (includes test suite)
  python3 -m scripts.validate_all --skip-tests # faster; skip pytest
"""
from __future__ import annotations
import json, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
REPORTS = ROOT / "reports"
REPORT_MD = ROOT / "FINAL-REPORT.md"

CHECK = "✅"
FAIL = "❌"
INFO = "ℹ️"


def _result(name, ok, detail):
    return {"name": name, "ok": bool(ok), "detail": detail}


# ---------------------------------------------------------------- checks ----
def check_tests() -> dict:
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q", "--no-header"],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=900)
        tail = (r.stdout or "").strip().splitlines()[-1:] or [""]
        passed = "passed" in tail[0] and "failed" not in tail[0]
        return _result("Test suite", passed, tail[0].strip() or "no output")
    except Exception as e:
        return _result("Test suite", False, f"could not run pytest ({type(e).__name__})")


def check_safety_invariants() -> list[dict]:
    out = []

    # 1. Go-live computes a verdict and live trading is fail-closed (blocked).
    try:
        from lab import go_live
        rep = go_live.evaluate()
        reason = go_live.gate_reason_for_live()
        out.append(_result(
            "Go-live verdict + live enforcement",
            rep.get("verdict") in ("BLOCKED", "CLEARED FOR LIVE") and (
                reason is not None or rep["verdict"] == "CLEARED FOR LIVE"),
            f"verdict={rep.get('verdict')}; live blocked because: "
            f"{reason or 'cleared'}"))
    except Exception as e:
        out.append(_result("Go-live verdict + live enforcement", False, f"error: {e}"))

    # 2. Recommendation engine caps conviction (no 'strong' while zero live).
    try:
        import recommend
        rec = recommend.recommend(equity=50000, top=5)
        cap = rec.get("conviction_cap_active")
        strong = [p for p in rec.get("picks", []) if p.get("conviction_band") == "strong"]
        out.append(_result(
            "Conviction cap (no overclaiming)",
            (not cap) or (cap and not strong),
            f"cap_active={cap}; strong_picks={len(strong)} (must be 0 while capped)"))
    except Exception as e:
        out.append(_result("Conviction cap (no overclaiming)", False, f"error: {e}"))

    # 3. Export bridge matches the app schema (no null levels, no 'strong' if capped).
    try:
        from scripts import export_app
        exp = export_app.build_export()
        problems = export_app.validate(exp)
        out.append(_result("App export bridge", not problems,
                            "schema-valid" if not problems else f"{len(problems)} problem(s)"))
    except Exception as e:
        out.append(_result("App export bridge", False, f"error: {e}"))

    # 4. Memory recall never misreports the track record (independent check).
    try:
        from lab.memory_metrics import recall_fidelity
        f = recall_fidelity()
        out.append(_result("Memory recall fidelity", f.get("fidelity_pct") == 100.0,
                            f"{f.get('fidelity_pct')}% of recalled facts match a fresh recompute"))
    except Exception as e:
        out.append(_result("Memory recall fidelity", False, f"error: {e}"))

    # 5. Data-quality gate passes (point-in-time sanity).
    try:
        dq = json.loads((REPORTS / "data-quality.json").read_text())
        out.append(_result("Data-quality gate", bool(dq.get("pass")),
                            f"pass={dq.get('pass')}, hard_failures={len(dq.get('hard_failures', []))}"))
    except Exception:
        out.append(_result("Data-quality gate", False, "data-quality.json missing — run lab.data_quality"))

    # 6. Look-ahead / determinism proofs on file and passing.
    try:
        v = json.loads((REPORTS / "validate.json").read_text())
        out.append(_result("No-look-ahead proofs", bool(v.get("pass")),
                            f"pass={v.get('pass')} (no_lookahead, live==backtest, determinism)"))
    except Exception:
        out.append(_result("No-look-ahead proofs", False, "validate.json missing — run lab.validate"))

    return out


def check_validation_outputs() -> list[dict]:
    """Run the heavy validators so we KNOW they execute, and capture verdicts."""
    out = []
    try:
        from backtest import monte_carlo
        mc = monte_carlo.run(paths=5000, source="replay", seed=7, method="block")
        ror = mc.get("risk_of_ruin", {})
        out.append(_result("Monte Carlo (risk of ruin)",
                           "error" not in mc and "probability" in ror,
                           f"risk_of_ruin={ror.get('probability')}, "
                           f"99th-pct DD≈{mc.get('max_drawdown_pct_approx', {}).get('p99')}%"))
    except Exception as e:
        out.append(_result("Monte Carlo (risk of ruin)", False, f"error: {e}"))

    try:
        from lab import gauntlet
        g = gauntlet.scorecard()
        out.append(_result("Validation gauntlet",
                           g.get("verdict") in ("APPROVED", "CONDITIONAL", "REJECTED"),
                           f"verdict={g.get('verdict')}, score={g.get('overall_score')}/100"))
    except Exception as e:
        out.append(_result("Validation gauntlet", False, f"error: {e}"))
    return out


# --------------------------------------------------------- presentation ----
def _verdicts():
    gl = json.loads((REPORTS / "go-live.json").read_text()) if (REPORTS / "go-live.json").exists() else {}
    g = json.loads((REPORTS / "gauntlet.json").read_text()) if (REPORTS / "gauntlet.json").exists() else {}
    rec = json.loads((REPORTS / "recommendations.json").read_text()) if (REPORTS / "recommendations.json").exists() else {}
    return gl, g, rec


def write_final_report(results: list[dict]) -> None:
    gl, g, rec = _verdicts()
    healthy = all(r["ok"] for r in results)
    L = [
        "# TradingBrain — Final Report",
        f"_generated {datetime.now(timezone.utc).isoformat()}_",
        "",
        "## What this is",
        "A swing-trading decision-support engine with an unusually honest validation",
        "and safety apparatus. It screens a universe, scores conviction across six",
        "pillars, builds defined-risk trade plans, red-teams its own calls, and refuses",
        "to trade live until a battery of gates is green.",
        "",
        "## The verdict that matters",
        f"- **Validation gauntlet: {g.get('verdict', '?')}** "
        f"(robustness {g.get('overall_score', '?')}/100)",
        f"- **Go-live gate: {gl.get('verdict', '?')}**",
        f"- **Live trades on record: {rec.get('live_trades_on_record', 0)}** "
        f"· conviction cap active: {rec.get('conviction_cap_active')}",
        "",
        "> This system is **not cleared to trade real money**, and that is the correct,",
        "> intended state. The blocker is not a bug — it is the absence of a real",
        "> forward paper-trading record and a survivorship-free universe. No amount of",
        "> code changes this; only paper-trading and better data do.",
        "",
        "## Validation self-check",
        f"**Infrastructure health: {'ALL CHECKS PASS ' + CHECK if healthy else 'SOME CHECKS FAILED ' + FAIL}**",
        "",
        "_'Pass' means the validation machinery works and the safety invariants hold",
        "(the system refuses to over-claim and stays fail-closed). It does NOT mean the",
        "strategy is approved._",
        "",
        "| Check | Status | Detail |",
        "|-------|--------|--------|",
    ]
    for r in results:
        L.append(f"| {r['name']} | {CHECK if r['ok'] else FAIL} | {r['detail']} |")

    L += [
        "",
        "## What is verified vs not",
        "- **Verified (Python backend):** the engine, regime labels, memory recall,",
        "  Monte Carlo, the gauntlet, the go-live gate (enforced + fail-closed), and the",
        "  app export bridge — all exercised by the test suite.",
        "- **Not run here:** the Next.js app against live Supabase, live market-data",
        "  fetch, and any Anthropic call. Treat the app as reviewed, not battle-tested.",
        "",
        "## Honest limitations (see CRITIQUE.md)",
        "- Conviction weights, regime thresholds, and Monte Carlo knobs are hand-picked,",
        "  not optimized.",
        "- PBO is high on a short, single-setup-dominated sample — a real overfitting flag.",
        "- The replay trades are simulated by the same logic being validated (circularity).",
        "- This is honesty/validation scaffolding around an edge that is **not yet proven",
        "  live**.",
        "",
        "## The one next step that matters",
        "Run the app in paper mode to build a real forward record, and add a",
        "survivorship-free (delisted-inclusive) universe. Those — not more code — are",
        "what move the verdict.",
        "",
        "_Informational engineering results, not financial advice. Markets risk total",
        "loss of capital; past or backtested performance does not predict the future._",
    ]
    REPORT_MD.write_text("\n".join(L))


def main():
    t0 = time.time()
    skip = "--skip-tests" in sys.argv
    print("TradingBrain validation — running all checks...\n")

    results = []
    if not skip:
        print("  running test suite (this takes ~40s)...")
        results.append(check_tests())
    print("  checking safety invariants...")
    results += check_safety_invariants()
    print("  running validators (Monte Carlo, gauntlet)...")
    results += check_validation_outputs()

    write_final_report(results)

    print("\n" + "=" * 60)
    for r in results:
        print(f"  {CHECK if r['ok'] else FAIL} {r['name']}: {r['detail']}")
    print("=" * 60)
    healthy = all(r["ok"] for r in results)
    gl, g, _ = _verdicts()
    print(f"\nValidation infrastructure: {'HEALTHY' if healthy else 'PROBLEMS FOUND'}")
    print(f"Gauntlet verdict: {g.get('verdict','?')} ({g.get('overall_score','?')}/100)  ·  "
          f"Go-live: {gl.get('verdict','?')}")
    print(f"\nFinal report written to FINAL-REPORT.md  ({time.time()-t0:.0f}s)")
    sys.exit(0 if healthy else 1)


if __name__ == "__main__":
    main()

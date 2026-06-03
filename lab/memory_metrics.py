#!/usr/bin/env python3
"""Memory metrics — the numbers that decide whether memory is actually better.

North star (from the memory master prompt): memory is "better" only if it changes
DECISIONS for the better. So this module measures recall QUALITY, not volume, on
the data that actually exists — and is blunt about what cannot be measured yet
(decision-lift / repeated-failure need live decisions, of which there are ~0).

Metrics computed on real data:
  * experience_coverage — fraction of resolved-trade experience reachable via recall.
  * recall_precision     — of the items recall returns for a setup, fraction on-target.
  * honesty_rate         — fraction of recalled quantitative facts carrying (n, source label).
  * lesson_health        — count, single-event share, contradiction rate, median age (days).
  * NOT-yet-measurable    — decision_lift, forecast_accuracy, repeated_failure_rate (no live decisions).

Run:
  python3 -m lab.memory_metrics                 # baseline report (old retrieve vs new recall)
  python3 -m lab.memory_metrics --json          # machine-readable
"""
from __future__ import annotations
import json, statistics, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from paths import ROOT
from collective import memory

KB = ROOT / "data" / "knowledge.duckdb"


def _con():
    import duckdb
    return duckdb.connect(str(KB), read_only=True)


def _resolved_setups() -> list[str]:
    con = _con()
    rows = con.execute(
        "SELECT setup, COUNT(*) FROM signal_ledger WHERE realized_R IS NOT NULL "
        "AND setup IS NOT NULL GROUP BY setup ORDER BY COUNT(*) DESC").fetchall()
    con.close()
    return [r[0] for r in rows]


def _on_target(text: str, setup: str) -> bool:
    """A returned lesson/failure is 'on-target' for a setup if it actually
    references that setup (the cheapest defensible relevance test)."""
    if not text:
        return False
    return setup.lower() in str(text).lower()


def experience_coverage(recall_fn) -> dict:
    """Fraction of resolved-trade experience (by setup) that recall surfaces.
    Old retrieve() never touches signal_ledger -> 0%. New recall() -> all setups."""
    setups = _resolved_setups()
    con = _con()
    total = con.execute(
        "SELECT COUNT(*) FROM signal_ledger WHERE realized_R IS NOT NULL").fetchone()[0]
    con.close()
    reached_trades, reached_setups = 0, 0
    for s in setups:
        out = recall_fn(s)
        exp = out.get("experience") or out.get("track_record")
        if exp and (exp.get("n") if isinstance(exp, dict) else None):
            reached_setups += 1
            reached_trades += int(exp.get("n", 0))
        elif exp and isinstance(exp, list) and exp:
            reached_setups += 1
            reached_trades += sum(int(e.get("n", 0)) for e in exp)
    return {"setups_total": len(setups), "setups_with_experience": reached_setups,
            "resolved_trades_total": total, "resolved_trades_reachable": reached_trades,
            "coverage_pct": round(100.0 * reached_trades / total, 1) if total else 0.0}


def recall_precision(recall_fn, k: int = 5) -> dict:
    """Of the top-k lessons+failures recall returns for a setup, fraction on-target."""
    setups = _resolved_setups()
    per, hits, shown = {}, 0, 0
    for s in setups:
        out = recall_fn(s)
        items = []
        for L in (out.get("lessons") or [])[:k]:
            items.append(L.get("lesson", ""))
        for f in (out.get("failures") or [])[:k]:
            items.append(f.get("failure_mode", ""))
        if not items:
            per[s] = None
            continue
        on = sum(1 for t in items if _on_target(t, s))
        per[s] = round(on / len(items), 2)
        hits += on
        shown += len(items)
    return {"per_setup": per,
            "precision_at_k": round(hits / shown, 3) if shown else 0.0,
            "k": k}


def honesty_rate(recall_fn) -> dict:
    """Fraction of recalled QUANTITATIVE facts that carry a sample size AND a
    replay/live source label. Old path returns oos_expectancy_R with neither."""
    setups = _resolved_setups()
    labeled, total = 0, 0
    for s in setups:
        out = recall_fn(s)
        exp = out.get("experience") or out.get("track_record")
        entries = exp if isinstance(exp, list) else ([exp] if isinstance(exp, dict) else [])
        for e in entries:
            if not isinstance(e, dict):
                continue
            # a quantitative fact = something with a number (avg_R / win_rate)
            if any(key in e for key in ("avg_R", "win_rate", "expectancy_R")):
                total += 1
                if e.get("n") is not None and e.get("source"):
                    labeled += 1
        # legacy strategy_status carries a number but no n/label
        ss = out.get("strategy_status")
        if isinstance(ss, dict) and ss.get("oos_expectancy_R") is not None:
            total += 1
            if ss.get("n") is not None and ss.get("source"):
                labeled += 1
    return {"quantitative_facts": total, "with_n_and_source": labeled,
            "honesty_pct": round(100.0 * labeled / total, 1) if total else None}


def lesson_health() -> dict:
    con = _con()
    rows = con.execute(
        "SELECT lesson, confidence, times_reinforced, ts FROM lessons").fetchall()
    con.close()
    n = len(rows)
    if not n:
        return {"count": 0}
    single = sum(1 for r in rows if (r[2] or 0) <= 1)
    now = datetime.now(timezone.utc)
    ages = []
    for r in rows:
        ts = r[3]
        if isinstance(ts, datetime):
            ts = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
            ages.append((now - ts).days)
    # contradiction: same setup named with opposing verdict words across lessons
    txt = [str(r[0]).lower() for r in rows]
    contra = 0
    for s in _resolved_setups():
        sl = [t for t in txt if s.lower() in t]
        pos = any(w in t for t in sl for w in ("deploy", "validated", "works", "edge holds"))
        neg = any(w in t for t in sl for w in ("broken", "reject", "fails", "no edge", "lower"))
        if pos and neg:
            contra += 1
    return {"count": n,
            "single_event_share_pct": round(100.0 * single / n, 1),
            "median_age_days": int(statistics.median(ages)) if ages else None,
            "contradicting_setups": contra}


# --- adapters so we can score OLD vs NEW recall with the same probes ----------
def _old_recall(setup):
    """Baseline: the pre-existing retrieve() — ignores the ledger, lessons not
    scoped to setup."""
    return memory.retrieve(setup=setup, limit=5)


def _new_recall(setup):
    """Upgraded: experience-grounded, honesty-labeled recall (if available)."""
    if hasattr(memory, "recall"):
        return memory.recall(setup=setup, k=5)
    return _old_recall(setup)


def recall_fidelity() -> dict:
    """Non-circular check (fixes F8): does recall report the TRUTH? For each
    setup we independently recompute avg_R and win_rate straight from the ledger
    and compare to what recall() returns. This is independent of the substring
    relevance rule, so it cannot be gamed by the same change that defines it."""
    from collective import memory
    con = _con()
    checks, ok = [], 0
    for s in _resolved_setups():
        truth = con.execute(
            "SELECT ROUND(AVG(realized_R),3), ROUND(100.0*AVG(CASE WHEN realized_R>0 "
            "THEN 1 ELSE 0 END),1) FROM signal_ledger WHERE setup=? AND realized_R IS NOT NULL",
            [s]).fetchone()
        rec = memory.recall(s)
        exp = (rec.get("experience") or [{}])[0]
        match = (exp.get("avg_R") == truth[0] and exp.get("win_rate") == truth[1])
        checks.append({"setup": s, "recall_avg_R": exp.get("avg_R"),
                       "truth_avg_R": truth[0], "match": match})
        ok += int(match)
    con.close()
    return {"setups": len(checks), "faithful": ok,
            "fidelity_pct": round(100.0 * ok / len(checks), 1) if checks else None,
            "note": "independent recompute vs recall output; 100% means recall never "
                    "misreports the track record."}


def baseline_report() -> dict:
    has_new = hasattr(memory, "recall")
    rep = {
        "asof": datetime.now(timezone.utc).isoformat(),
        "store": str(KB),
        "old_retrieve": {
            "experience_coverage": experience_coverage(_old_recall),
            "recall_precision": recall_precision(_old_recall),
            "honesty_rate": honesty_rate(_old_recall),
        },
        "new_recall_available": has_new,
        "lesson_health": lesson_health(),
        "recall_fidelity": recall_fidelity(),
        "not_yet_measurable": {
            "reason": "0 rows in decisions/forecasts — these need live/paper "
                      "decisions logged with their recall citations.",
            "decision_lift": None,
            "forecast_accuracy": None,
            "repeated_failure_rate": None,
        },
    }
    if has_new:
        rep["new_recall"] = {
            "experience_coverage": experience_coverage(_new_recall),
            "recall_precision": recall_precision(_new_recall),
            "honesty_rate": honesty_rate(_new_recall),
        }
    return rep


def _fmt(rep: dict) -> str:
    L = ["MEMORY METRICS — baseline", f"store: {rep['store']}", ""]
    def block(name, b):
        ec, rp, hr = b["experience_coverage"], b["recall_precision"], b["honesty_rate"]
        L.append(f"[{name}]")
        L.append(f"  experience coverage : {ec['coverage_pct']}%  "
                 f"({ec['resolved_trades_reachable']}/{ec['resolved_trades_total']} resolved trades, "
                 f"{ec['setups_with_experience']}/{ec['setups_total']} setups)")
        L.append(f"  recall precision@{rp['k']}: {rp['precision_at_k']}")
        L.append(f"  honesty rate        : {hr['honesty_pct']}%  "
                 f"({hr['with_n_and_source']}/{hr['quantitative_facts']} facts carry n+source)")
    block("OLD retrieve()", rep["old_retrieve"])
    if rep.get("new_recall"):
        L.append("")
        block("NEW recall()", rep["new_recall"])
    lh = rep["lesson_health"]
    L += ["", "[lesson health]",
          f"  lessons: {lh.get('count')}  · single-event: {lh.get('single_event_share_pct')}%"
          f"  · median age: {lh.get('median_age_days')}d"
          f"  · contradicting setups: {lh.get('contradicting_setups')}"]
    nm = rep["not_yet_measurable"]
    L += ["", "[not yet measurable]", f"  {nm['reason']}",
          "  -> decision_lift, forecast_accuracy, repeated_failure_rate all pending live decisions."]
    return "\n".join(L)


def main():
    rep = baseline_report()
    if "--json" in sys.argv:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print(_fmt(rep))
    out = ROOT / "reports" / "memory-metrics.json"
    out.write_text(json.dumps(rep, indent=2, default=str))


if __name__ == "__main__":
    main()

import { NextResponse } from "next/server";
import { readFile } from "node:fs/promises";
import path from "node:path";

type JsonRecord = Record<string, unknown>;

export const dynamic = "force-dynamic";
export const revalidate = 0;

const reportsDir = () => path.join(process.cwd(), "..", "reports");

async function readJson<T = JsonRecord>(name: string, fallback: T): Promise<T> {
  try {
    const raw = await readFile(path.join(reportsDir(), name), "utf8");
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function asRecord(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as JsonRecord) : {};
}

function asArray(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.map(asRecord) : [];
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => asString(item)).filter(Boolean) : [];
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asNumber(value: unknown, fallback = 0): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

function statusTone(status: string): "green" | "amber" | "red" | "slate" {
  const s = status.toLowerCase();
  if (s.includes("pass") || s.includes("candidate") || s.includes("ready") || s.includes("active")) return "green";
  if (s.includes("needs") || s.includes("watch") || s.includes("paper") || s.includes("research")) return "amber";
  if (s.includes("fail") || s.includes("blocked") || s.includes("critical")) return "red";
  return "slate";
}

export async function GET() {
  const [
    appExport,
    readiness,
    goLive,
    stress,
    narrative,
    skillLab,
    alpaca,
    paperScorecard,
    dataQuality,
  ] = await Promise.all([
    readJson<JsonRecord>("app-export.json", {}),
    readJson<JsonRecord>("live-readiness-dashboard.json", {}),
    readJson<JsonRecord>("go-live.json", {}),
    readJson<JsonRecord>("live-readiness-stress.json", {}),
    readJson<JsonRecord>("event-narrative-intelligence-latest.json", {}),
    readJson<JsonRecord>("paper-skill-lab-latest.json", {}),
    readJson<JsonRecord>("alpaca-paper-trade-three-latest.json", {}),
    readJson<JsonRecord>("forward-paper-scorecard.json", {}),
    readJson<JsonRecord>("data-quality.json", {}),
  ]);

  const run = asRecord(appExport.run);
  const evidence = asRecord(appExport.evidence_summary);
  const account = asRecord(alpaca.alpaca_account);
  const clock = asRecord(alpaca.clock);
  const bestSkill = asRecord(skillLab.best_skill);
  const bestSkillRun = asRecord(bestSkill.best_primary_run);
  const narrativeEvents = asArray(narrative.events).slice(0, 5);
  const gates = asArray(goLive.gates);
  const gateRows = gates.map((gate) => ({
    name: asString(gate.gate, "Gate"),
    status: asString(gate.status, "UNKNOWN"),
    detail: asString(gate.detail, ""),
    tone: statusTone(asString(gate.status, "")),
  }));

  const report = {
    asof: new Date().toISOString(),
    mission: {
      name: "TradingBrain Mission Control",
      mode: asString(readiness.mode, asString(run.go_live_verdict, "paper")),
      liveStatus: asString(readiness.status, asString(stress.verdict, "LIVE_BLOCKED")),
      verdict: asString(readiness.verdict, asString(goLive.verdict, "BLOCKED")),
      goLive: asString(goLive.verdict, "BLOCKED"),
      posture: asString(readiness.posture, "RESEARCH_ONLY"),
      marketRead: asString(run.market_read, "No latest market read available."),
      disclaimer: asString(run.disclaimer, "Decision support only. Paper mode remains gated by risk controls."),
    },
    scores: {
      overall: asNumber(stress.overall_score),
      safety: asNumber(stress.safety_score),
      data: asNumber(stress.data_score),
      execution: asNumber(stress.execution_score),
      paperEvidence: asNumber(stress.paper_evidence_score),
      backtestRealism: asNumber(stress.backtest_realism_score),
      aiSafety: asNumber(stress.ai_safety_score),
      observability: asNumber(stress.observability_score),
    },
    blockers: {
      critical: asStringArray(readiness.blockers),
      goLive: asStringArray(goLive.blockers),
      execution: asStringArray(alpaca.preflight_blockers),
      nextAction: asString(readiness.next_action, asString(stress.fastest_next_step, "Collect forward paper evidence.")),
    },
    account: {
      status: asString(account.status, "unknown"),
      equity: asNumber(account.equity),
      cash: asNumber(account.cash),
      buyingPower: asNumber(account.buying_power),
      marketOpen: Boolean(clock.is_open),
      nextOpen: asString(clock.next_open, ""),
      openOrders: asArray(alpaca.open_orders_before).map((order) => ({
        symbol: asString(order.symbol),
        status: asString(order.status),
      })),
      selectedSymbols: Array.isArray(alpaca.symbols) ? alpaca.symbols.map((s) => asString(s)).filter(Boolean) : [],
      ordersSubmitted: asNumber(alpaca.orders_submitted),
    },
    evidence: {
      paperOpen: asNumber(evidence.paper_open),
      paperResolved: asNumber(evidence.paper_resolved),
      forwardResolved: asNumber(evidence.forward_resolved),
      liveResolved: asNumber(evidence.live_resolved),
      replayResolved: asNumber(evidence.replay_resolved),
      scorecardResolved: asNumber(paperScorecard.resolved_trades),
      scorecardVerdict: asString(paperScorecard.verdict, asString(paperScorecard.drift_status, "insufficient_forward_paper")),
      scorecardDrift: asString(paperScorecard.drift_status, "unknown"),
    },
    narrative: {
      candidateTop3: Array.isArray(narrative.paper_candidate_top3) ? narrative.paper_candidate_top3.map((s) => asString(s)).filter(Boolean) : [],
      watchlistTop3: Array.isArray(narrative.paper_watchlist_top3) ? narrative.paper_watchlist_top3.map((s) => asString(s)).filter(Boolean) : [],
      events: narrativeEvents.map((event) => ({
        ticker: asString(event.ticker, "N/A"),
        title: asString(event.event_title, "Narrative event"),
        signal: asString(event.final_signal, "unknown"),
        confidence: asNumber(event.confidence_score),
        chaseRisk: asNumber(event.chase_risk_score),
        sourceScore: asNumber(event.source_score),
      })),
    },
    skillLab: {
      bestSkill: asString(bestSkill.skill, "unknown"),
      bestScore: asNumber(bestSkill.paper_skill_score),
      verdict: asString(bestSkill.verdict, "unknown"),
      currentTop3: Array.isArray(bestSkill.current_top3) ? bestSkill.current_top3.map((s) => asString(s)).filter(Boolean) : [],
      ensembleTop3: Array.isArray(skillLab.ensemble_top3) ? skillLab.ensemble_top3.map((s) => asString(s)).filter(Boolean) : [],
      simulatedReturnPct: asNumber(bestSkillRun.return_pct),
      simulatedMaxDrawdownPct: asNumber(bestSkillRun.max_drawdown_pct),
      simulatedDollars: asNumber(bestSkillRun.dollars_made_lost),
    },
    dataQuality: {
      pass: Boolean(dataQuality.pass),
      warnings: Array.isArray(dataQuality.warnings) ? dataQuality.warnings.slice(0, 6).map((w) => asString(w)).filter(Boolean) : [],
      tickersWithIssues: asNumber(dataQuality.tickers_with_issues),
      tickers: asNumber(dataQuality.tickers),
    },
    gates: gateRows,
    recommendations: Array.isArray(appExport.recommendations) ? appExport.recommendations : [],
  };

  return NextResponse.json(report);
}

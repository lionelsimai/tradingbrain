"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { MissionDashboardData, Recommendation } from "@/lib/types";
import { PickCard } from "./PickCard";

type Tone = "green" | "amber" | "red" | "slate" | "blue";

const scoreLabels: { key: string; label: string }[] = [
  { key: "safety", label: "Safety" },
  { key: "execution", label: "Execution" },
  { key: "data", label: "Data" },
  { key: "backtestRealism", label: "Backtest" },
  { key: "paperEvidence", label: "Paper Evidence" },
  { key: "observability", label: "Observability" },
];

export function Dashboard() {
  const [mission, setMission] = useState<MissionDashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/mission", { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => {
        setMission(d);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load mission dashboard"));
  }, []);

  const executionBlocked = (mission?.blockers.execution.length ?? 0) > 0;
  const goLiveBlocked = mission?.mission.goLive === "BLOCKED";
  const pipeline = useMemo(() => buildPipeline(mission), [mission]);

  if (!mission) {
    return (
      <div className="mx-auto flex min-h-screen max-w-7xl items-center justify-center px-6">
        <div className="w-full max-w-md rounded-lg border border-slate-200 bg-white p-6 text-center shadow-sm">
          <div className="text-sm font-semibold uppercase tracking-wide text-slate-500">TradingBrain</div>
          <div className="mt-3 h-2 rounded-full bg-slate-100">
            <div className="h-2 w-2/3 rounded-full bg-cyan-500" />
          </div>
          <p className="mt-4 text-sm text-slate-600">{error ?? "Loading mission state..."}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1440px] px-4 py-5 sm:px-6 lg:px-8">
      <header className="border-b border-slate-200 pb-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-cyan-700">Mission Control</div>
            <h1 className="mt-1 text-3xl font-semibold text-slate-950">TradingBrain</h1>
            <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-600">{mission.mission.marketRead}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge label={`Mode ${mission.mission.mode}`} tone="blue" />
            <Badge label={`Go-live ${mission.mission.goLive}`} tone={goLiveBlocked ? "red" : "green"} />
            <Badge label={`Posture ${mission.mission.posture}`} tone="amber" />
            <Badge label={mission.account.marketOpen ? "Market open" : "Market closed"} tone={mission.account.marketOpen ? "green" : "slate"} />
          </div>
        </div>
      </header>

      {error && (
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          {error}
        </div>
      )}

      <section className="mt-5 grid gap-4 lg:grid-cols-[1.1fr_1fr_1fr]">
        <Panel title="Live Readiness" eyebrow={mission.mission.liveStatus}>
          <div className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
            <Field label="Verdict" value={mission.mission.verdict} tone="red" />
            <Field label="Overall score" value={`${mission.scores.overall}/100`} tone={mission.scores.overall > 60 ? "green" : "red"} />
            <Field label="Forward paper" value={`${mission.evidence.forwardResolved} resolved`} tone={mission.evidence.forwardResolved > 0 ? "green" : "red"} />
            <Field label="Data quality" value={mission.dataQuality.pass ? "Pass" : "Fail"} tone={mission.dataQuality.pass ? "green" : "red"} />
          </div>
          <div className="mt-4 border-t border-slate-100 pt-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Safe next action</div>
            <p className="mt-1 text-sm leading-5 text-slate-700">{mission.blockers.nextAction}</p>
          </div>
        </Panel>

        <Panel title="Readiness Scores" eyebrow="Stress Suite">
          <div className="space-y-3">
            {scoreLabels.map((item) => (
              <ScoreRow key={item.key} label={item.label} value={mission.scores[item.key] ?? 0} />
            ))}
          </div>
        </Panel>

        <Panel title="Paper Account" eyebrow={mission.account.status}>
          <div className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
            <Field label="Equity" value={money(mission.account.equity)} tone="slate" />
            <Field label="Cash" value={money(mission.account.cash)} tone={mission.account.cash >= 0 ? "green" : "red"} />
            <Field label="Buying power" value={money(mission.account.buyingPower)} tone="slate" />
            <Field label="Orders sent" value={`${mission.account.ordersSubmitted}`} tone={mission.account.ordersSubmitted > 0 ? "green" : "slate"} />
          </div>
          <div className="mt-4 border-t border-slate-100 pt-4">
            <div className="mb-2 flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-slate-500">
              <span>Execution Gate</span>
              <StatusDot tone={executionBlocked ? "red" : "green"} />
            </div>
            <BlockerList items={mission.blockers.execution} empty="No execution blockers in latest report." />
          </div>
        </Panel>
      </section>

      <section className="mt-5">
        <Panel title="Candidate Pipeline" eyebrow="Narrative + Skills + Broker Gate">
          <div className="grid gap-3 md:grid-cols-4">
            {pipeline.map((step) => (
              <PipelineStep key={step.title} {...step} />
            ))}
          </div>
        </Panel>
      </section>

      <section className="mt-5 grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <Panel title="Event Narrative Intelligence" eyebrow="Verified catalysts">
          <div className="space-y-3">
            {mission.narrative.events.map((event) => (
              <NarrativeRow key={`${event.ticker}-${event.title}`} event={event} />
            ))}
          </div>
        </Panel>

        <Panel title="Skill Lab" eyebrow={mission.skillLab.verdict}>
          <div className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
            <Field label="Best skill" value={mission.skillLab.bestSkill} tone="blue" />
            <Field label="Skill score" value={`${mission.skillLab.bestScore}`} tone="slate" />
            <Field label="Replay return" value={`${mission.skillLab.simulatedReturnPct.toFixed(2)}%`} tone="green" />
            <Field label="Max drawdown" value={`${mission.skillLab.simulatedMaxDrawdownPct.toFixed(2)}%`} tone="amber" />
          </div>
          <TickerStrip label="Ensemble" tickers={mission.skillLab.ensembleTop3} />
          <TickerStrip label="Best skill" tickers={mission.skillLab.currentTop3} />
          <p className="mt-4 text-xs leading-5 text-slate-500">
            Historical replay is research evidence. It does not satisfy the forward-paper gate.
          </p>
        </Panel>
      </section>

      <section className="mt-5 grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <Panel title="Go-Live Gates" eyebrow="Fail closed">
          <div className="space-y-2">
            {mission.gates.map((gate) => (
              <GateRow key={gate.name} gate={gate} />
            ))}
          </div>
        </Panel>

        <Panel title="Base Recommendations" eyebrow={`${mission.recommendations.length} active`}>
          {mission.recommendations.length === 0 ? (
            <div className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
              No qualifying setups in the latest export.
            </div>
          ) : (
            <div className="grid gap-3 lg:grid-cols-2">
              {mission.recommendations.map((rec) => (
                <PickCard key={rec.id} rec={rec as Recommendation} />
              ))}
            </div>
          )}
        </Panel>
      </section>

      <section className="mt-5 grid gap-4 lg:grid-cols-2">
        <Panel title="Evidence" eyebrow={mission.evidence.scorecardVerdict}>
          <div className="grid grid-cols-3 gap-x-4 gap-y-3 text-sm">
            <Field label="Paper open" value={`${mission.evidence.paperOpen}`} tone="slate" />
            <Field label="Paper resolved" value={`${mission.evidence.paperResolved}`} tone="red" />
            <Field label="Replay resolved" value={`${mission.evidence.replayResolved}`} tone="amber" />
            <Field label="Live resolved" value={`${mission.evidence.liveResolved}`} tone="red" />
            <Field label="Scorecard trades" value={`${mission.evidence.scorecardResolved}`} tone="red" />
            <Field label="Drift" value={mission.evidence.scorecardDrift} tone="amber" />
          </div>
        </Panel>

        <Panel title="Data Quality" eyebrow={mission.dataQuality.pass ? "Pass" : "Fail"}>
          <div className="mb-3 text-sm text-slate-700">
            {mission.dataQuality.tickersWithIssues} of {mission.dataQuality.tickers} tickers flagged.
          </div>
          <BlockerList items={mission.dataQuality.warnings} empty="No data-quality warnings in latest report." />
        </Panel>
      </section>

      <footer className="mt-6 border-t border-slate-200 py-4 text-xs leading-5 text-slate-500">
        {mission.mission.disclaimer}
      </footer>
    </div>
  );
}

function buildPipeline(mission: MissionDashboardData | null) {
  if (!mission) return [];
  return [
    {
      title: "Event Intel",
      status: mission.narrative.candidateTop3.length ? "candidate" : "watchlist",
      tone: mission.narrative.candidateTop3.length ? "green" : "amber",
      main: mission.narrative.candidateTop3.join(", ") || mission.narrative.watchlistTop3.join(", ") || "none",
      detail: "Verified narrative layer",
    },
    {
      title: "Skill Lab",
      status: mission.skillLab.verdict,
      tone: "blue",
      main: mission.skillLab.ensembleTop3.join(", ") || "none",
      detail: `${mission.skillLab.bestSkill} replay leader`,
    },
    {
      title: "Paper Selector",
      status: "selected",
      tone: "slate",
      main: mission.account.selectedSymbols.join(", ") || "none",
      detail: "Narrative filtered skill picks",
    },
    {
      title: "Execution",
      status: mission.blockers.execution.length ? "blocked" : "clear",
      tone: mission.blockers.execution.length ? "red" : "green",
      main: mission.account.ordersSubmitted ? `${mission.account.ordersSubmitted} sent` : "0 sent",
      detail: mission.account.marketOpen ? "Market open" : "Market closed",
    },
  ] as const;
}

function Panel({ title, eyebrow, children }: { title: string; eyebrow: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-4 flex min-h-8 items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-slate-950">{title}</h2>
          <div className="mt-0.5 text-xs font-medium uppercase tracking-wide text-slate-500">{eyebrow}</div>
        </div>
      </div>
      {children}
    </div>
  );
}

function Field({ label, value, tone }: { label: string; value: string; tone: Tone }) {
  return (
    <div className="min-w-0 border-l-2 border-slate-200 pl-3">
      <div className="truncate text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 break-words text-sm font-semibold ${textTone(tone)}`}>{value}</div>
    </div>
  );
}

function ScoreRow({ label, value }: { label: string; value: number }) {
  const tone: Tone = value >= 80 ? "green" : value >= 50 ? "amber" : "red";
  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-3 text-xs">
        <span className="font-medium text-slate-600">{label}</span>
        <span className={`font-semibold ${textTone(tone)}`}>{value}/100</span>
      </div>
      <div className="h-2 rounded-full bg-slate-100">
        <div className={`h-2 rounded-full ${barTone(tone)}`} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
      </div>
    </div>
  );
}

function PipelineStep({ title, status, tone, main, detail }: { title: string; status: string; tone: Tone; main: string; detail: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-slate-200 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="truncate text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</div>
        <Badge label={status} tone={tone} />
      </div>
      <div className="mt-3 break-words text-lg font-semibold text-slate-950">{main}</div>
      <div className="mt-1 text-xs text-slate-500">{detail}</div>
    </div>
  );
}

function NarrativeRow({ event }: { event: MissionDashboardData["narrative"]["events"][number] }) {
  const tone: Tone = event.signal === "paper_candidate" ? "green" : event.signal.includes("pullback") ? "amber" : "slate";
  return (
    <div className="border-b border-slate-100 pb-3 last:border-b-0 last:pb-0">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-slate-950">{event.ticker}</span>
            <Badge label={event.signal} tone={tone} />
          </div>
          <div className="mt-1 text-sm leading-5 text-slate-600">{event.title}</div>
        </div>
        <div className="grid min-w-[170px] grid-cols-3 gap-2 text-right text-xs">
          <MiniStat label="Conf" value={event.confidence} tone={event.confidence >= 70 ? "green" : "amber"} />
          <MiniStat label="Chase" value={event.chaseRisk} tone={event.chaseRisk >= 70 ? "red" : "amber"} />
          <MiniStat label="Source" value={event.sourceScore} tone={event.sourceScore >= 80 ? "green" : "amber"} />
        </div>
      </div>
    </div>
  );
}

function MiniStat({ label, value, tone }: { label: string; value: number; tone: Tone }) {
  return (
    <div>
      <div className={`font-semibold ${textTone(tone)}`}>{value.toFixed(0)}</div>
      <div className="text-slate-400">{label}</div>
    </div>
  );
}

function GateRow({ gate }: { gate: MissionDashboardData["gates"][number] }) {
  return (
    <div className="grid gap-2 border-b border-slate-100 py-2 last:border-b-0 sm:grid-cols-[210px_90px_1fr]">
      <div className="text-sm font-medium text-slate-800">{gate.name}</div>
      <Badge label={gate.status} tone={gate.tone} />
      <div className="line-clamp-2 text-xs leading-5 text-slate-500">{gate.detail}</div>
    </div>
  );
}

function TickerStrip({ label, tickers }: { label: string; tickers: string[] }) {
  return (
    <div className="mt-4">
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="flex flex-wrap gap-2">
        {tickers.length ? tickers.map((ticker) => <Badge key={ticker} label={ticker} tone="blue" />) : <span className="text-sm text-slate-400">none</span>}
      </div>
    </div>
  );
}

function BlockerList({ items, empty }: { items: string[]; empty: string }) {
  if (!items.length) return <p className="text-sm text-slate-500">{empty}</p>;
  return (
    <div className="space-y-2">
      {items.map((item, index) => (
        <div key={`${item}-${index}`} className="flex gap-2 text-sm leading-5 text-slate-700">
          <span className="mt-2 h-1.5 w-1.5 flex-none rounded-full bg-red-500" />
          <span className="min-w-0 break-words">{item}</span>
        </div>
      ))}
    </div>
  );
}

function Badge({ label, tone }: { label: string; tone: Tone }) {
  return (
    <span className={`inline-flex w-fit max-w-full items-center rounded-full px-2 py-0.5 text-xs font-semibold ${badgeTone(tone)}`}>
      <span className="truncate">{label}</span>
    </span>
  );
}

function StatusDot({ tone }: { tone: Tone }) {
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${barTone(tone)}`} />;
}

function money(value: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
}

function textTone(tone: Tone) {
  return {
    green: "text-emerald-700",
    amber: "text-amber-700",
    red: "text-red-700",
    slate: "text-slate-800",
    blue: "text-cyan-700",
  }[tone];
}

function barTone(tone: Tone) {
  return {
    green: "bg-emerald-500",
    amber: "bg-amber-500",
    red: "bg-red-500",
    slate: "bg-slate-500",
    blue: "bg-cyan-500",
  }[tone];
}

function badgeTone(tone: Tone) {
  return {
    green: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
    amber: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
    red: "bg-red-50 text-red-700 ring-1 ring-red-200",
    slate: "bg-slate-100 text-slate-700 ring-1 ring-slate-200",
    blue: "bg-cyan-50 text-cyan-700 ring-1 ring-cyan-200",
  }[tone];
}

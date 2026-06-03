// GET  /api/recommendations  -> latest run + its recommendations + paper trades
// POST /api/recommendations  -> ingest an engine export (reports/app-export.json)
//
// IMPORTANT: picks come from the tested Python engine, which computes real
// entry/stop/target from price structure. The app does NOT ask an LLM to invent
// price levels — that would hallucinate the exact numbers that define risk.
import { NextRequest, NextResponse } from "next/server";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { requireAutomationToken } from "@/lib/auth";
import { hasSupabaseServerConfig, supabaseServer } from "@/lib/supabase";
import type { AppExport } from "@/lib/types";

export async function GET() {
  if (!hasSupabaseServerConfig()) {
    try {
      const exportPath = path.join(process.cwd(), "..", "reports", "app-export.json");
      const exp = JSON.parse(await readFile(exportPath, "utf8")) as AppExport;
      return NextResponse.json({
        run: exp.run,
        recommendations: exp.recommendations ?? [],
        paper_trades: exp.paper_trades ?? [],
        live_trades: exp.live_trades ?? [],
        replay_trades: exp.replay_trades ?? [],
        evidence_summary: exp.evidence_summary ?? null,
        error: "Serving local reports/app-export.json because Supabase env vars are not configured",
      });
    } catch {
      return NextResponse.json({
        run: null,
        recommendations: [],
        paper_trades: [],
        error: "Supabase env vars are not configured and reports/app-export.json is unavailable",
      });
    }
  }
  const db = supabaseServer();
  const { data: runs } = await db.from("runs").select("*").order("ran_at", { ascending: false }).limit(1);
  const run = runs?.[0];
  if (!run) return NextResponse.json({ run: null, recommendations: [], paper_trades: [] });
  const { data: recs } = await db.from("recommendations").select("*")
    .eq("run_id", run.id).order("conviction_score", { ascending: false });
  const { data: paper } = await db.from("paper_trades").select("*")
    .order("opened_at", { ascending: false }).limit(200);
  return NextResponse.json({ run, recommendations: recs ?? [], paper_trades: paper ?? [] });
}

export async function POST(req: NextRequest) {
  const authError = requireAutomationToken(req);
  if (authError) return authError;
  if (!hasSupabaseServerConfig()) {
    return NextResponse.json({ error: "Supabase env vars are not configured" }, { status: 503 });
  }

  // Ingest the engine export produced by `python3 -m scripts.export_app`.
  const exp = (await req.json()) as AppExport;
  const db = supabaseServer();

  // Safety guard mirrored from the engine: refuse to ingest an inflated pick.
  if (exp.run?.conviction_cap_active) {
    const bad = exp.recommendations.find((r) => r.conviction_band === "strong");
    if (bad) return NextResponse.json(
      { error: `refused: ${bad.ticker} is 'strong' while conviction cap is active` },
      { status: 400 });
  }
  const nullLevel = exp.recommendations.find((r) => r.stop_loss == null || r.entry_low == null);
  if (nullLevel) return NextResponse.json(
    { error: `refused: ${nullLevel.ticker} has a null price level (engine must compute it)` },
    { status: 400 });

  const { error: runErr } = await db.from("runs").insert(exp.run);
  if (runErr) return NextResponse.json({ error: runErr.message }, { status: 500 });
  if (exp.recommendations.length) {
    const { error } = await db.from("recommendations").insert(exp.recommendations);
    if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  }
  // open a paper trade per fresh recommendation (entry/stop/first target)
  const trades = exp.recommendations.map((r) => ({
    recommendation_id: r.id, ticker: r.ticker,
    entry: r.entry_high, stop: r.stop_loss,
    target: r.targets?.[0]?.level ?? null, status: "open",
  }));
  if (trades.length) await db.from("paper_trades").insert(trades);
  return NextResponse.json({ ok: true, ingested: exp.recommendations.length });
}

// POST /api/paper/mark  -> mark open paper trades against fresh prices.
//
// Marking uses the day's HIGH and LOW, not just the close, because within a day
// price can hit the stop OR the target first. When both are touched in the same
// bar we resolve conservatively to the STOP (worst-case ordering) — the same
// honest rule the Python backtester uses. Naive close-only marking overstates
// results and is a classic way paper records lie.
import { NextRequest, NextResponse } from "next/server";
import { requireAutomationToken } from "@/lib/auth";
import { hasSupabaseServerConfig, supabaseServer } from "@/lib/supabase";

interface Bar { high: number; low: number; close: number; } // from your data source

async function fetchBar(ticker: string): Promise<Bar | null> {
  // TODO: wire your chosen market-data API (Finnhub/Polygon/yfinance). Must
  // return today's high/low/close. Returning null => leave the trade open
  // (never mark on missing data — fail safe).
  return null;
}

export async function POST(req: NextRequest) {
  const authError = requireAutomationToken(req);
  if (authError) return authError;
  if (!hasSupabaseServerConfig()) {
    return NextResponse.json({ error: "Supabase env vars are not configured" }, { status: 503 });
  }

  const db = supabaseServer();
  const { data: open } = await db.from("paper_trades").select("*").eq("status", "open");
  let marked = 0;
  for (const t of open ?? []) {
    const bar = await fetchBar(t.ticker);
    if (!bar) continue; // fail safe on missing data
    const risk = t.entry - t.stop;
    if (risk <= 0) continue;
    const hitStop = bar.low <= t.stop;
    const hitTarget = t.target != null && bar.high >= t.target;
    let status: string | null = null, result_r: number | null = null, reason: string | null = null;
    if (hitStop) { status = "hit_stop"; result_r = -1; reason = "stop"; }        // conservative: stop wins ties
    else if (hitTarget) { status = "hit_target"; result_r = (t.target - t.entry) / risk; reason = "t1"; }
    if (status) {
      await db.from("paper_trades").update({
        status, result_r, exit_reason: reason, closed_at: new Date().toISOString(),
      }).eq("id", t.id);
      marked++;
    }
  }
  return NextResponse.json({ ok: true, marked });
}

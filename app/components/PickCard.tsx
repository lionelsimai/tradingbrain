"use client";
import { useState } from "react";
import type { Recommendation } from "@/lib/types";

const bandColor: Record<string, string> = {
  strong: "bg-emerald-100 text-emerald-800",
  moderate: "bg-amber-100 text-amber-800",
  weak: "bg-slate-100 text-slate-700",
};

export function PickCard({ rec }: { rec: Recommendation }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-slate-200 p-4 shadow-sm">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-lg font-semibold">{rec.ticker}</span>
          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${bandColor[rec.conviction_band] ?? ""}`}>
            {rec.conviction_band} · {rec.conviction_score}
          </span>
          <span className="text-sm text-slate-500">{rec.direction} · R:R {rec.reward_to_risk}</span>
        </div>
        <span className="text-slate-400">{open ? "–" : "+"}</span>
      </button>

      {open && (
        <div className="mt-4 space-y-3 text-sm">
          <div className="grid grid-cols-3 gap-2">
            <Stat label="Entry" value={`${rec.entry_low}–${rec.entry_high}`} />
            <Stat label="Stop" value={`${rec.stop_loss}`} />
            <Stat label="Target" value={`${rec.targets?.[0]?.level ?? "—"}`} />
          </div>
          <p><span className="font-medium">Thesis. </span>{rec.thesis}</p>
          <p><span className="font-medium">Invalidation. </span>{rec.invalidation}</p>
          {rec.key_risks?.length > 0 && (
            <div>
              <span className="font-medium">Bear case.</span>
              <ul className="ml-4 list-disc">{rec.key_risks.map((k, i) => <li key={i}>{k}</li>)}</ul>
            </div>
          )}
          <p className="rounded-lg bg-amber-50 p-2 text-xs text-amber-900">
            Risk: {rec.confidence_caveats}
          </p>
          <p className="text-xs text-slate-400">{rec.data_freshness}</p>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-slate-50 p-2">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="font-medium">{value}</div>
    </div>
  );
}

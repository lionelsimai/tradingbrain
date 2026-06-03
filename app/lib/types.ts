// TradingBrain app types — mirror app/supabase/schema.sql exactly.
export type Pillar = "bullish" | "bearish" | "neutral" | string;

export interface Run {
  id: string;
  ran_at: string;
  market_read: string;
  tickers_scanned: number | null;
  picks_generated: number;
  conviction_cap_active: boolean | null; // true => no pick may be "strong"
  live_trades_on_record: number | null;
  gauntlet_verdict: "APPROVED" | "CONDITIONAL" | "REJECTED" | null;
  go_live_verdict: "CLEARED FOR LIVE" | "BLOCKED" | null;
  survivorship_warning: string | null;
  disclaimer: string | null;
}

export interface Recommendation {
  id: string;
  run_id: string;
  ticker: string;
  asset_class: "equity" | "crypto";
  direction: "long" | "short";
  conviction_score: number;           // capped at 60 while no live track record
  conviction_band: "strong" | "moderate" | "weak";
  time_horizon: string;
  entry_low: number; entry_high: number;
  stop_loss: number;
  targets: { level: number; rationale: string }[];
  reward_to_risk: number;
  position_size: { shares_or_units: number; dollar_risk: number; percent_of_equity: number };
  thesis: string;
  pillar_reads: Record<string, string>;
  key_risks: string[];
  invalidation: string;
  confidence_caveats: string;
  data_freshness: string;
}

export interface PaperTrade {
  id: string;
  recommendation_id: string | null;
  source_signal_id?: string;
  ticker: string;
  entry: number; stop: number; target: number;
  status: "open" | "hit_target" | "hit_stop" | "timeout";
  opened_at: string; closed_at: string | null;
  result_r: number | null;
  mfe_r: number | null; mae_r: number | null;
  exit_reason: string | null;
  source?: "live" | "paper" | "replay" | string;
}

export interface EvidenceSummary {
  paper_open: number;
  paper_resolved: number;
  live_open: number;
  live_resolved: number;
  forward_open: number;
  forward_resolved: number;
  replay_open: number;
  replay_resolved: number;
  paper_trades_are_forward_only: boolean;
  note: string;
}

export interface AppExport {
  run: Run;
  recommendations: Recommendation[];
  paper_trades: PaperTrade[];
  live_trades?: PaperTrade[];
  replay_trades?: PaperTrade[];
  evidence_summary?: EvidenceSummary;
  watch_list: { ticker: string; setup: string; why_not: string; trigger: string }[];
  no_qualifying_setups: boolean;
}

export interface MissionDashboardData {
  asof: string;
  mission: {
    name: string;
    mode: string;
    liveStatus: string;
    verdict: string;
    goLive: string;
    posture: string;
    marketRead: string;
    disclaimer: string;
  };
  scores: Record<string, number>;
  blockers: {
    critical: string[];
    goLive: string[];
    execution: string[];
    nextAction: string;
  };
  account: {
    status: string;
    equity: number;
    cash: number;
    buyingPower: number;
    marketOpen: boolean;
    nextOpen: string;
    openOrders: { symbol: string; status: string }[];
    selectedSymbols: string[];
    ordersSubmitted: number;
  };
  evidence: {
    paperOpen: number;
    paperResolved: number;
    forwardResolved: number;
    liveResolved: number;
    replayResolved: number;
    scorecardResolved: number;
    scorecardVerdict: string;
    scorecardDrift: string;
  };
  narrative: {
    candidateTop3: string[];
    watchlistTop3: string[];
    events: {
      ticker: string;
      title: string;
      signal: string;
      confidence: number;
      chaseRisk: number;
      sourceScore: number;
    }[];
  };
  skillLab: {
    bestSkill: string;
    bestScore: number;
    verdict: string;
    currentTop3: string[];
    ensembleTop3: string[];
    simulatedReturnPct: number;
    simulatedMaxDrawdownPct: number;
    simulatedDollars: number;
  };
  dataQuality: {
    pass: boolean;
    warnings: string[];
    tickersWithIssues: number;
    tickers: number;
  };
  gates: {
    name: string;
    status: string;
    detail: string;
    tone: "green" | "amber" | "red" | "slate";
  }[];
  recommendations: Recommendation[];
}

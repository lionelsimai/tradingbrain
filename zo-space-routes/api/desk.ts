// zo.space API route — path: /api/desk
// Aggregates all 11 brain layers from reports/*.json into one payload for the desk.
import type { Context } from "hono";
import { readFile, stat } from "node:fs/promises";

const R = "/home/workspace/TradingBrain/reports";

async function readJSON(name: string): Promise<any> {
  try {
    const txt = await readFile(`${R}/${name}`, "utf-8");
    return JSON.parse(txt);
  } catch {
    return null;
  }
}

async function ageMin(name: string): Promise<number | null> {
  try {
    const s = await stat(`${R}/${name}`);
    return Math.round((Date.now() - s.mtimeMs) / 60000);
  } catch {
    return null;
  }
}

export default async (c: Context) => {
  const [
    regime, desk, picks, swing, sells, movers, calib, research, circuit, alloc, scorecard,
  ] = await Promise.all([
    readJSON("hmm-regime.json"),
    readJSON("desk-signals.json"),
    readJSON("realtime-picks-latest.json"),
    readJSON("swing-setups.json"),
    readJSON("sell-signals-latest.json"),
    readJSON("market-movers-latest.json"),
    readJSON("calibration.json"),
    readJSON("research-report.json"),
    readJSON("circuit-breakers.json"),
    readJSON("allocation.json"),
    readJSON("live-scorecard.json"),
  ]);

  const ages = Object.fromEntries(
    await Promise.all(
      ["hmm-regime.json", "desk-signals.json", "realtime-picks-latest.json",
       "market-movers-latest.json"].map(async (n) => [n, await ageMin(n)]),
    ),
  );

  const L1_regime = regime
    ? { label: regime.acted_label, raw_label: regime.raw_label, exposure: regime.target_exposure,
        stability: regime.stability, volatile: regime.volatile_warning,
        posterior: regime.raw_posterior, features: regime.features_today, asof: regime.asof }
    : null;

  const L2_buys = desk
    ? { buys: desk.buys ?? [], watchlist: desk.watchlist ?? [], n_graded: desk.n_graded,
        ranked: (desk.ranked ?? []).slice(0, 20), asof: desk.asof }
    : null;

  const L3_setups = swing
    ? { candidates: (swing.candidates ?? []).slice(0, 12), blackout: swing.blackout ?? [],
        snap_used: swing.snap_used, asof: swing.asof }
    : null;

  const L4_picks = picks
    ? { picks: picks.picks ?? [], regime: picks.regime, exposure: picks.target_exposure,
        market: picks.market_status, sgt: picks.asof_sgt, et: picks.asof_et }
    : null;

  const L5_sells = sells
    ? { positions: sells.positions ?? [], note: sells.note, asof: sells.asof }
    : null;

  const L6_movers = movers
    ? { items: (movers.items ?? []).slice(0, 40), counts: movers.counts, asof: movers.asof }
    : null;

  const L7_strategies = research
    ? {
        data_quality: research.data_quality,
        cost_R: research.cost_R_per_trade,
        strategies: Object.fromEntries(
          Object.entries(research.strategies ?? {}).map(([k, v]: any) => [
            k,
            { verdict: v.verdict, full_exp: v.full?.expectancy_R, oos_exp: v.out_of_sample?.expectancy_R,
              wfe: v.walk_forward_efficiency, win: v.full?.win_rate, n: v.full?.n,
              ci: v.bootstrap_ci_expectancy_R, deflated_sharpe: v.deflated_sharpe },
          ]),
        ),
      }
    : null;

  const themeMap: Record<string, { count: number; avg_rr: number; tickers: string[] }> = {};
  for (const r of desk?.ranked ?? []) {
    const th = r.theme ?? "other";
    if (!themeMap[th]) themeMap[th] = { count: 0, avg_rr: 0, tickers: [] };
    themeMap[th].count++;
    themeMap[th].avg_rr += r.rr ?? 0;
    if (themeMap[th].tickers.length < 5) themeMap[th].tickers.push(r.ticker);
  }
  for (const k of Object.keys(themeMap)) {
    themeMap[k].avg_rr = +(themeMap[k].avg_rr / themeMap[k].count).toFixed(2);
  }

  const L9_risk = { circuit: circuit ?? null, allocation: alloc ?? null,
    exposure_target: regime?.target_exposure ?? null };

  const L10_calib = calib
    ? { source: calib.source, calibration: calib.calibration, asof: calib.asof }
    : null;

  const L11_scorecard = scorecard
    ? { overall: scorecard.overall, by_setup: scorecard.by_setup, by_grade: scorecard.by_grade,
        verdict: scorecard.verdict, resolved: scorecard.resolved, open: scorecard.open, asof: scorecard.asof }
    : null;

  return c.json(
    {
      updatedAt: new Date().toISOString(),
      freshness: ages,
      layers: {
        regime: L1_regime, buy_signals: L2_buys, swing_setups: L3_setups,
        momentum_picks: L4_picks, sell_signals: L5_sells, market_movers: L6_movers,
        strategy_lab: L7_strategies, theme_heatmap: themeMap, risk: L9_risk,
        calibration: L10_calib, live_scorecard: L11_scorecard,
      },
    },
    200,
    { "Cache-Control": "no-store" },
  );
};

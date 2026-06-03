// zo.space PAGE route — path: /trading-desk (private)
// 10-layer real-time trading desk. Polls /api/desk every 30s.
import { useEffect, useState } from "react";
import {
  Activity, TrendingUp, TrendingDown, Layers, Newspaper, FlaskConical,
  Grid3x3, ShieldAlert, Gauge, Target, Radio, Clock, ArrowUpRight,
  ArrowDownRight, Minus, AlertTriangle, CheckCircle2, XCircle,
} from "lucide-react";

const theme = {
  bg: "#0a0e14", panel: "#111722", border: "#1e2733", fg: "#e6edf3",
  muted: "#7d8895", green: "#3fb950", red: "#f85149", amber: "#d29922",
  blue: "#58a6ff", purple: "#bc8cff", accent: "#d8a657",
};

type Desk = any;

function useDesk() {
  const [data, setData] = useState<Desk | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const r = await fetch("/api/desk", { headers: { Accept: "application/json" } });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const j = await r.json();
        if (alive) { setData(j); setErr(null); }
      } catch (e: any) {
        if (alive) setErr(String(e.message ?? e));
      }
    };
    load();
    const id = setInterval(load, 30000);
    return () => { alive = false; clearInterval(id); };
  }, []);
  return { data, err };
}

function Panel({ icon: Icon, title, sub, children, accent }: any) {
  return (
    <div style={{ background: theme.panel, border: `1px solid ${theme.border}`,
      borderRadius: 10, padding: 14, display: "flex", flexDirection: "column", minHeight: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <Icon size={15} style={{ color: accent ?? theme.blue }} />
        <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: 0.5,
          textTransform: "uppercase", color: theme.fg }}>{title}</span>
        {sub && <span style={{ fontSize: 10, color: theme.muted, marginLeft: "auto" }}>{sub}</span>}
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: "auto" }}>{children}</div>
    </div>
  );
}

function Pill({ text, color }: { text: string; color: string }) {
  return <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 5,
    background: color + "22", color, border: `1px solid ${color}44` }}>{text}</span>;
}

const fmt = (n: any, d = 2) => (typeof n === "number" ? n.toFixed(d) : "—");

export default function TradingDesk() {
  const { data, err } = useDesk();
  const [now, setNow] = useState(new Date());
  useEffect(() => { const id = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(id); }, []);

  const L = data?.layers ?? {};
  const sgt = now.toLocaleTimeString("en-US", { timeZone: "Asia/Singapore", hour12: false });
  const et = now.toLocaleTimeString("en-US", { timeZone: "America/New_York", hour12: false });

  const regime = L.regime;
  const regimeColor = regime?.label === "Bull" || regime?.label === "Euphoria" ? theme.green
    : regime?.label === "Bear" || regime?.label === "Crash" ? theme.red : theme.amber;

  return (
    <div style={{ minHeight: "100vh", background: theme.bg, color: theme.fg,
      fontFamily: "ui-monospace, 'SF Mono', Menlo, monospace", padding: 14 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 14,
        flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Activity size={20} style={{ color: theme.accent }} />
          <span style={{ fontSize: 16, fontWeight: 800, letterSpacing: 1 }}>TRADINGBRAIN · DESK</span>
        </div>
        {regime && (
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Pill text={`REGIME: ${regime.label?.toUpperCase()}`} color={regimeColor} />
            <Pill text={`EXPOSURE ${Math.round((regime.exposure ?? 0) * 100)}%`} color={theme.blue} />
            {regime.volatile && <Pill text="VOLATILE" color={theme.amber} />}
          </div>
        )}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 14,
          fontSize: 11, color: theme.muted }}>
          <span><Clock size={11} style={{ display: "inline", marginRight: 4 }} />SGT {sgt}</span>
          <span>ET {et}</span>
          <span style={{ color: err ? theme.red : theme.green }}>
            <Radio size={11} style={{ display: "inline", marginRight: 4 }} />
            {err ? "RECONNECTING" : "LIVE · 30s"}
          </span>
        </div>
      </div>

      {!data && !err && <div style={{ color: theme.muted, padding: 40, textAlign: "center" }}>Loading desk…</div>}

      {data && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(12, 1fr)", gap: 12,
          gridAutoRows: "minmax(240px, auto)" }}>
          {/* L11 Live scorecard — the brain's REAL track record (full width, top) */}
          <div style={{ gridColumn: "span 12" }}>
            <Panel icon={CheckCircle2} title="11 · Live Forward-Test Scorecard"
              accent={(L.live_scorecard?.overall?.expectancy_R ?? 0) > 0 ? theme.green : theme.red}
              sub={L.live_scorecard ? `${L.live_scorecard.resolved} resolved · ${L.live_scorecard.open} open` : ""}>
              {L.live_scorecard ? (
                <div style={{ display: "flex", gap: 20, flexWrap: "wrap", alignItems: "flex-start" }}>
                  <div style={{ minWidth: 200 }}>
                    <div style={{ fontSize: 26, fontWeight: 800,
                      color: (L.live_scorecard.overall?.expectancy_R ?? 0) > 0 ? theme.green : theme.red }}>
                      {fmt(L.live_scorecard.overall?.expectancy_R, 3)}R
                    </div>
                    <div style={{ fontSize: 11, color: theme.muted, marginBottom: 6 }}>
                      realized expectancy · {fmt(L.live_scorecard.overall?.win_rate, 1)}% win · PF {fmt(L.live_scorecard.overall?.profit_factor, 2)} · {fmt(L.live_scorecard.overall?.avg_hold_days, 1)}d avg hold
                    </div>
                    <div style={{ fontSize: 10.5, color: (L.live_scorecard.overall?.expectancy_R ?? 0) > 0 ? theme.green : theme.red,
                      fontWeight: 700 }}>{L.live_scorecard.verdict}</div>
                  </div>
                  <table style={{ fontSize: 10.5, borderCollapse: "collapse", flex: 1, minWidth: 360 }}>
                    <thead><tr style={{ color: theme.muted, textAlign: "left" }}>
                      <th>SETUP</th><th>n</th><th>win</th><th>LIVE</th><th>BACKTEST</th><th>DRIFT</th>
                    </tr></thead>
                    <tbody>
                      {Object.entries(L.live_scorecard.by_setup ?? {})
                        .sort((a: any, b: any) => (b[1].expectancy_R ?? 0) - (a[1].expectancy_R ?? 0))
                        .map(([k, v]: any) => (
                        <tr key={k} style={{ borderTop: `1px solid ${theme.border}` }}>
                          <td style={{ padding: "3px 0" }}>{k}</td>
                          <td style={{ color: theme.muted }}>{v.n}</td>
                          <td>{fmt(v.win_rate, 0)}%</td>
                          <td style={{ color: (v.expectancy_R ?? 0) > 0 ? theme.green : theme.red, fontWeight: 700 }}>
                            {fmt(v.expectancy_R, 2)}R</td>
                          <td style={{ color: theme.muted }}>{fmt(v.backtest_expectancy_R, 2)}R</td>
                          <td style={{ color: (v.drift_R ?? 0) >= 0 ? theme.green : theme.red }}>
                            {v.drift_R != null ? (v.drift_R >= 0 ? "+" : "") + fmt(v.drift_R, 2) : "—"}
                            {v.expectancy_R < -0.05 && v.n >= 25 && <span style={{ color: theme.red }}> ⛔</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <div style={{ color: theme.muted, fontSize: 11 }}>No scorecard yet — signals accumulating.</div>}
            </Panel>
          </div>

          {/* L1 Regime */}
          <div style={{ gridColumn: "span 3" }}>
            <Panel icon={Gauge} title="1 · Regime" sub={regime?.asof} accent={regimeColor}>
              {regime && (
                <div>
                  <div style={{ fontSize: 28, fontWeight: 800, color: regimeColor }}>{regime.label}</div>
                  <div style={{ fontSize: 11, color: theme.muted, marginBottom: 10 }}>
                    target exposure {Math.round((regime.exposure ?? 0) * 100)}% · {regime.stability}
                  </div>
                  {Object.entries(regime.posterior ?? {}).map(([k, v]: any) => (
                    <div key={k} style={{ marginBottom: 5 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10 }}>
                        <span style={{ color: theme.muted }}>{k}</span><span>{(v * 100).toFixed(0)}%</span>
                      </div>
                      <div style={{ height: 4, background: theme.border, borderRadius: 2 }}>
                        <div style={{ width: `${v * 100}%`, height: "100%", borderRadius: 2,
                          background: k === "Bull" || k === "Euphoria" ? theme.green
                            : k === "Bear" || k === "Crash" ? theme.red : theme.amber }} />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Panel>
          </div>

          {/* L2 Buy signals */}
          <div style={{ gridColumn: "span 6" }}>
            <Panel icon={Target} title="2 · Doctrine Buy Signals" accent={theme.green}
              sub={`${L.buy_signals?.n_graded ?? 0} graded`}>
              {(L.buy_signals?.buys?.length ?? 0) === 0 && (
                <div style={{ color: theme.amber, fontSize: 11 }}>No A/B-grade longs clear the bar. No-trade is respectable.</div>
              )}
              <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
                <thead><tr style={{ color: theme.muted, textAlign: "left" }}>
                  <th>TKR</th><th>GR</th><th>R/R</th><th>ENTRY</th><th>STOP</th><th>T1</th><th>SIZE</th>
                </tr></thead>
                <tbody>
                  {(L.buy_signals?.buys ?? []).map((b: any) => (
                    <tr key={b.ticker} style={{ borderTop: `1px solid ${theme.border}` }}>
                      <td style={{ fontWeight: 700, color: theme.green, padding: "4px 0" }}>{b.ticker}</td>
                      <td><Pill text={b.grade} color={theme.green} /></td>
                      <td style={{ color: theme.accent, fontWeight: 700 }}>{fmt(b.rr, 1)}</td>
                      <td>${fmt(b.entry)}</td><td style={{ color: theme.red }}>${fmt(b.stop)}</td>
                      <td style={{ color: theme.green }}>${fmt(b.t1)}</td>
                      <td style={{ fontSize: 10, color: theme.muted }}>{b.size}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {(L.buy_signals?.watchlist?.length ?? 0) > 0 && (
                <div style={{ marginTop: 10, fontSize: 10, color: theme.muted }}>
                  WATCH: {L.buy_signals.watchlist.map((w: any) => `${w.ticker} (R/R ${fmt(w.rr, 1)})`).join(" · ")}
                </div>
              )}
            </Panel>
          </div>

          {/* L7 Strategy lab */}
          <div style={{ gridColumn: "span 3" }}>
            <Panel icon={FlaskConical} title="7 · Strategy Lab" accent={theme.purple}
              sub={L.strategy_lab?.data_quality?.survivorship_free ? "validated" : "indicative"}>
              <table style={{ width: "100%", fontSize: 10.5, borderCollapse: "collapse" }}>
                <thead><tr style={{ color: theme.muted, textAlign: "left" }}>
                  <th>STRATEGY</th><th>OOS</th><th></th>
                </tr></thead>
                <tbody>
                  {Object.entries(L.strategy_lab?.strategies ?? {}).map(([k, v]: any) => (
                    <tr key={k} style={{ borderTop: `1px solid ${theme.border}` }}>
                      <td style={{ padding: "3px 0", fontSize: 9.5 }}>{k}</td>
                      <td style={{ color: (v.oos_exp ?? 0) > 0 ? theme.green : theme.red }}>{fmt(v.oos_exp, 2)}R</td>
                      <td><Pill text={v.verdict} color={v.verdict === "Deploy" ? theme.green
                        : v.verdict === "Iterate" ? theme.amber : theme.red} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          </div>

          {/* L3 Momentum picks */}
          <div style={{ gridColumn: "span 4" }}>
            <Panel icon={TrendingUp} title="3 · Momentum Picks" accent={theme.blue}
              sub={L.momentum_picks?.market}>
              {(L.momentum_picks?.picks ?? []).slice(0, 8).map((p: any, i: number) => (
                <div key={p.ticker} style={{ display: "flex", alignItems: "center", gap: 8,
                  padding: "4px 0", borderTop: i ? `1px solid ${theme.border}` : "none", fontSize: 11 }}>
                  <span style={{ fontWeight: 700, width: 46 }}>{p.ticker}</span>
                  <span style={{ color: theme.muted, fontSize: 10, flex: 1 }}>{p.subcategory ?? p.theme}</span>
                  <span style={{ color: theme.accent, fontSize: 10 }}>{p.setup}</span>
                  {p.winrate_10d && <Pill text={`${Math.round(p.winrate_10d)}%`} color={theme.green} />}
                </div>
              ))}
            </Panel>
          </div>

          {/* L4 Swing setups */}
          <div style={{ gridColumn: "span 4" }}>
            <Panel icon={Layers} title="4 · Swing Setups" accent={theme.accent}
              sub={`${L.swing_setups?.blackout?.length ?? 0} earnings-blocked`}>
              {(L.swing_setups?.candidates ?? []).slice(0, 8).map((s: any, i: number) => (
                <div key={s.ticker + i} style={{ display: "flex", alignItems: "center", gap: 8,
                  padding: "4px 0", borderTop: i ? `1px solid ${theme.border}` : "none", fontSize: 11 }}>
                  <span style={{ fontWeight: 700, width: 50 }}>{s.ticker}</span>
                  <span style={{ color: theme.accent, fontSize: 10, flex: 1 }}>{s.setup}</span>
                  <span style={{ color: theme.muted, fontSize: 10 }}>score {fmt(s.score, 2)}</span>
                </div>
              ))}
            </Panel>
          </div>

          {/* L5 Sell signals */}
          <div style={{ gridColumn: "span 4" }}>
            <Panel icon={TrendingDown} title="5 · Exit Signals" accent={theme.red}>
              {(L.sell_signals?.positions?.length ?? 0) === 0 && (
                <div style={{ color: theme.muted, fontSize: 11 }}>
                  {L.sell_signals?.note ?? "No positions configured. Add holdings in config/holdings.yaml."}
                </div>
              )}
              {(L.sell_signals?.positions ?? []).map((p: any, i: number) => (
                <div key={p.ticker + i} style={{ display: "flex", alignItems: "center", gap: 8,
                  padding: "4px 0", borderTop: i ? `1px solid ${theme.border}` : "none", fontSize: 11 }}>
                  <span style={{ fontWeight: 700, width: 50 }}>{p.ticker}</span>
                  <Pill text={p.action ?? "—"} color={p.action === "SELL" ? theme.red
                    : p.action === "TRIM" ? theme.amber : theme.green} />
                  <span style={{ color: theme.muted, fontSize: 10, flex: 1 }}>{p.reason}</span>
                </div>
              ))}
            </Panel>
          </div>

          {/* L8 Theme heatmap */}
          <div style={{ gridColumn: "span 4" }}>
            <Panel icon={Grid3x3} title="8 · Theme Heatmap" accent={theme.purple}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                {Object.entries(L.theme_heatmap ?? {}).sort((a: any, b: any) => b[1].avg_rr - a[1].avg_rr)
                  .map(([k, v]: any) => (
                  <div key={k} style={{ background: theme.bg, borderRadius: 6, padding: 8,
                    border: `1px solid ${theme.border}` }}>
                    <div style={{ fontSize: 9.5, color: theme.muted, marginBottom: 3 }}>{k}</div>
                    <div style={{ fontSize: 14, fontWeight: 700,
                      color: v.avg_rr >= 2 ? theme.green : v.avg_rr >= 1 ? theme.amber : theme.red }}>
                      {fmt(v.avg_rr, 1)} <span style={{ fontSize: 9, color: theme.muted }}>avg R/R</span>
                    </div>
                    <div style={{ fontSize: 9, color: theme.muted }}>{v.tickers.join(" ")}</div>
                  </div>
                ))}
              </div>
            </Panel>
          </div>

          {/* L9 Risk */}
          <div style={{ gridColumn: "span 4" }}>
            <Panel icon={ShieldAlert} title="9 · Risk & Circuit Breakers" accent={theme.amber}>
              <div style={{ fontSize: 11 }}>
                <div style={{ display: "flex", justifyContent: "space-between", padding: "4px 0" }}>
                  <span style={{ color: theme.muted }}>Target exposure</span>
                  <span style={{ fontWeight: 700 }}>{Math.round((L.risk?.exposure_target ?? 0) * 100)}%</span>
                </div>
                {L.risk?.circuit && Object.entries(L.risk.circuit).slice(0, 6).map(([k, v]: any) => (
                  <div key={k} style={{ display: "flex", justifyContent: "space-between",
                    padding: "4px 0", borderTop: `1px solid ${theme.border}` }}>
                    <span style={{ color: theme.muted, fontSize: 10 }}>{k}</span>
                    <span style={{ fontSize: 10 }}>{typeof v === "object" ? JSON.stringify(v).slice(0, 24) : String(v)}</span>
                  </div>
                ))}
              </div>
            </Panel>
          </div>

          {/* L6 Market movers */}
          <div style={{ gridColumn: "span 8" }}>
            <Panel icon={Newspaper} title="6 · Market Movers" accent={theme.blue}
              sub={`${L.market_movers?.counts?.high ?? 0} high-impact`}>
              {(L.market_movers?.items ?? []).slice(0, 12).map((m: any, i: number) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 8,
                  padding: "4px 0", borderTop: i ? `1px solid ${theme.border}` : "none", fontSize: 11 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 4, flexShrink: 0,
                    background: m.impact === "HIGH" ? theme.red : m.impact === "MED" ? theme.amber : theme.muted }} />
                  <span style={{ fontSize: 9, color: theme.muted, width: 44, flexShrink: 0 }}>{m.kind}</span>
                  {m.tickers?.length > 0 && <span style={{ fontWeight: 700, color: theme.accent,
                    fontSize: 10, flexShrink: 0 }}>{m.tickers.join(",")}</span>}
                  <span style={{ color: theme.fg, overflow: "hidden", textOverflow: "ellipsis",
                    whiteSpace: "nowrap" }}>{m.headline}</span>
                </div>
              ))}
            </Panel>
          </div>

          {/* L10 Calibration */}
          <div style={{ gridColumn: "span 4" }}>
            <Panel icon={CheckCircle2} title="10 · Calibration" accent={theme.green}
              sub={L.calibration?.source}>
              <table style={{ width: "100%", fontSize: 10.5, borderCollapse: "collapse" }}>
                <thead><tr style={{ color: theme.muted, textAlign: "left" }}>
                  <th>SETUP</th><th>OOS exp</th><th>win</th>
                </tr></thead>
                <tbody>
                  {Object.entries(L.calibration?.calibration ?? {}).map(([k, v]: any) => (
                    <tr key={k} style={{ borderTop: `1px solid ${theme.border}` }}>
                      <td style={{ padding: "3px 0", fontSize: 9.5 }}>{k}</td>
                      <td style={{ color: (v.oos_expectancy_R ?? v.expectancy_R ?? 0) > 0 ? theme.green : theme.red }}>
                        {fmt(v.oos_expectancy_R ?? v.expectancy_R, 2)}R</td>
                      <td>{fmt(v.win_rate, 0)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          </div>
        </div>
      )}

      <div style={{ marginTop: 14, fontSize: 10, color: theme.muted, textAlign: "center" }}>
        Paper-only · backtest edge {L.strategy_lab?.data_quality?.survivorship_free ? "validated" : "INDICATIVE (survivorship-biased)"} · not financial advice
      </div>
    </div>
  );
}

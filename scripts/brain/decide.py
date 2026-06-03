#!/usr/bin/env python3
"""The Brain: fuses all signals + macro regime into a ranked watchlist.

Inputs read from knowledge.duckdb + prices.duckdb:
  - signals (momentum, value_quality, insider_buy_cluster, news_burst)
  - macro_series (VIX, 10Y yield, yield curve)
  - documents (recent context, used by the LLM rationale layer if enabled)

Output:
  - One row per ticker per day in `watchlist` (rank, action, confidence, rationale)
  - Decision rows in `decisions` for actionable BUY/SELL calls
  - Prints + saves a markdown digest to reports/<date>-digest.md
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from datetime import date, datetime
from pathlib import Path
import duckdb, numpy as np, pandas as pd, yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import kb, PRICES_DB  # noqa: E402

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
SOURCES = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text())
WEIGHTS = SOURCES["weights"]
RULES = SOURCES["risk_rules"]
REPORTS = ROOT / "reports"
REPORTS.mkdir(exist_ok=True)

# Ticker → sector mapping from universe.yaml (for dashboard grouping).
_UNI = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text())
TICKER_SECTOR: dict[str, str] = {}
for _cat, _tks in _UNI.get("universe", {}).items():
    for _t in _tks:
        TICKER_SECTOR[_t] = _cat


def latest_momentum() -> pd.DataFrame:
    p = ROOT / "data" / "momentum.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    return df.rename(columns={"score": "momentum_score"})


def latest_signal(con, name: str) -> pd.DataFrame:
    df = con.execute(
        """SELECT ticker, value AS v, rank AS r, metadata
           FROM signals
           WHERE signal_date = (SELECT MAX(signal_date) FROM signals WHERE signal_name = ?)
             AND signal_name = ?""",
        [name, name]
    ).fetch_df()
    return df


def macro_snapshot(con) -> dict:
    out = {}
    for sid in ("DGS10", "DGS3MO", "VIXCLS", "DEXUSEU"):
        r = con.execute(
            "SELECT observation_date, value FROM macro_series WHERE series_id = ? ORDER BY observation_date DESC LIMIT 1",
            [sid]
        ).fetchone()
        if r:
            out[sid] = {"date": str(r[0]), "value": float(r[1])}
    # SPY regime from prices.duckdb
    pc = duckdb.connect(str(PRICES_DB), read_only=True)
    spy = pc.execute(
        "SELECT date, adj_close FROM prices WHERE ticker = 'SPY' ORDER BY date DESC LIMIT 220"
    ).fetch_df().iloc[::-1].reset_index(drop=True)
    pc.close()
    if len(spy) >= 200:
        ma200 = float(spy["adj_close"].tail(200).mean())
        close = float(spy["adj_close"].iloc[-1])
        out["SPY"] = {"close": close, "ma200": ma200, "above": close > ma200,
                       "pct_vs_ma200": round((close / ma200 - 1) * 100, 2)}
    return out


def regime_score(macro: dict) -> tuple[float, str]:
    """Return (0..1, label). Used to scale confidence and gate buys."""
    spy_ok = macro.get("SPY", {}).get("above", False)
    vix = macro.get("VIXCLS", {}).get("value", 20)
    score = 0.5
    if spy_ok:
        score += 0.3
    else:
        score -= 0.2
    if vix < 18:
        score += 0.15
    elif vix > 30:
        score -= 0.25
    elif vix > 22:
        score -= 0.10
    score = max(0.0, min(1.0, score))
    label = "BULL" if score >= 0.65 else "MIXED" if score >= 0.4 else "RISK-OFF"
    return score, label


def normalise(s: pd.Series) -> pd.Series:
    s = s.fillna(0)
    if s.std() == 0:
        return pd.Series(np.zeros(len(s)), index=s.index)
    return ((s - s.mean()) / s.std()).clip(-3, 3)


def fuse(momo: pd.DataFrame, vq: pd.DataFrame, insider: pd.DataFrame, news: pd.DataFrame,
         x: pd.DataFrame, regime: float) -> pd.DataFrame:
    df = momo[["ticker", "momentum_score", "close", "passes_filters", "atr_pct"]].copy() if not momo.empty else pd.DataFrame()
    if df.empty:
        return df

    # Pull value/quality
    if not vq.empty:
        vq_map = vq.set_index("ticker")["v"].to_dict()
        df["vq_score"] = df["ticker"].map(vq_map).fillna(0)
    else:
        df["vq_score"] = 0

    # Insider score
    if not insider.empty:
        ins_map = insider.set_index("ticker")["v"].to_dict()
        df["insider_score"] = df["ticker"].map(ins_map).fillna(0)
    else:
        df["insider_score"] = 0

    # News burst
    if not news.empty:
        nb_map = news.set_index("ticker")["v"].to_dict()
        df["news_burst"] = df["ticker"].map(nb_map).fillna(0)
    else:
        df["news_burst"] = 0

    if not x.empty:
        x_map = x.set_index("ticker")["v"].to_dict()
        df["x_score"] = df["ticker"].map(x_map).fillna(0)
    else:
        df["x_score"] = 0

    # Normalise each, then weight per sources.yaml.
    df["z_momo"]    = normalise(df["momentum_score"])
    df["z_vq"]      = normalise(df["vq_score"])
    df["z_insider"] = normalise(df["insider_score"])
    df["z_news"]    = normalise(df["news_burst"])
    df["z_x"]       = normalise(df["x_score"])

    df["composite"] = (
        WEIGHTS["signals_quantitative"] * df["z_momo"] +    # quant momentum
        WEIGHTS["tier_1_fundamentals"]  * (0.6 * df["z_insider"] + 0.4 * df["z_vq"]) +
        WEIGHTS["tier_3_qualitative"]   * df["z_news"] * 0.5 +    # weak signal — discount
        WEIGHTS["tier_4_sentiment"]     * (0.7 * df["z_x"] + 0.3 * df["z_news"])
    )
    # Regime tilts composite up/down.
    df["composite"] = df["composite"] * (0.7 + 0.6 * regime)

    # Confidence = squashed composite + filter compliance.
    df["confidence"] = np.tanh(df["composite"]).clip(-1, 1) * 0.5 + 0.5
    df.loc[~df["passes_filters"].fillna(False), "confidence"] *= 0.6
    df["confidence"] = df["confidence"].round(3)
    return df.sort_values("composite", ascending=False).reset_index(drop=True)


def decide_action(row, regime_label: str) -> tuple[str, str]:
    """Translate signals into BUY / WATCH / HOLD / SELL with a plain-English why."""
    conf = float(row["confidence"])
    min_conf = RULES["min_confidence"]
    reasons = []
    if row.get("z_momo", 0) > 0.5:
        reasons.append(f"momentum top-quartile (z={row['z_momo']:+.2f})")
    if row.get("z_vq", 0) > 0.5:
        reasons.append(f"value+quality top-quartile (z={row['z_vq']:+.2f})")
    if row.get("z_insider", 0) > 1.0:
        reasons.append(f"insiders accumulating (z={row['z_insider']:+.2f})")
    if row.get("z_news", 0) > 1.0:
        reasons.append(f"news-flow burst (z={row['z_news']:+.2f})")
    if row.get("z_x", 0) > 0.8:
        reasons.append(f"X-buzz positive (z={row['z_x']:+.2f})")
    if row.get("z_x", 0) < -0.8:
        reasons.append(f"X-buzz negative (z={row['z_x']:+.2f})")
    if not row.get("passes_filters", True):
        reasons.append("FAILS technical filters (trend or gap)")

    if regime_label == "RISK-OFF":
        action = "HOLD" if conf < 0.8 else "WATCH"
        why = "Risk-off regime: cash-preferred. " + ("; ".join(reasons) or "no edge.")
    elif conf >= min_conf and row.get("passes_filters", False):
        action = "BUY"
        why = "Edge confirmed: " + ("; ".join(reasons) if reasons else "composite above threshold")
    elif conf >= 0.5:
        action = "WATCH"
        why = "Building case but below threshold: " + ("; ".join(reasons) or "watching for confirmation")
    else:
        action = "HOLD"
        why = "Insufficient edge."
    return action, why


def write_decisions(con, df: pd.DataFrame, regime: dict, regime_label: str, top_n: int):
    today = datetime.now(tz=None)
    df = df.head(top_n).copy()
    rows_wl = []
    rows_dec = []
    for i, r in df.iterrows():
        action, rationale = decide_action(r, regime_label)
        breakdown = {
            "momentum_score": float(r.get("momentum_score") or 0),
            "vq_score":       float(r.get("vq_score") or 0),
            "insider_score":  float(r.get("insider_score") or 0),
            "news_burst":     float(r.get("news_burst") or 0),
            "x_score":        float(r.get("x_score") or 0),
            "z_momo":         float(r.get("z_momo") or 0),
            "z_vq":           float(r.get("z_vq") or 0),
            "z_insider":      float(r.get("z_insider") or 0),
            "z_news":         float(r.get("z_news") or 0),
            "z_x":            float(r.get("z_x") or 0),
            "regime_label":   regime_label,
        }
        rows_wl.append((today, r["ticker"], int(i) + 1, float(r["composite"]),
                        action, float(r["confidence"]), rationale,
                        json.dumps(breakdown)))
        if action in ("BUY", "SELL"):
            decision_id = hashlib.sha256(f"{r['ticker']}|{today.isoformat()}|{action}".encode()).hexdigest()[:24]
            rows_dec.append((decision_id, r["ticker"], action, float(r["close"]),
                             float(r["confidence"]), rationale,
                             json.dumps(breakdown), json.dumps([])))
    if rows_wl:
        con.executemany(
            """INSERT OR REPLACE INTO watchlist
               (watchlist_date, ticker, rank, composite_score, action, confidence, rationale, signal_breakdown)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", rows_wl
        )
    if rows_dec:
        con.executemany(
            """INSERT OR REPLACE INTO decisions
               (decision_id, ticker, action, price_at_decision, confidence, rationale, signal_snapshot, kb_citations)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", rows_dec
        )


def write_digest(df: pd.DataFrame, regime: dict, regime_label: str, regime_score_v: float, top_n: int) -> Path:
    today = date.today()
    out = REPORTS / f"{today}-digest.md"
    md = [f"# TradingBrain digest — {today}", ""]
    md.append("## Macro & regime")
    if "SPY" in regime:
        s = regime["SPY"]
        md.append(f"- SPY {s['close']:.2f} vs MA200 {s['ma200']:.2f} ({s['pct_vs_ma200']:+.2f}%) → {'ABOVE' if s['above'] else 'BELOW'}")
    if "VIXCLS" in regime:
        md.append(f"- VIX: {regime['VIXCLS']['value']:.2f}")
    if "DGS10" in regime:
        md.append(f"- 10Y yield: {regime['DGS10']['value']:.2f}")
    if "DGS3MO" in regime:
        md.append(f"- 3M yield: {regime['DGS3MO']['value']:.2f}")
    md.append(f"- **Regime: {regime_label}** (score {regime_score_v:.2f})")
    md.append("")
    md.append(f"## Watchlist — top {top_n}")
    md.append("")
    md.append("| # | Ticker | Action | Conf | Composite | Momentum | VQ | Insider | News | Rationale |")
    md.append("|---|--------|--------|------|-----------|----------|----|---------|------|-----------|")
    for i, r in df.head(top_n).iterrows():
        action, why = decide_action(r, regime_label)
        md.append(
            f"| {i+1} | **{r['ticker']}** | `{action}` | {r['confidence']:.2f} | {r['composite']:+.2f} | "
            f"{r['z_momo']:+.2f} | {r['z_vq']:+.2f} | {r['z_insider']:+.2f} | {r['z_news']:+.2f} | {why} |"
        )
    md.append("")
    md.append("## Risk rails")
    md.append(f"- max position: {RULES['max_position_pct']*100:.0f}%  · stop-loss: {RULES['stop_loss_pct']*100:.0f}%  · take-profit: {RULES['take_profit_pct']*100:.0f}%")
    md.append(f"- kill switch at {RULES['max_drawdown_halt_pct']*100:.0f}% drawdown  · min confidence to BUY: {RULES['min_confidence']:.2f}")
    out.write_text("\n".join(md))
    return out


def write_latest_json(df: pd.DataFrame, regime: dict, regime_label: str,
                      regime_score_v: float, x_meta: dict, top_n: int) -> Path:
    """Export the dashboard payload. Read at request time by the zo.space API."""
    out = REPORTS / "latest.json"
    items = []
    for i, r in df.head(top_n).iterrows():
        action, rationale = decide_action(r, regime_label)
        t = r["ticker"]
        xm = x_meta.get(t, {})
        items.append({
            "rank": int(i) + 1,
            "ticker": t,
            "sector": TICKER_SECTOR.get(t, "uncategorised"),
            "action": action,
            "confidence": float(r["confidence"]),
            "composite": float(r["composite"]),
            "close": float(r.get("close") or 0),
            "atr_pct": float(r.get("atr_pct") or 0),
            "momentum_z": float(r.get("z_momo") or 0),
            "vq_z": float(r.get("z_vq") or 0),
            "insider_z": float(r.get("z_insider") or 0),
            "news_z": float(r.get("z_news") or 0),
            "x_z": float(r.get("z_x") or 0),
            "x_sentiment_avg": float(xm.get("sentiment_avg", 0.0)),
            "x_volume_z": float(xm.get("volume_z", 0.0)),
            "passes_filters": bool(r.get("passes_filters", False)),
            "rationale": rationale,
        })
    payload = {
        "asof": str(date.today()),
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "regime": regime,
        "regime_label": regime_label,
        "regime_score": float(regime_score_v),
        "weights": WEIGHTS,
        "rules": RULES,
        "watchlist": items,
        "universe": _UNI.get("universe", {}),
    }
    out.write_text(json.dumps(payload, indent=2, default=str))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    con = kb()
    momo = latest_momentum()
    vq = latest_signal(con, "vq_composite")
    insider = latest_signal(con, "insider_buy_cluster")
    news = latest_signal(con, "news_burst")
    x = latest_signal(con, "x_sentiment")
    macro = macro_snapshot(con)
    reg_score, reg_label = regime_score(macro)

    # Parse X metadata per ticker for dashboard detail.
    x_meta = {}
    if not x.empty and "metadata" in x.columns:
        for _, row in x.iterrows():
            try:
                x_meta[row["ticker"]] = json.loads(row["metadata"]) if row["metadata"] else {}
            except Exception:
                x_meta[row["ticker"]] = {}

    df = fuse(momo, vq, insider, news, x, reg_score)
    if df.empty:
        print("No data to score. Run ingestion + momentum.py first.")
        con.close()
        return

    write_decisions(con, df, macro, reg_label, args.top)
    digest_path = write_digest(df, macro, reg_label, reg_score, args.top)
    json_path = write_latest_json(df, macro, reg_label, reg_score, x_meta, args.top)
    # Also expose a stable "latest" copy of the markdown.
    latest_md = REPORTS / "digest-latest.md"
    latest_md.write_text(digest_path.read_text())
    con.close()

    print(f"\nRegime: {reg_label} (score {reg_score:.2f})")
    print(f"  digest   → {digest_path}")
    print(f"  dashboard→ {json_path}")
    print(f"\nTop {args.top}:")
    print(f"{'#':>3}  {'tkr':<6}  {'action':<6}  {'conf':>5}  {'comp':>6}  {'momo':>6}  {'vq':>6}  {'ins':>6}  {'news':>6}  {'x':>6}")
    for i, r in df.head(args.top).iterrows():
        action, _ = decide_action(r, reg_label)
        print(f" {i+1:>2}  {r['ticker']:<6}  {action:<6}  {r['confidence']:>5.2f}  {r['composite']:>+6.2f}  "
              f"{r['z_momo']:>+6.2f}  {r['z_vq']:>+6.2f}  {r['z_insider']:>+6.2f}  {r['z_news']:>+6.2f}  {r['z_x']:>+6.2f}")


if __name__ == "__main__":
    main()

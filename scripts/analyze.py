#!/usr/bin/env python3
"""tb analyze <TICKER> — full six-lens swing analysis per DOCTRINE.md.

Pulls real data through the six lenses (regime, relative strength, technicals,
catalysts, sentiment/positioning, intermarket), names the setup, builds a
complete trade plan with ATR-based stops and position sizing from
config/session.yaml, grades confluence A/B/C, and prints the Section 9 format.

LIVE data sources (no fabrication): prices.duckdb, intraday_snap.parquet,
hmm-regime.json, _clenow_lab/momentum.parquet, earnings_calendar.parquet,
reports/pattern-basis.json.

Usage:
    python3 -m scripts.analyze NVDA
    python3 -m scripts.analyze NVDA --direction long --json
"""
from __future__ import annotations
import argparse, json
from datetime import date
from pathlib import Path
import duckdb, pandas as pd, yaml
try:
    from scripts import calibration
except ImportError:
    import calibration
try:
    from backtest import trade_sim
except ImportError:
    import sys as _sys
    _sys.path.insert(0, str(next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)))
    from backtest import trade_sim

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
PRICES = ROOT / "data" / "prices.duckdb"
SNAP = ROOT / "data" / "intraday_snap.parquet"
EARN = ROOT / "data" / "earnings_calendar.parquet"
REGIME = ROOT / "reports" / "hmm-regime.json"
CLENOW = ROOT / "_clenow_lab" / "momentum.parquet"
BASIS = ROOT / "reports" / "pattern-basis.json"
SESSION = ROOT / "config" / "session.yaml"
UNIV = ROOT / "config" / "universe.yaml"


def load_session() -> dict:
    cfg = yaml.safe_load(SESSION.read_text()) if SESSION.exists() else {}
    cfg.setdefault("account_equity_usd", 50000)
    cfg.setdefault("risk_per_trade_pct", 1.0)
    cfg.setdefault("max_portfolio_heat_pct", 6.0)
    cfg.setdefault("max_position_pct", 20.0)
    cfg.setdefault("min_reward_to_risk", 2.0)
    cfg.setdefault("prefer_reward_to_risk", 3.0)
    cfg.setdefault("slippage_bps", 5)
    cfg.setdefault("data_mode", "LIVE")
    return cfg


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(s: pd.Series, n: int = 14) -> float:
    d = s.diff()
    up = d.clip(lower=0).rolling(n).mean()
    dn = (-d.clip(upper=0)).rolling(n).mean()
    if dn.iloc[-1] == 0:
        return 100.0
    rs = up.iloc[-1] / dn.iloc[-1]
    return float(100 - 100 / (1 + rs))


def macd(s: pd.Series):
    line = ema(s, 12) - ema(s, 26)
    sig = ema(line, 9)
    return float(line.iloc[-1]), float(sig.iloc[-1]), float(line.iloc[-1] - sig.iloc[-1])


def atr(df: pd.DataFrame, n: int = 14) -> float:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return float(tr.rolling(n).mean().iloc[-1])


def load_prices(t: str) -> pd.DataFrame:
    con = duckdb.connect(str(PRICES), read_only=True)
    df = con.execute(
        "SELECT date, open, high, low, close, volume FROM prices WHERE ticker=? ORDER BY date", [t]
    ).fetchdf()
    con.close()
    return df


def snap_price(t: str):
    if not SNAP.exists():
        return None
    df = pd.read_parquet(SNAP)
    row = df[df["ticker"] == t]
    if row.empty:
        return None
    r = row.iloc[0]
    return {"last": float(r["last_price"]), "state": r.get("market_state", ""),
            "change_pct": float(r["change_pct"]) if pd.notna(r.get("change_pct")) else None}


def earnings_for(t: str):
    if not EARN.exists():
        return None
    df = pd.read_parquet(EARN)
    row = df[df["ticker"] == t]
    if row.empty:
        return None
    today = date.today()
    fut = row[pd.to_datetime(row["report_date"]).dt.date >= today]
    if fut.empty:
        return None
    nxt = fut.sort_values("report_date").iloc[0]
    d = pd.to_datetime(nxt["report_date"]).date()
    return {"date": d.isoformat(), "days_away": (d - today).days, "hour": nxt.get("hour", "")}


def _structural_regime():
    """Transparent regime from SPY structure (DOCTRINE §14 lens 1).
    Returns (label, exposure, detail). Authoritative for the long-gate."""
    try:
        con = duckdb.connect(str(PRICES), read_only=True)
        spy = con.execute("SELECT date, close FROM prices WHERE ticker='SPY' ORDER BY date").fetch_df()
        con.close()
        c = spy["close"]
        last = float(c.iloc[-1])
        ma200 = float(c.tail(200).mean())
        dd60 = last / float(c.tail(60).max()) - 1
        ret60 = last / float(c.iloc[-60]) - 1 if len(c) > 60 else 0.0
        vol20 = float(c.pct_change().tail(20).std())
        if dd60 < -0.20 or (last < ma200 and dd60 < -0.12):
            return "Crash", 0.10, f"SPY {dd60:+.0%} off 60d high, below MA200"
        if last < ma200:
            return "Bear", 0.30, f"SPY below MA200 ({last:.0f}<{ma200:.0f})"
        if dd60 < -0.08:
            return "Pullback", 0.50, f"SPY {dd60:+.0%} off highs but >MA200"
        if vol20 > 0.018:
            return "Bull_volatile", 0.60, f"SPY >MA200, elevated vol {vol20:.1%}"
        if ret60 > 0.12:
            return "Euphoria", 0.60, f"SPY >MA200, +{ret60:.0%}/60d"
        return "Bull", 0.90, f"SPY >MA200 ({last:.0f}>{ma200:.0f})"
    except Exception:
        return "Unknown", 0.5, ""


def regime_read():
    struct_label, struct_exp, struct_detail = _structural_regime()
    hmm_label = "Unknown"
    if REGIME.exists():
        hmm_label = json.loads(REGIME.read_text()).get("acted_label", "Unknown")
    # Structure is authoritative. Flag implausible HMM disagreement.
    disagree = ""
    if hmm_label in ("Crash", "Bear") and struct_label in ("Bull", "Euphoria", "Bull_volatile", "Pullback"):
        disagree = f" (HMM says {hmm_label} — overridden by structure)"
    fav = struct_label in ("Bull", "Euphoria", "Bull_volatile")
    return {"label": struct_label, "exposure": struct_exp, "favorable": fav,
            "detail": struct_detail + disagree, "hmm_label": hmm_label}


def clenow_rank(t: str):
    if not CLENOW.exists():
        return None
    df = pd.read_parquet(CLENOW)
    row = df[df["ticker"] == t]
    if row.empty:
        return None
    return {"rank": int(row.iloc[0]["rank"]), "score": float(row.iloc[0]["score"]),
            "atr_pct": float(row.iloc[0]["atr_pct"])}


def pattern_winrate(setup: str):
    if not BASIS.exists():
        return None
    d = json.loads(BASIS.read_text()).get("summary", {})
    key = setup if setup in d else ("TREND_LEADER" if setup == "MOMO_CONT" else None)
    if not key or key not in d:
        return None
    b = d[key]
    return {"winrate_10d": round(b.get("winrate_10d", 0), 1), "median_10d": round(b.get("median_10d", 0), 2),
            "n": b.get("n_10d", 0)}


def categorize(t: str):
    u = yaml.safe_load(UNIV.read_text())["universe"]
    for sub, lst in u.items():
        if t in lst:
            return sub
    return None


def analyze(t: str, direction: str | None, cfg: dict) -> dict:
    t = t.upper()
    df = load_prices(t)
    if len(df) < 60:
        return {"error": f"insufficient price history for {t} ({len(df)} bars)"}

    spy = load_prices("SPY")
    snap = snap_price(t)
    last = snap["last"] if snap else float(df["close"].iloc[-1])
    eod_close = float(df["close"].iloc[-1])

    closes = df["close"]
    ma20 = float(closes.rolling(20).mean().iloc[-1])
    ma50 = float(closes.rolling(50).mean().iloc[-1])
    ma200 = float(closes.rolling(200).mean().iloc[-1]) if len(df) >= 200 else None
    rsi14 = rsi(closes)
    macd_line, macd_sig, macd_hist = macd(closes)
    atr14 = atr(df)
    atr_pct = atr14 / last * 100
    bb_mid = ma20
    bb_std = float(closes.rolling(20).std().iloc[-1])
    bb_up, bb_lo = bb_mid + 2 * bb_std, bb_mid - 2 * bb_std
    bb_pos = (last - bb_lo) / (bb_up - bb_lo) if bb_up > bb_lo else 0.5
    vol20 = float(df["volume"].rolling(20).mean().iloc[-1])
    vol_today = float(df["volume"].iloc[-1])
    vol_ratio = vol_today / vol20 if vol20 else 1.0
    hi52 = float(df["high"].tail(252).max())
    lo52 = float(df["low"].tail(252).min())
    pct_to_52h = (hi52 - last) / last * 100

    # Relative strength vs SPY (20d)
    ret20 = float(closes.pct_change(20).iloc[-1])
    spy20 = float(spy["close"].pct_change(20).iloc[-1]) if len(spy) > 20 else 0.0
    rs20 = (ret20 - spy20) * 100

    above20, above50 = last > ma20, last > ma50
    above200 = (ma200 is not None and last > ma200)
    uptrend = above50 and (ma200 is None or ma50 > ma200)

    reg = regime_read()
    cl = clenow_rank(t)
    earn = earnings_for(t)
    cat = categorize(t)

    # Default direction = long unless clearly broken
    if direction is None:
        direction = "long" if uptrend or above50 else "short"

    # ---- Name the setup ----
    setup, setup_note = "NONE", "no clean setup"
    prev5_high = float(df["high"].tail(6).head(5).max())
    near_52h = pct_to_52h < 3
    if direction == "long":
        if cl and cl["rank"] <= 20 and above50 and last > prev5_high:
            setup, setup_note = "MOMO_CONT", f"Clenow #{cl['rank']}, new 5-day high"
        elif near_52h and vol_ratio > 1.2:
            setup, setup_note = "BREAKOUT", f"within {pct_to_52h:.1f}% of 52w high, vol {vol_ratio:.1f}x"
        elif uptrend and 30 <= rsi14 <= 45 and abs(last - ma50) / ma50 < 0.06:
            setup, setup_note = "PULLBACK", f"uptrend pullback to MA50, RSI {rsi14:.0f}"
        elif above200 and rsi14 < 35:
            setup, setup_note = "MEAN_REVERSION", f"oversold (RSI {rsi14:.0f}) above MA200"
        elif uptrend and above50:
            setup, setup_note = "TREND_LEADER", f"trend intact (>MA50{'/200' if above200 else ''}), RS {rs20:+.1f}%"
    else:
        if not above50 and rsi14 > 60:
            setup, setup_note = "BREAKDOWN", f"below MA50, RSI {rsi14:.0f} rolling over"

    # ---- Trade plan (structure-based levels, DOCTRINE §5) ----
    swing_low_20 = float(df["low"].tail(20).min())
    swing_high_20 = float(df["high"].tail(20).max())
    swing_high_60 = float(df["high"].tail(60).max())
    base_range = swing_high_60 - swing_low_20

    if direction == "long":
        # Identical plan to the backtest/calibration engines (single source of truth).
        _plan = trade_sim.build_plan(df, atr14=atr14, last=last)
        entry = _plan.entry
        stop = round(_plan.stop, 2)
        t1, t2 = round(_plan.t1, 2), round(_plan.t2, 2)
    else:
        entry = last
        struct_stop = swing_high_20 + 0.25 * atr14
        atr_cap = last + 2.5 * atr14
        stop = round(min(struct_stop, atr_cap), 2)
        if last > swing_low_20 * 1.005:
            t1 = swing_low_20
        elif last > lo52 * 1.005:
            t1 = lo52
        else:
            t1 = last - 2.0 * atr14
        t2 = min(lo52, last - 0.6 * base_range, t1 - 1.5 * atr14)
        t1, t2 = round(t1, 2), round(t2, 2)
    risk_per_share = abs(entry - stop)
    rr_t1 = abs(t1 - entry) / risk_per_share if risk_per_share else 0
    rr_t2 = abs(t2 - entry) / risk_per_share if risk_per_share else 0
    blended_rr = 0.5 * rr_t1 + 0.5 * rr_t2

    equity = cfg["account_equity_usd"]
    risk_pct = cfg["risk_per_trade_pct"]
    max_pos_pct = cfg.get("max_position_pct", 20.0)
    risk_dollars = equity * risk_pct / 100
    shares = int(risk_dollars / risk_per_share) if risk_per_share else 0
    # DOCTRINE Part VI: a single position cannot exceed max_position_pct of equity.
    # Tight stops make the 1R-risk size huge; cap notional and let effective risk fall below 1R.
    max_shares = int((equity * max_pos_pct / 100) / entry) if entry else shares
    size_capped = shares > max_shares
    if size_capped:
        shares = max_shares
    position_value = shares * entry
    pct_of_equity = position_value / equity * 100
    effective_risk_dollars = shares * risk_per_share
    effective_risk_pct = effective_risk_dollars / equity * 100 if equity else 0.0

    wr = pattern_winrate(setup)

    # ---- Six-lens scoring ----
    lenses = {}
    # 1 Regime
    if reg["favorable"]:
        lenses["regime"] = ("supportive", f"{reg['label']} regime, exposure {reg['exposure']:.0%}")
    elif reg["favorable"] is False:
        lenses["regime"] = ("concern", f"{reg['label']} regime — risk-off")
    else:
        lenses["regime"] = ("neutral", f"{reg['label']}")
    # 2 Relative strength
    if cl and cl["rank"] <= 15:
        lenses["rel_strength"] = ("supportive", f"Clenow #{cl['rank']}, RS {rs20:+.1f}% vs SPY")
    elif rs20 > 0:
        lenses["rel_strength"] = ("supportive", f"RS {rs20:+.1f}% vs SPY (20d)" + (f", Clenow #{cl['rank']}" if cl else ""))
    else:
        lenses["rel_strength"] = ("concern", f"RS {rs20:+.1f}% — lagging SPY")
    # 3 Technicals
    tech_bits = []
    tech_score = 0
    if direction == "long":
        if above20: tech_bits.append(">MA20"); tech_score += 1
        if above50: tech_bits.append(">MA50"); tech_score += 1
        if above200: tech_bits.append(">MA200"); tech_score += 1
        if macd_hist > 0: tech_bits.append("MACD+"); tech_score += 1
        if 40 <= rsi14 <= 70: tech_bits.append(f"RSI {rsi14:.0f} ok"); tech_score += 1
        elif rsi14 > 80: tech_bits.append(f"RSI {rsi14:.0f} extended"); tech_score -= 1
    lab = "supportive" if tech_score >= 3 else "neutral" if tech_score >= 1 else "concern"
    lenses["technicals"] = (lab, f"{setup} · " + ", ".join(tech_bits) + f", ATR {atr_pct:.1f}%")
    # 4 Catalysts
    if earn and earn["days_away"] <= max(cfg.get("holding_period_days", [2, 20])[1], 20):
        lenses["catalysts"] = ("concern", f"earnings in {earn['days_away']}d ({earn['date']}) — gap risk inside window")
    else:
        lenses["catalysts"] = ("neutral", "no earnings inside holding window")
    # 5 Sentiment / positioning
    if rsi14 > 85 or bb_pos > 1.0:
        lenses["sentiment"] = ("concern", f"euphoric (RSI {rsi14:.0f}, BB {bb_pos:.0%}) — crowded")
    elif rsi14 < 30:
        lenses["sentiment"] = ("supportive", f"fearful (RSI {rsi14:.0f}) — contrarian long")
    else:
        lenses["sentiment"] = ("neutral", f"RSI {rsi14:.0f}, Bollinger {bb_pos:.0%} of band")
    # 6 Intermarket
    lenses["intermarket"] = ("neutral", f"sector: {cat or 'n/a'} · check correlation vs other open positions")

    # ---- Grade ----
    sup = sum(1 for v, _ in lenses.values() if v == "supportive")
    con = sum(1 for v, _ in lenses.values() if v == "concern")
    min_rr = cfg["min_reward_to_risk"]
    rr_ok = blended_rr >= min_rr

    # ---- Calibration (trained on 10y stress test) ----
    regime_key = str(reg.get("label", "")).lower()
    calib_cw = calibration.confidence_weight(setup, regime_key) if setup != "NONE" else 0.0
    calib_oos = calibration.oos_expectancy(setup) if setup != "NONE" else 0.0
    calib_enabled = calibration.is_enabled(setup) if setup != "NONE" else False
    longs_suppressed = calibration.long_gated(regime_key) and direction == "long"
    research_verdict = calibration.research_verdict(setup) if setup != "NONE" else "Unknown"
    research_cap = calibration.size_cap(setup) if setup != "NONE" else 1.0
    live_neg = (calibration.replay_negative_gated(setup) or calibration.live_gated(setup)) if setup != "NONE" else False
    live_exp = calibration.live_expectancy(setup) if setup != "NONE" else None

    if setup == "NONE" or not rr_ok:
        grade = "C"
    elif longs_suppressed:
        grade = "C"
        setup_note += " · LONGS SUPPRESSED — bear regime (10y stress: negative expectancy)"
    elif research_verdict == "Reject":
        grade = "C"
        setup_note += " · ⛔ research REJECT — failed 30y validation, not deployable"
    elif live_neg:
        grade = "C"
        setup_note += f" · ⛔ LIVE GATE — recent realized {live_exp:+.2f}R (setup bleeding now, backtest overstated)"
    elif not calib_enabled:
        grade = "C"
        setup_note += " · setup disabled by calibration (no proven OOS edge)"
    elif sup >= 4 and con == 0 and blended_rr >= cfg["prefer_reward_to_risk"] and calib_oos > 0:
        grade = "A"
    elif sup >= 3 and con <= 1 and calib_oos > 0:
        grade = "B"
    else:
        grade = "C"

    if grade == "A":
        verdict, conf, size = ("Long" if direction == "long" else "Short"), "high", "full"
    elif grade == "B":
        verdict, conf, size = ("Long" if direction == "long" else "Short"), "medium", "half to full"
    else:
        verdict, conf, size = ("Watchlist" if setup != "NONE" and rr_ok else "Pass"), "low", "none"
        if not rr_ok and setup != "NONE":
            setup_note += f" · R/R {blended_rr:.1f} below min {min_rr}"

    # Research size cap (DOCTRINE Part XII): provisional setups trade at half.
    if research_cap == 0.5 and size in ("full", "half to full"):
        size = "half (research: Iterate — provisional edge)"

    return {
        "ticker": t, "asof": date.today().isoformat(), "category": cat,
        "price": {"last": round(last, 2), "eod_close": round(eod_close, 2),
                  "snap_state": snap["state"] if snap else "EOD",
                  "snap_change_pct": snap["change_pct"] if snap else None},
        "regime": reg, "direction": direction, "setup": setup, "setup_note": setup_note,
        "indicators": {"ma20": round(ma20, 2), "ma50": round(ma50, 2),
                       "ma200": round(ma200, 2) if ma200 else None, "rsi14": round(rsi14, 1),
                       "macd_hist": round(macd_hist, 3), "atr14": round(atr14, 2),
                       "atr_pct": round(atr_pct, 2), "vol_ratio": round(vol_ratio, 2),
                       "rs20_vs_spy": round(rs20, 1), "bollinger_pos": round(bb_pos, 2),
                       "pct_to_52w_high": round(pct_to_52h, 1), "clenow": cl},
        "plan": {"entry": round(entry, 2), "stop": stop, "t1": t1, "t2": t2,
                 "risk_per_share": round(risk_per_share, 2), "rr_t1": round(rr_t1, 2),
                 "rr_t2": round(rr_t2, 2), "blended_rr": round(blended_rr, 2),
                 "shares": shares, "position_value": round(position_value, 0),
                 "pct_of_equity": round(pct_of_equity, 1), "risk_dollars": round(risk_dollars, 0),
                 "size_capped": size_capped, "max_position_pct": max_pos_pct,
                 "effective_risk_pct": round(effective_risk_pct, 2)},
        "earnings": earn, "pattern_winrate": wr, "lenses": lenses,
        "calibration": {"oos_expectancy_R": round(calib_oos, 3), "confidence_weight": calib_cw,
                        "regime_key": regime_key, "enabled": calib_enabled,
                        "research_verdict": research_verdict,
                        "longs_suppressed": longs_suppressed},
        "grade": grade, "verdict": verdict, "confidence": conf, "size": size,
        "config": {"equity": equity, "risk_pct": risk_pct, "min_rr": min_rr},
    }


def render(a: dict) -> str:
    if "error" in a:
        return f"⚠️  {a['error']}"
    p, ind, pl = a["price"], a["indicators"], a["plan"]
    L = a["lenses"]
    icon = {"supportive": "🟢", "neutral": "⚪", "concern": "🔴"}
    out = []
    out.append(f"═══ {a['ticker']} · ${p['last']} ({p['snap_state']}) · {a['category'] or 'n/a'} · {a['asof']} ═══")
    snapchg = f" ({p['snap_change_pct']:+.1f}% today)" if p['snap_change_pct'] is not None else ""
    out.append(f"  EOD close ${p['eod_close']}{snapchg}")
    out.append("")
    rfav = "FAVORABLE" if a["regime"]["favorable"] else "HOSTILE" if a["regime"]["favorable"] is False else "NEUTRAL"
    out.append(f"① REGIME: {rfav} — {L['regime'][1]}")
    out.append("")
    out.append("② SIX-LENS SUMMARY")
    for k in ["regime", "rel_strength", "technicals", "catalysts", "sentiment", "intermarket"]:
        v, note = L[k]
        out.append(f"   {icon[v]} {k.replace('_',' ').title():14} {note}")
    out.append("")
    out.append(f"③ SETUP: {a['setup']} — {a['setup_note']}")
    wr = a["pattern_winrate"]
    if wr:
        out.append(f"   historical: {wr['winrate_10d']}% win @10d, {wr['median_10d']}% median (n={wr['n']})")
    cal = a.get("calibration", {})
    if cal and a["setup"] != "NONE":
        suppress = " · ⛔ LONGS SUPPRESSED (bear regime)" if cal.get("longs_suppressed") else ""
        out.append(f"   trained: OOS expectancy {cal['oos_expectancy_R']:+.3f}R · conf weight {cal['confidence_weight']}{suppress}")
    out.append(f"   GRADE: {a['grade']}")
    out.append("")
    out.append(f"④ TRADE PLAN ({a['direction'].upper()})")
    out.append(f"   Entry   ${pl['entry']}")
    out.append(f"   Stop    ${pl['stop']}  (−${pl['risk_per_share']}/sh · {ind['atr_pct']:.1f}% ATR buffer)")
    out.append(f"   T1      ${pl['t1']}  (R/R {pl['rr_t1']}) — scale 50%")
    out.append(f"   T2      ${pl['t2']}  (R/R {pl['rr_t2']}) — scale remainder")
    out.append(f"   Blended R/R: {pl['blended_rr']}  (min {a['config']['min_rr']})")
    out.append(f"   Size    {pl['shares']} sh = ${pl['position_value']:,.0f} ({pl['pct_of_equity']}% of equity)")
    out.append(f"           Math: ${a['config']['equity']:,} × {a['config']['risk_pct']}% = ${pl['risk_dollars']:,.0f} risk ÷ ${pl['risk_per_share']}/sh = {pl['shares']} sh")
    if pl.get("size_capped"):
        out.append(f"           ⚠ capped at {pl['max_position_pct']:.0f}% max position (tight stop) — effective risk {pl['effective_risk_pct']:.2f}% (<{a['config']['risk_pct']}% nominal)")
    out.append("   Manage  Move stop to breakeven after T1. Trail under MA20/swing lows on T2 leg.")
    out.append("")
    out.append("⑤ KEY RISKS & INVALIDATION")
    if a["earnings"]:
        out.append(f"   ⚠ earnings {a['earnings']['date']} ({a['earnings']['days_away']}d) — decide hold-through explicitly")
    out.append(f"   ✗ invalidation: close below ${pl['stop']} (long) / failed {a['setup']} snapback")
    out.append("")
    out.append(f"⑥ VERDICT: {a['verdict'].upper()} · confidence {a['confidence']} · size {a['size']}")
    out.append("")
    out.append(f"⑦ WHAT TO WATCH: 52w high ${ind['pct_to_52w_high']}% away · RSI {ind['rsi14']} · vol {ind['vol_ratio']}x · MA50 ${ind['ma50']}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("--direction", choices=["long", "short"], default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    cfg = load_session()
    res = analyze(a.ticker, a.direction, cfg)
    if a.json:
        print(json.dumps(res, indent=2, default=str))
    else:
        print(render(res))


if __name__ == "__main__":
    main()

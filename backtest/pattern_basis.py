#!/usr/bin/env python3
"""Historical base rates per swing-setup pattern.

For each pattern, walks 2-year history of the universe, fires the same
detector used in real-time, then measures realized 5/10/20-day forward
return + win rate.

Writes reports/pattern-basis.json (loaded by premarket briefing).
"""
from __future__ import annotations
import json, sys
from datetime import date
from pathlib import Path
import duckdb, numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.signals.swing_setup import detect_setup

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
PRICES = ROOT / "data" / "prices.duckdb"
REPORTS = ROOT / "reports"
REPORTS.mkdir(exist_ok=True)


def main():
    con = duckdb.connect(str(PRICES), read_only=True)
    tickers = [r[0] for r in con.execute("SELECT DISTINCT ticker FROM prices WHERE ticker NOT IN ('SPY','QQQ')").fetchall()]
    spy_full = con.execute("SELECT date, open, high, low, close, volume FROM prices WHERE ticker = 'SPY' ORDER BY date").fetchdf()

    # Step every 5 days through history; for each step, snapshot each ticker
    # and detect setup using only data up to that date.
    samples = {}  # setup -> list of {fwd5, fwd10, fwd20}

    print(f"Walking {len(tickers)} tickers...")
    for ti, t in enumerate(tickers):
        df_full = con.execute(
            "SELECT date, open, high, low, close, volume FROM prices WHERE ticker = ? ORDER BY date",
            [t],
        ).fetchdf()
        if len(df_full) < 250:
            continue

        # iterate from idx 220 to len-21, step 5
        for i in range(220, len(df_full) - 21, 5):
            slice_df = df_full.iloc[: i + 1].copy()
            slice_spy = spy_full[spy_full["date"] <= slice_df["date"].iloc[-1]].copy()
            setup = detect_setup(slice_df, slice_spy, clenow_rank=None)
            kind = setup.get("setup", "NONE")
            if kind == "NONE":
                continue
            entry_price = float(slice_df["close"].iloc[-1])
            # Forward returns at +5/+10/+20 trading days
            for fwd in (5, 10, 20):
                if i + fwd < len(df_full):
                    fwd_price = float(df_full["close"].iloc[i + fwd])
                    ret = (fwd_price - entry_price) / entry_price
                    samples.setdefault(kind, []).append({"fwd": fwd, "ret": ret, "ticker": t})
        if (ti + 1) % 20 == 0:
            print(f"  ...{ti+1}/{len(tickers)}")

    # Aggregate
    summary = {}
    for kind, rows in samples.items():
        s = {}
        df = pd.DataFrame(rows)
        for fwd in (5, 10, 20):
            sub = df[df["fwd"] == fwd]["ret"]
            if len(sub) == 0:
                continue
            s[f"n_{fwd}d"] = int(len(sub))
            s[f"median_{fwd}d"] = float(sub.median()) * 100
            s[f"mean_{fwd}d"] = float(sub.mean()) * 100
            s[f"winrate_{fwd}d"] = float((sub > 0).mean()) * 100
            s[f"sharpe_{fwd}d"] = float(sub.mean() / sub.std() * np.sqrt(252 / fwd)) if sub.std() > 0 else 0
        summary[kind] = s

    print("\nBase rates by setup:")
    for kind, s in summary.items():
        print(f"\n{kind} (n={s.get('n_5d', 0)} fires)")
        for fwd in (5, 10, 20):
            if f"median_{fwd}d" in s:
                print(f"  +{fwd}d  median {s[f'median_{fwd}d']:+.2f}%  "
                      f"winrate {s[f'winrate_{fwd}d']:5.1f}%  sharpe {s[f'sharpe_{fwd}d']:.2f}")

    out = REPORTS / "pattern-basis.json"
    out.write_text(json.dumps({"asof": date.today().isoformat(), "summary": summary}, indent=2, default=str))
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()

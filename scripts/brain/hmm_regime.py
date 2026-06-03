#!/usr/bin/env python3
"""5-state Gaussian HMM on SPY -> Crash, Bear, Neutral, Bull, Euphoria.

Features: 1d return, 20d realised vol, 60d drawdown, 20d momentum z.
States ordered by mean 1d return after fit.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import duckdb, numpy as np, pandas as pd
from hmmlearn.hmm import GaussianHMM

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import kb, PRICES_DB

LABELS = ["Crash", "Bear", "Neutral", "Bull", "Euphoria"]
ALLOC =  {"Crash": 0.10, "Bear": 0.30, "Neutral": 0.60, "Bull": 0.90, "Euphoria": 0.60}


def features(prices: pd.DataFrame) -> pd.DataFrame:
    p = prices.copy().sort_values("date").reset_index(drop=True)
    p["ret"] = p["close"].pct_change()
    p["vol20"] = p["ret"].rolling(20).std() * np.sqrt(252)
    p["dd60"] = p["close"] / p["close"].rolling(60).max() - 1.0
    p["mom20z"] = (p["close"].pct_change(20) -
                   p["close"].pct_change(20).rolling(60).mean()) / \
                  p["close"].pct_change(20).rolling(60).std()
    return p.dropna().reset_index(drop=True)


def fit_hmm(X: np.ndarray, n_states: int = 5, seed: int = 17) -> GaussianHMM:
    m = GaussianHMM(n_components=n_states, covariance_type="full",
                    n_iter=200, random_state=seed)
    m.fit(X)
    return m


def order_by_return(model: GaussianHMM, X: np.ndarray) -> list[int]:
    """Map fitted state indexes -> ordered position 0..4 by mean return."""
    states = model.predict(X)
    means = []
    for s in range(model.n_components):
        idx = (states == s)
        means.append((s, float(X[idx, 0].mean()) if idx.sum() else -9))
    means.sort(key=lambda x: x[1])
    return [s for s, _ in means]


def causal_states(model, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n = len(X)
    states = np.zeros(n, dtype=int)
    posterior = np.zeros((n, model.n_components))
    for i in range(n):
        _, post = model.score_samples(X[: i + 1])
        posterior[i] = post[-1]
        states[i] = int(post[-1].argmax())
    return states, posterior


def stability_filter(states: np.ndarray, min_consecutive: int = 3, lookback: int = 20, max_flicker: int = 4) -> tuple[int, str, bool]:
    """Return (acted_state, status, is_volatile_warning).
    - acted_state stays at last-acted regime until a new regime persists min_consecutive bars
    - flicker count = number of state changes in trailing `lookback`; > max_flicker = warning"""
    if len(states) < min_consecutive:
        return int(states[-1]), "BOOTSTRAP", False
    acted = int(states[0])
    run = 1
    for s in states[1:]:
        if int(s) == acted:
            run = max(run, run + 1)  # noop, just for clarity
        else:
            run = 1
            # only switch if next min_consecutive-1 also agree
        # walking version: track current candidate
        if int(s) != acted:
            run = 1
        else:
            pass
    # cleaner second pass
    acted = int(states[0])
    candidate = int(states[0]); cand_run = 1
    for s in states[1:]:
        if int(s) == candidate:
            cand_run += 1
            if cand_run >= min_consecutive:
                acted = candidate
        else:
            candidate = int(s); cand_run = 1
    tail = states[-lookback:]
    flicker = int((np.diff(tail) != 0).sum())
    status = "VOLATILE" if flicker > max_flicker else "STABLE"
    return acted, status, flicker > max_flicker


def main():
    pcon = duckdb.connect(str(PRICES_DB), read_only=True)
    spy = pcon.execute(
        "SELECT date, close FROM prices WHERE ticker = 'SPY' ORDER BY date"
    ).fetchdf()
    if spy.empty:
        print("No SPY data."); return

    f = features(spy)
    X = f[["ret", "vol20", "dd60", "mom20z"]].to_numpy()
    if len(X) < 180:
        print(f"Only {len(X)} days; need more history for HMM."); return

    model = fit_hmm(X)
    order = order_by_return(model, X)
    states, posterior = causal_states(model, X)
    raw_state = int(states[-1])
    raw_post = posterior[-1].tolist()
    acted_state, stability_status, is_volatile = stability_filter(states)
    # order[rank] = hmm_state_index ranked low->high mean return; invert it.
    state_to_rank = {s: rank for rank, s in enumerate(order)}
    raw_label = LABELS[state_to_rank[raw_state]]
    acted_label = LABELS[state_to_rank[acted_state]]
    # Re-align posterior to labels by rank.
    raw_post = [posterior[-1][order[rank]] for rank in range(len(LABELS))]

    target_exposure = ALLOC[acted_label] * (0.5 if is_volatile else 1.0)

    today = f.iloc[-1]
    con = kb()
    asof = today["date"]
    if hasattr(asof, "date"):
        asof = asof.date()
    meta = json.dumps({
        "raw_label": raw_label,
        "acted_label": acted_label,
        "stability": stability_status,
        "volatile_warning": is_volatile,
        "probs": dict(zip(LABELS, raw_post)),
    })
    con.execute("DELETE FROM signals WHERE signal_date = ? AND signal_name LIKE 'hmm_%'", [asof])
    con.execute(
        "INSERT INTO signals VALUES (?, 'SPY', 'hmm_regime', ?, NULL, ?)",
        [asof, target_exposure, meta],
    )

    out = {
        "asof": asof.isoformat(),
        "raw_state": raw_state,
        "raw_label": raw_label,
        "raw_posterior": dict(zip(LABELS, raw_post)),
        "acted_state": acted_state,
        "acted_label": acted_label,
        "stability": stability_status,
        "volatile_warning": is_volatile,
        "target_exposure": round(target_exposure, 2),
        "features_today": {
            "ret": float(today["ret"]),
            "vol20": float(today["vol20"]),
            "dd60": float(today["dd60"]),
            "mom20z": float(today["mom20z"]),
        },
    }
    out_path = ROOT / "reports" / "hmm-regime.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"HMM regime: {acted_label} (raw={raw_label}, {stability_status})  target exposure {target_exposure:.0%}")
    for s, p in zip(LABELS, raw_post):
        print(f"  {s:9}  p={p:.2f}")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""TradingAgents-style multi-agent debate per ticker.

Five role agents per ticker, each consulting the compiled brain page + targeted
context, then a final Trader synthesises into a structured decision.

Roles (trimmed from TradingAgents v0.2.4 7-role schema for cost):
  1. Fundamentals Analyst (rating + thesis from fundamentals + filings)
  2. Technical Analyst    (rating + thesis from momentum, swing setup, price)
  3. News/Sentiment Analyst (rating + thesis from recent news + X sentiment)
  4. Risk Manager           (veto/approve + concerns)
  5. Trader                 (final BUY/HOLD/SELL + size in R + holding period)

Each agent uses /zo/ask with the Tape persona prompt customised by role.
Output structured JSON written to brain/debates/<DATE>-<TICKER>.json.
"""
from __future__ import annotations
import argparse, json, os, time
from datetime import date
from pathlib import Path
import requests

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
DEBATES = ROOT / "brain" / "debates"
COMPANIES = ROOT / "brain" / "companies"
DEBATES.mkdir(parents=True, exist_ok=True)

ZO_API = "https://api.zo.computer/zo/ask"
ZO_TOKEN = os.environ.get("ZO_CLIENT_IDENTITY_TOKEN", "")
MODEL_ANALYST = "anthropic:claude-sonnet-4-6"
MODEL_TRADER = "anthropic:claude-opus-4-7"

ROLE_PROMPTS = {
    "fundamentals": (
        "You are a Fundamentals Analyst on a swing-trading desk. "
        "Read the COMPILED BRAIN PAGE for {ticker} below. Focus only on "
        "the fundamentals snapshot, insider activity, filings timeline, "
        "and any explicit gap-analysis flags. Output strict JSON:\n"
        "{{\"rating\": <1-5 where 5=very bullish>, \"thesis\": \"<one sentence>\", "
        "\"top_points\": [\"<point>\", \"<point>\", \"<point>\"], "
        "\"confidence\": <0.0-1.0>}}\n"
        "Be honest. If data is thin, lower confidence."
    ),
    "technical": (
        "You are a Technical Analyst on a swing-trading desk. "
        "Read the COMPILED BRAIN PAGE for {ticker} below. Focus on the "
        "current setup, signal stack, momentum rank, swing pattern, and "
        "any price levels mentioned. Output strict JSON:\n"
        "{{\"rating\": <1-5 where 5=very bullish>, \"thesis\": \"<one sentence>\", "
        "\"top_points\": [\"<point>\", \"<point>\", \"<point>\"], "
        "\"confidence\": <0.0-1.0>}}"
    ),
    "sentiment": (
        "You are a News/Sentiment Analyst on a swing-trading desk. "
        "Read the COMPILED BRAIN PAGE for {ticker}. Focus on recent themes "
        "(news headlines) and any X/social sentiment indicators. Discount "
        "noise. Look for catalyst proximity. Output strict JSON:\n"
        "{{\"rating\": <1-5 where 5=very bullish>, \"thesis\": \"<one sentence>\", "
        "\"top_points\": [\"<point>\", \"<point>\", \"<point>\"], "
        "\"confidence\": <0.0-1.0>}}"
    ),
    "risk": (
        "You are the Risk Manager. You see the three analyst views below "
        "and the brain page for {ticker}. Approve or veto a swing-trade at "
        "1R risk. Your veto is ABSOLUTE. Output strict JSON:\n"
        "{{\"verdict\": \"APPROVE\"|\"VETO\", \"size_R\": <0.0-1.0>, "
        "\"primary_concern\": \"<one sentence>\", "
        "\"stop_discipline\": \"<one short sentence>\"}}\n"
        "Veto if: regime is BEAR, earnings within 5 trading days, "
        "stock already up >20% in last 5 days (extended), or analysts disagree by >=2 stars."
    ),
    "trader": (
        "You are the Trader making the final call on {ticker}. You see the "
        "three analyst views and the Risk Manager's verdict. If Risk vetoed, "
        "you MUST output HOLD or SELL — Risk's veto is absolute. Output strict JSON:\n"
        "{{\"action\": \"BUY\"|\"HOLD\"|\"SELL\", \"size_R\": <0.0-1.0>, "
        "\"horizon_days\": <int 1-30>, "
        "\"final_thesis\": \"<two sentences max, Tape's voice>\", "
        "\"key_invalidation\": \"<one short sentence>\"}}"
    ),
}

def ask(prompt: str, model: str = MODEL_ANALYST, retries: int = 2) -> dict:
    payload = {
        "input": prompt,
        "model_name": model,
        "output_format": {
            "type": "object",
            "properties": {"_": {"type": "string"}},
            "required": [],
        },
    }
    headers = {"authorization": ZO_TOKEN, "content-type": "application/json"}
    for attempt in range(retries + 1):
        try:
            r = requests.post(ZO_API, json=payload, headers=headers, timeout=120)
            r.raise_for_status()
            out = r.json().get("output", {})
            if isinstance(out, str):
                # try to extract JSON from a code-fenced or plain response
                t = out.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                try:
                    return json.loads(t)
                except Exception:
                    return {"raw": out}
            return out
        except Exception as e:
            if attempt == retries:
                return {"error": str(e)}
            time.sleep(2 * (attempt + 1))

def page_for(ticker: str) -> str:
    p = COMPANIES / f"{ticker}.md"
    return p.read_text() if p.exists() else f"(no brain page for {ticker} yet)"

def debate_one(ticker: str) -> dict:
    page = page_for(ticker)
    rec: dict = {"ticker": ticker, "asof": date.today().isoformat(), "agents": {}}
    # Analysts in parallel feel — done sequentially here (3 calls, ~5s each)
    for role in ("fundamentals", "technical", "sentiment"):
        prompt = ROLE_PROMPTS[role].format(ticker=ticker) + "\n\nCOMPILED BRAIN PAGE:\n\n" + page[:8000]
        rec["agents"][role] = ask(prompt, MODEL_ANALYST)
    # Risk gate sees the three views
    risk_ctx = "\n\nANALYST VIEWS:\n" + json.dumps(rec["agents"], indent=2)
    rec["agents"]["risk"] = ask(ROLE_PROMPTS["risk"].format(ticker=ticker) + risk_ctx + "\n\nBRAIN PAGE:\n\n" + page[:5000], MODEL_ANALYST)
    # Trader synthesises
    trader_ctx = "\n\nANALYSTS + RISK:\n" + json.dumps(rec["agents"], indent=2)
    rec["agents"]["trader"] = ask(ROLE_PROMPTS["trader"].format(ticker=ticker) + trader_ctx + "\n\nBRAIN PAGE:\n\n" + page[:4000], MODEL_TRADER)
    return rec

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", help="single ticker to debate")
    ap.add_argument("--top", type=int, default=3, help="debate top-N swing candidates")
    a = ap.parse_args()
    if not ZO_TOKEN:
        print("ZO_CLIENT_IDENTITY_TOKEN not set — debate disabled.")
        return
    if a.ticker:
        tickers = [a.ticker.upper()]
    else:
        # Top-N from swing setups
        setups = json.loads((ROOT / "reports" / "swing-setups.json").read_text())
        cands = setups.get("candidates") if isinstance(setups, dict) else setups
        tickers = [c["ticker"] for c in (cands or [])[: a.top]]
    print(f"Debating {len(tickers)} tickers: {', '.join(tickers)}")
    out = []
    for t in tickers:
        print(f"  [{t}] running...")
        rec = debate_one(t)
        out.append(rec)
        p = DEBATES / f"{date.today().isoformat()}-{t}.json"
        p.write_text(json.dumps(rec, indent=2))
        verdict = rec["agents"].get("trader", {}).get("action", "?")
        size = rec["agents"].get("trader", {}).get("size_R", "?")
        print(f"  [{t}] {verdict} · size {size}R")
    # Latest summary
    (DEBATES / "latest.json").write_text(json.dumps({"asof": date.today().isoformat(), "debates": out}, indent=2))
    print(f"\nWrote {len(out)} debates → {DEBATES}")

if __name__ == "__main__":
    main()

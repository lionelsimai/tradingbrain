"""The 'brain': combines rules + ML + an LLM advisor into one decision."""
from dataclasses import dataclass

from config import CFG
from agent.signals import signal_trend, signal_momentum


def ml_score(signals: dict) -> float:
    """
    [HOOK 2] STUB for a TRAINED ML model. Returns a 0..1 confidence.
    For now it just turns the rule-votes into a score. Later: train a real
    model on historical setups and return its probability (a smooth number,
    which makes min_confidence meaningful).
    """
    votes = list(signals.values())
    bullish = sum(1 for v in votes if v > 0)
    return round(bullish / len(votes), 2) if votes else 0.0


def llm_reasoning(symbol: str, signals: dict, confidence: float) -> str:
    """
    [HOOK 3] STUB for an LLM ADVISOR. It explains; it never trades.
    Later, wire in the Anthropic API (key read from your environment):
        # import anthropic
        # client = anthropic.Anthropic()
        # prompt = f"Given signals {signals}, summarize recent context for {symbol}."
        # msg = client.messages.create(model="claude-sonnet-4-...",
        #         max_tokens=300, messages=[{"role": "user", "content": prompt}])
        # return msg.content[0].text
    """
    leaning = "bullish" if confidence >= 0.5 else "cautious"
    return f"{symbol}: {signals} -> {leaning} ({confidence:.0%}) [LLM stub: add news]"


@dataclass
class Decision:
    day: int
    price: float
    signals: dict
    confidence: float
    action: str   # BUY / SELL / HOLD
    reason: str   # plain-English why  (this is your observability)


def decide(day: int, history, shares: int) -> Decision:
    price = history[-1]
    signals = {"trend": signal_trend(history), "momentum": signal_momentum(history)}
    confidence = ml_score(signals)
    advice = llm_reasoning(CFG.symbol, signals, confidence)

    # RULES make the final call — the brain only advises.
    if shares == 0 and confidence >= CFG.min_confidence and signals["trend"] > 0:
        action, why = "BUY", f"Entry: trend up, confidence {confidence:.0%}."
    elif shares > 0 and (signals["trend"] < 0 or confidence < 0.4):
        action, why = "SELL", "Exit: trend turned / confidence faded."
    else:
        action, why = "HOLD", "No clear edge — staying patient."
    return Decision(day, price, signals, confidence, action, f"{why} | {advice}")

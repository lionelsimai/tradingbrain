#!/usr/bin/env python3
"""Finance-tuned, dependency-free sentiment + manipulation lexicon.

This replaces the crude bag-of-words scorer in scripts/ingest/xurl_sentiment.py
with something materially better while staying auditable and free of heavy NLP
dependencies (no FinBERT / no transformer download). It is intentionally
transparent: every score can be explained by the terms that produced it.

What it adds over a plain positive/negative count:
  * negation handling — "not bullish", "no upside", "isn't strong" flip polarity
  * intensity weighting — "massive beat" weighs more than "beat"
  * hedging dampener — "might", "could", "rumor" reduce magnitude
  * MANIPULATION / HYPE detection — pump phrases ("to the moon", "can't lose",
    "guaranteed", "100x", rocket-spam) are scored as *manipulation risk*, NOT as
    genuine bullish sentiment. This is the single most important guardrail when
    consuming social data: the loudest "bullish" posts are often coordinated
    pumps, and a naive scorer would treat a pump as a strong buy signal.

The output of `analyze_text` is a small dict the engine can aggregate:
    {
      "sentiment": float in [-1, +1],   # genuine directional read
      "intensity": float >= 0,          # how strong the language is
      "hype": float in [0, 1],          # pump/ramp language density
      "spam": float in [0, 1],          # bot/spam structural markers
      "n_terms": int,                   # sentiment-bearing tokens matched
    }

Nothing here is financial advice; it is a text feature extractor.
"""
from __future__ import annotations

import re
from typing import Iterable

# --------------------------------------------------------------------------- #
# Term banks. Weights are deliberately conservative and human-readable.
# Positive/negative weights are on a ~0.3-1.0 scale; the aggregate is squashed.
# --------------------------------------------------------------------------- #
POSITIVE = {
    # demand / fundamentals
    "beat": 0.8, "beats": 0.8, "raised": 0.7, "raise": 0.6, "raises": 0.7,
    "upgrade": 0.8, "upgraded": 0.8, "outperform": 0.7, "accelerating": 0.7,
    "acceleration": 0.6, "growth": 0.4, "demand": 0.4, "record": 0.6,
    "guidance": 0.2, "expansion": 0.5, "margin": 0.2, "margins": 0.2,
    "tailwind": 0.6, "tailwinds": 0.6, "moat": 0.5, "leader": 0.5,
    "leaders": 0.4, "leadership": 0.4, "winner": 0.5, "winning": 0.5,
    # price / tape
    "breakout": 0.6, "rally": 0.5, "rallied": 0.5, "surge": 0.6, "surged": 0.6,
    "upside": 0.6, "bull": 0.5, "bullish": 0.7, "long": 0.3, "buy": 0.4,
    "buying": 0.4, "accumulate": 0.5, "accumulating": 0.5, "support": 0.3,
    "strong": 0.5, "strength": 0.5, "momentum": 0.3, "positive": 0.5,
    "oversold": 0.3,  # mild contrarian-positive
    "calls": 0.2,
}

NEGATIVE = {
    # demand / fundamentals
    "miss": 0.8, "misses": 0.8, "missed": 0.8, "cut": 0.6, "cuts": 0.6,
    "downgrade": 0.8, "downgraded": 0.8, "underperform": 0.7, "slowing": 0.6,
    "slowdown": 0.7, "decline": 0.5, "declining": 0.5, "warning": 0.7,
    "warn": 0.6, "guidance": 0.0, "headwind": 0.6, "headwinds": 0.6,
    "weak": 0.6, "weakness": 0.6, "soft": 0.4, "fraud": 1.0, "probe": 0.6,
    "investigation": 0.6, "lawsuit": 0.5, "recall": 0.6, "layoffs": 0.5,
    "dilution": 0.5, "dilutive": 0.5, "bankruptcy": 1.0, "default": 0.8,
    # price / tape
    "breakdown": 0.6, "selloff": 0.6, "sell-off": 0.6, "crash": 0.8,
    "plunge": 0.7, "plunged": 0.7, "dump": 0.6, "dumped": 0.6, "tank": 0.6,
    "tanked": 0.6, "downside": 0.6, "bear": 0.5, "bearish": 0.7, "short": 0.3,
    "shorting": 0.5, "puts": 0.2, "sell": 0.4, "selling": 0.4, "falling": 0.5,
    "fell": 0.4, "drop": 0.4, "dropped": 0.4, "overbought": 0.4, "bubble": 0.6,
    "overvalued": 0.5, "risk": 0.2, "risks": 0.2, "concern": 0.4,
    "concerns": 0.4, "negative": 0.5, "trap": 0.5,
}

# Words that AMPLIFY whatever sentiment word follows them (within 2 tokens).
INTENSIFIERS = {
    "massive": 1.8, "huge": 1.7, "enormous": 1.8, "explosive": 1.8,
    "monster": 1.7, "insane": 1.6, "extreme": 1.6, "very": 1.3, "highly": 1.3,
    "incredibly": 1.5, "strongly": 1.4, "significantly": 1.4, "major": 1.4,
    "sharply": 1.4, "dramatically": 1.5, "record": 1.4, "unprecedented": 1.6,
}

# Words that DAMPEN magnitude (hedging / low conviction).
HEDGES = {
    "might", "may", "could", "maybe", "perhaps", "possibly", "rumor",
    "rumour", "rumored", "speculation", "speculative", "unconfirmed", "if",
    "potentially", "supposedly", "allegedly", "seems", "appears", "likely",
}

# Negators flip the polarity of the next sentiment word (within 3 tokens).
NEGATORS = {"not", "no", "never", "without", "isn't", "isnt", "aren't", "arent",
            "wasn't", "wasnt", "won't", "wont", "don't", "dont", "doesn't",
            "doesnt", "didn't", "didnt", "cannot", "cant", "can't", "lacks",
            "lacking", "fails", "failing", "failed"}

# HYPE / PUMP markers. These do NOT count as sentiment. They raise manipulation
# risk. A post full of these is treated as suspect, not as a strong buy.
HYPE_PHRASES = [
    "to the moon", "moon shot", "moonshot", "can't lose", "cant lose",
    "guaranteed", "free money", "easy money", "all in", "yolo", "diamond hands",
    "hold the line", "next 100x", "100x", "1000x", "10x easy", "get rich",
    "this will explode", "load up", "back up the truck", "do not miss",
    "don't miss out", "dont miss out", "last chance", "lambo", "printing money",
    "infinite money", "you're welcome", "mark my words", "screenshot this",
    "trust me", "not financial advice but", "nfa but",
]
HYPE_TOKENS = {"moon", "rocket", "🚀", "💎", "🙌", "🤑", "💰", "🔥", "ape", "apes",
               "tendies", "squeeze", "gamma", "fomo"}

# Structural spam / bot markers handled in code: excessive cashtags, all-caps
# ratio, repeated punctuation, link-only posts.

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z'\-]*|🚀|💎|🙌|🤑|💰|🔥")
_CASHTAG_RE = re.compile(r"\$[A-Za-z]{1,6}\b")
_URL_RE = re.compile(r"https?://\S+")


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _emoji_run(text: str) -> int:
    """Longest run of repeated hype emojis (rocket spam etc.)."""
    best = run = 0
    prev = ""
    for ch in text:
        if ch in HYPE_TOKENS and ch == prev:
            run += 1
            best = max(best, run)
        elif ch in HYPE_TOKENS:
            run = 1
            prev = ch
        else:
            run = 0
            prev = ""
    return best


def analyze_text(text: str) -> dict:
    """Return sentiment/intensity/hype/spam features for one post."""
    text = (text or "").strip()
    if not text:
        return {"sentiment": 0.0, "intensity": 0.0, "hype": 0.0, "spam": 0.0, "n_terms": 0}

    low = text.lower()
    toks = _tokens(text)
    n = len(toks)

    # ---- hype / pump density --------------------------------------------- #
    hype_hits = sum(low.count(p) for p in HYPE_PHRASES)
    hype_hits += sum(1 for t in toks if t in HYPE_TOKENS)
    emoji_run = _emoji_run(text)
    hype = min(1.0, 0.25 * hype_hits + 0.2 * emoji_run)

    # ---- structural spam markers ----------------------------------------- #
    cashtags = len(_CASHTAG_RE.findall(text))
    urls = len(_URL_RE.findall(text))
    letters = [c for c in text if c.isalpha()]
    caps_ratio = (sum(1 for c in letters if c.isupper()) / len(letters)) if letters else 0.0
    excl = text.count("!")
    spam = 0.0
    if cashtags >= 5:          # ticker-stuffing
        spam += min(0.5, 0.1 * (cashtags - 4))
    if n > 0 and urls and n < 8:   # link-only / near-link-only
        spam += 0.3
    if caps_ratio > 0.6 and n >= 4:
        spam += 0.3
    if excl >= 4:
        spam += 0.2
    spam = min(1.0, spam)

    # ---- directional sentiment with negation + intensity ----------------- #
    score = 0.0
    n_terms = 0
    for i, tok in enumerate(toks):
        base = 0.0
        if tok in POSITIVE:
            base = POSITIVE[tok]
        elif tok in NEGATIVE:
            base = -NEGATIVE[tok]
        if base == 0.0:
            continue
        n_terms += 1
        # negation within 3 preceding tokens flips polarity
        window = toks[max(0, i - 3):i]
        if any(w in NEGATORS for w in window):
            base = -base
        # intensifier within 2 preceding tokens scales magnitude
        amp = 1.0
        for w in toks[max(0, i - 2):i]:
            if w in INTENSIFIERS:
                amp = max(amp, INTENSIFIERS[w])
        score += base * amp

    intensity = abs(score)

    # hedging dampens conviction
    if any(w in HEDGES for w in toks):
        score *= 0.6

    # squash to [-1, +1]; normalise by sqrt(term count) so a single strong word
    # can still register but a wall of weak words doesn't run away.
    if n_terms > 0:
        norm = score / (1.5 * (n_terms ** 0.5))
        sentiment = max(-1.0, min(1.0, norm))
    else:
        sentiment = 0.0

    # If a post is mostly hype, suppress its apparent sentiment — we do not let
    # ramp language masquerade as conviction.
    if hype >= 0.5:
        sentiment *= 0.4

    return {
        "sentiment": round(sentiment, 4),
        "intensity": round(intensity, 4),
        "hype": round(hype, 4),
        "spam": round(spam, 4),
        "n_terms": n_terms,
    }


def score_text_sentiment(text: str) -> float:
    """Back-compatible shim: returns just the [-1, +1] sentiment.

    Lets scripts/ingest/xurl_sentiment.py and others swap in this richer scorer
    without changing their call sites.
    """
    return analyze_text(text)["sentiment"]


if __name__ == "__main__":  # tiny manual smoke test
    samples = [
        "NVDA absolutely massive beat, demand accelerating, raising guidance",
        "not bullish on AMD here, margins look weak and guidance was soft",
        "$NVDA $AMD $MU $TSM $AVGO $SMCI 🚀🚀🚀 to the moon can't lose 100x all in",
        "Might be a rumor but MU could possibly see some upside maybe",
    ]
    for s in samples:
        print(analyze_text(s), "::", s[:60])

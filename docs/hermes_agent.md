# Hermes Agent Adapter

Drive TradingBrain from a Nous **Hermes** agent as a **research, summarisation, and stock-recommendation assistant**. TradingBrain already calls Hermes for its Q&A (`scripts/ask.py`); this adapter goes the other way — it exposes the system's safe operations as **Hermes-format tools** so a Hermes agent can summarise market evidence, rank watchlists, pull recommendations, and read sentiment on your behalf. It is intentionally not a live-trading agent.

## The shape

```
Hermes model (3-405b / 70b / 8b)
        │  OpenAI-compatible /chat/completions  (ChatML)
        ▼
scripts/agent/hermes_agent.py        ← system prompt with <tools>, runs the loop
        │  parses <tool_call> {"name":..,"arguments":..}   (or OpenAI tool_calls)
        ▼
scripts/agent/hermes_tools.py        ← safe registry → existing TradingBrain code
        │  returns <tool_response> back to the model
        ▼
get_market_regime · get_macro_context · get_outlier_context · get_target_quality · list_universe · get_recommendations
get_super_recommendations · get_social_sentiment · refresh_social_sentiment · ask_brain
```

It speaks both tool dialects: the OpenAI-structured `tool_calls` that vLLM emits with `--tool-call-parser hermes`, and raw `<tool_call>` tags in the message content (single- or double-quoted JSON). So it works against a local server or a hosted provider without changes.

## Two compatibility modes

Hermes is served in different ways, so the adapter supports both and defaults to the one that works everywhere:

- **Portable (default).** The adapter injects the tool schema as a `<tools>` block in the system prompt and parses the `<tool_call>` tags the model emits. This needs no special server support, so it runs against **any** OpenAI-compatible Hermes endpoint — Ollama, a plain vLLM/llama.cpp server, or a hosted route.
- **Native** (`export HERMES_NATIVE_TOOLS=1`). The server runs `--tool-call-parser hermes` (or a provider's tool API). The adapter passes `tools` in the request and lets the server inject the schema and return structured `tool_calls` — so it does **not** also embed `<tools>` itself, avoiding describing the tools twice. Use this with vLLM started as `--tool-call-parser hermes --enable-auto-tool-choice`.

Either way, both response styles are parsed defensively, so a mode mismatch degrades gracefully rather than breaking.

## Try it offline first (no API, no cost)

```bash
python3 -m scripts.agent.hermes_agent --dry-run        # lists tools, runs two locally
python3 -m scripts.agent.hermes_agent --print-system   # see the exact system prompt
```

The dry run reads your real reports (e.g. the current regime) and proves the wiring end to end without calling a model.

## Run the live agent

Set the same environment variables the rest of the repo uses, then ask in plain language:

```bash
export HERMES_API_KEY=...                         # required
export HERMES_API_BASE=https://inference.hermes.ai/v1   # or your local/hosted route
export HERMES_MODEL=nous-hermes-3-405b            # or hermes-3-70b / -8b

python3 -m scripts.agent.hermes_agent "what's the strongest AI name right now, and warn me about any hype"
```

The agent will check the regime, pull macro/rates/policy-event context, scan candidate outliers/trading abnormalities, evaluate target credibility / banker-target pump risk, run the stricter super-recommender when Lionel asks for the strongest stock recommendations, read sentiment as needed, and answer in the Tape voice — research summaries and recommendations only.

## Deployment options

- **Local with vLLM** (recommended for privacy / no per-token cost):
  ```bash
  vllm serve NousResearch/Hermes-3-Llama-3.1-8B --tool-call-parser hermes --enable-auto-tool-choice
  export HERMES_API_BASE=http://localhost:8000/v1
  export HERMES_MODEL=NousResearch/Hermes-3-Llama-3.1-8B
  export HERMES_API_KEY=local            # any non-empty value
  ```
- **Ollama:** `ollama run hermes3`, then point `HERMES_API_BASE` at Ollama's OpenAI-compatible endpoint.
- **Hosted:** OpenRouter and DeepInfra serve `hermes-3-405b` on an OpenAI-compatible route — set `HERMES_API_BASE`/`HERMES_MODEL`/`HERMES_API_KEY` accordingly.

The 8B model runs on a single consumer GPU and is fine for development; 70B/405B give better reasoning for production.

## Tools exposed

| Tool | What it does | Side effects |
| --- | --- | --- |
| `get_market_regime` | Risk-on/off, target exposure | read-only |
| `get_macro_context` | Upcoming FOMC/CPI/PCE/payrolls/Fed/Treasury/Trump policy-post context and rate-pricing risk | read-only |
| `get_outlier_context` | Trading-abnormality scan: extreme returns, volume spikes, large gaps, abnormal ranges, stale data, OHLC/bad prints | read-only |
| `get_target_quality` | Target credibility / pump-risk overlay for analyst/banker target provenance, independence, recency, dispersion, and live-quality gates | read-only |
| `list_universe` | AI value-chain names, optionally by sub-sector | read-only |
| `get_recommendations` | Baseline ranked picks + defined-risk plans (proposals) | read-only |
| `get_super_recommendations` | Stricter institutional stock-recommender overlay: setup + price/volume/liquidity + benchmark relative strength + macro + outlier + target-quality + sentiment/fresh evidence + live-quality blockers | read-only |
| `get_social_sentiment` | Manipulation-aware sentiment for a ticker | read-only |
| `refresh_social_sentiment` | Rebuild the sentiment signal from ingested posts | recomputes a signal; no scraping |
| `ask_brain` | Retrieve supporting evidence for a question | read-only (needs embeddings + populated KB) |

## Safety

This adapter inherits the repo's agent doctrine (`agents/permissions.py`): the agent **summarises, ranks, recommends, and explains research; it never places trades, calls a broker, sizes positions, modifies the risk policy, or touches the kill switch.** None of the tools import the broker or order paths, and `tests/test_hermes_agent.py` proves it. The system prompt repeats the guardrail and the disclaimer, and every tool result carries it too.

Everything here is informational, not personalized financial advice. A human operator reviews and executes.

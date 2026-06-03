# Devil's-Advocate Critique — the v1 app plan and my own work

You asked me to be my own harshest critic. Here it is, in two parts: what's wrong
with the v1 plan (and what I changed), and — more importantly — what's still wrong
with the system I've built. I'm not padding this; these are real.

## Part 1 — Flaws in the v1 plan (addressed)

1. **An LLM was set to invent entry/stop/target.** The plan calls the Anthropic
   API with the picker prompt and parses "the levels it returns." Those numbers
   define your risk, and an LLM will hallucinate them — plausibly, confidently,
   wrongly. **Changed:** the app ingests the tested engine's picks, which compute
   levels from real price structure. The LLM may narrate, never price.

2. **Close-only paper marking would have lied.** A daily job comparing to the
   close misses that intraday price can hit the stop *or* the target first.
   **Changed:** the marking route uses the day's high/low and resolves
   stop-before-target ties to the stop (worst case) — the rule the backtester uses.

3. **No auth, no RLS.** The plan ships four open tables. **Changed:** RLS is
   enabled on all of them with a loud "add policies before deploy" note. As-is it
   is owner-only; do not expose it publicly.

4. **A 10-ticker large-cap watchlist is maximal survivorship + a tiny sample.**
   The paper record the plan calls "your real moat" will be statistical noise for
   *months*. That's not a bug to fix in code; it's an expectation to set honestly.

5. **Paper-trading isn't wired to the validation band.** The gauntlet's Phase K
   requires comparing live paper results to the Monte Carlo confidence band, not
   just displaying a hit rate. The app surfaces the verdicts; closing this loop
   fully is still TODO.

## Part 2 — Flaws in MY work (mostly unresolved — read this)

1. **The app code is unrun.** I could not connect to Supabase, a data API, or a
   browser from here. The TypeScript is a careful first build, not a tested one.
   Expect integration bugs. Anyone who tells you otherwise about un-executed code
   is guessing.

2. **The conviction weights are hand-picked guesses.** Trend 25 / momentum 20 /
   regime 25, the 60 cap, the missing-pillar handling — I chose these by judgment.
   I have *no evidence* they are optimal or even good. They are reasonable; they
   are not validated.

3. **PBO is 92.9%, and I may be too quick to wave it away.** I called it
   "provisional" on a short sample. The less comfortable reading is that the setup
   selection is genuinely overfit. I cannot rule that out. It is a red flag, not a
   footnote.

4. **The regime classifier and Monte Carlo knobs are arbitrary.** The "crash"
   threshold (2.5× median vol) and the bootstrap block length (10) are hand-set;
   results move if you move them. They are defensible, not derived.

5. **The survivorship "discount" is folklore, not measurement.** I say "real edge
   is often roughly half." I cannot quantify the bias without delisted data. That
   number is a caution, not a correction.

6. **The skill-vs-beta alpha is essentially noise.** 376%/yr from ~8 months is an
   artifact; I flagged it but arguably shouldn't grant any "pass" on this sample.
   The real evidence of skill is a thin +7-point win-rate edge over random entries.

7. **The deepest one: circularity.** The "1,919 trades" are *simulated by the same
   trade logic being validated* — same fill, slippage, and exit assumptions. Real
   fills can differ materially. The gauntlet validates the system against its own
   simulation, which is weaker than it sounds.

8. **I have built an elaborate apparatus around an unproven edge.** Everything I
   added — memory, regimes, Monte Carlo, the gauntlet, the go-live gate, this app —
   is *honesty and validation* infrastructure. None of it is evidence the strategy
   makes money, because that evidence does not exist yet. A fair skeptic would say:
   impressive scaffolding, unproven core.

## The one conclusion both parts point to
The bottleneck has never been more code. It is the absence of (a) a real forward
paper-trading record and (b) a survivorship-free universe. Until those exist, the
honest verdict is REJECTED / BLOCKED, and it should stay there. The app is worth
shipping precisely because it is the machine that *starts producing (a)* — not
because it makes the system ready. It is not ready, and I won't say it is.

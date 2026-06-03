# Memory upgrade — what changed and why

Following the memory self-improvement prompt, applied to the real code with the
same discipline: measure first, change one thing, prove it, log it.

## The problem (measured, not guessed)
The agent had 1,919 resolved practice trades on record — but its memory recall
**couldn't reach a single one of them.** When it asked "what do I know about this
setup?", it got generic notes, not "this setup has actually gone +1.05R over 45
trades." Baseline numbers from `lab/memory_metrics.py`:
- Experience reachable through recall: **0%**
- Recall precision (how much of what's returned is on-topic): **0.13**
- Honesty labeling (does each recalled number say how big the sample is, and
  whether it's real or replay): **0%**

## The one change
Added experience-grounded recall (`memory.recall()`): it now surfaces each
setup's real track record — win rate, average result, how trades typically exit,
and real example IDs you can audit — with every number clearly labeled as replay
(practice) vs live, and tagged with its sample size.

## The result (same measurement, after)
- Experience reachable: **100%** (all 1,919 trades)
- Recall precision: **0.68** (5× better)
- Honesty labeling: **100%** — no recalled number is unlabeled

The old `retrieve()` is untouched, so nothing that depended on it breaks. The
full test suite passes (174 tests), including new tests that prove recall never
makes up a trade that didn't happen.

## Honest limits (unchanged truths)
- The track record is REPLAY — survivorship-biased practice data, not live.
  Recall now says so on every number, but it's still indicative only.
- Two memory metrics can't be measured yet — whether recall actually improves
  decisions, and whether mistakes stop repeating — because the agent has made
  zero real decisions. That's the reason to run it in paper mode and collect them.

## The loop's next proposed step (not yet applied — one change at a time)
Write REAL market-regime labels onto the history (today they're a "replay"
placeholder), then add gentle forgetting so stale, dead-regime lessons stop
dominating. See the open item in `export-state/experiments.csv`.

## See it yourself
```
python3 -m lab.memory_metrics                 # the before/after numbers
python3 scripts/collective/memory.py recall PULLBACK   # real recalled experience
python3 -m loops.improve experiments          # the change log
```

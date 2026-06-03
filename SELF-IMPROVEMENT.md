# Self-Improvement Loop — operating manual

This is the disciplined spine that turns TradingBrain into a true self-improving
agent. It does NOT add new trading signals. It adds judgement: it scores the
system against one clear goal, and forces improvement one careful step at a time.

## The one command
```
python3 -m loops.improve review
```
Run it on a cadence (weekly is fine). It writes a plain-English review to
`reports/improvement-review.md` and never trades on its own.

## What it enforces (the four rules)
- **Accurate** — it only scores REAL fills. Replay/backtest numbers are shown
  but never counted toward the goal (they flatter the system).
- **Reliable** — pure read-only, safe to re-run, won't crash on a missing file.
- **One clear goal** — everything is scored against `config/goal.yaml`. Edit that
  file to set what "winning" means. If you set an unrealistic goal (e.g. "beat
  the market"), the cycle will tell you it's not supported by the evidence.
- **Self-improving** — exactly ONE change is proposed per cycle, logged in
  `export-state/experiments.csv` with a hypothesis. You keep it or revert it next
  cycle. No changing five things at once and not knowing what worked.

## The changelog
```
python3 -m loops.improve experiments              # see all proposed/kept/reverted changes
python3 -m loops.improve resolve <id> kept|reverted "note"
```
Only ONE experiment can be open at a time. You must resolve it before the next
change is proposed. That is the scientific method, enforced.

## Operator vs Tuner (so changes don't collide)
- Operator cycle: weekly — mechanics, sizing, scoring.
- Tuner cycle: offset by 3 days — parameter/threshold tweaks.
Set in `config/goal.yaml` under `horizon`.

## Safety
`mode: read_only` in `config/goal.yaml` is the master switch. It stays read-only
until YOU change it and confirm. The loop proposes; it never goes live by itself.

## What the very first cycle told us (and it's the truth)
The system has **zero true live fills** — every impressive number so far is
replay over recent, survivorship-biased history. So step one isn't tuning. It's
letting it paper-trade and collect real results before trusting any of it.

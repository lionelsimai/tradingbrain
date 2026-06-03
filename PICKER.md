# The Recommendation Engine — your stock picker

One command turns the system's detected setups into clean, ranked
recommendations with full trade plans:
```
python3 -m scripts.recommend --equity 50000 --top 3
```
It writes `reports/recommendations.json` (for a front end) and prints a readable
report. For each pick it gives: entry zone, stop, target, reward:risk, position
size, a plain-English thesis, the six-pillar read, the single thing that means
you're wrong (invalidation), the bear case it argued against itself, and caveats.
It also gives a watch list (with the exact trigger to promote each name), a
market read, and an honest "no qualifying setups today" when nothing clears.

## What makes it trustworthy (built in, not optional)
- **It can't fake confidence.** Conviction is capped at "moderate" (60) while the
  system has zero live trades. Nothing can be labeled "strong" on practice data.
  The cap lifts on its own once a real live track record exists.
- **It only scores what it can see.** Three pillars have live data today (trend,
  momentum, regime). The other three (volume, fundamentals, sentiment) are not
  connected yet — every pick says so plainly. Connect those feeds and picks get
  sharper; until then, conviction stays honest.
- **It refuses bad trades.** Setups research has marked "Broken" are never shown.
  Anything below your minimum reward:risk goes to the watch list, not the picks.
- **It red-teams itself.** Each pick carries the strongest bear case, drawn from
  the setup's real replay win rate and its behaviour in crash windows.
- **It sizes off the stop.** Position size comes from your risk-per-trade and the
  stop distance, and total open risk is held under your heat cap.

## How to make the picks better (in order of impact)
1. **Paper-trade it.** Zero live trades is why conviction is capped and why the
   go-live gate is blocked. Real fills are the only thing that lifts both.
2. **Connect a sentiment feed (SocialBrain).** That's one of the three dark
   pillars; wiring it in adds real confluence instead of a disclosed blank.
3. **Load fundamentals/catalyst data.** Same idea for equities.

## The honest part I won't dress up
This is a disciplined decision-support tool, not a money machine. It will have
losing trades — good process loses sometimes. Its job is asymmetric setups,
small defined risk, and the discipline to say "no trade." It does not predict
profits, and no picker does.

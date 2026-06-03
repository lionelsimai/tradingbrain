# Hosting TradingBrain 24/7 (paper only)

Your laptop sleeps; a server doesn't. This runs your real system on a host so it
keeps taking PAPER trades and collecting the real results it needs — with live
trading firmly off.

## What it does
`ops/serve.py` runs your paper pipeline on a schedule and runs the
self-improvement review periodically. It will **refuse to start** if any live
flag is set, and it never pushes code anywhere.

## Run it locally first (one command each)
```
docker build -t tradingbrain .
docker run --rm tradingbrain
```
To test a single cycle and exit:
```
docker run --rm tradingbrain python3 ops/serve.py --once
```

## Put it on a host
Any container host works (Railway, Fly.io, Render, or a small VPS). Sign up
directly — you don't need anyone's referral link. Point the host at this folder,
let it build the Dockerfile, and add a small persistent disk mounted at
`/app/reports` and `/app/export-state` so your results survive restarts.

## Staying safe (the two rules)
1. **Leave it in paper mode.** Live stays off unless you deliberately set
   `HERMES_TRADING_MODE=live` and `TB_ALLOW_LIVE=1`. Don't, until you have a real
   paper track record and have re-checked everything on unbiased data.
2. **No self-driving to live.** Nothing here lets the agent flip itself to live
   or push its own code. Keep it that way.

## Check on it
```
docker logs <container>                         # live tail
cat reports/improvement-review.md               # latest review
python3 -m loops.improve experiments            # the change log
```

# Security & Secrets

- Secrets via env only; `.env` git-ignored; `.env.example` carries no real values.
- `safety/logging_setup.py` masks any NAME containing key/secret/token/password and
  known prefixes (`sk-`, `whsec_`, `pk_`). Tested in `test_red_team_safety.py`.
- Live broker keys must be separate from paper keys; live disabled regardless.
- CI `scripts/ci_static_safety.sh` fails on raw broker writes, hardcoded roots,
  hardcoded equity, agent→broker imports, combined-scorecard gating.
- No secret is ever printed; never run `env`/`printenv` in logs.

# PIT Coverage - open

Generated: 2026-06-03T02:48:35.660100+00:00
Closed: False
Universe rows: 0
Delisted rows: 0 (0.0%)
Candidate traceability: 0.0% (poor)
Corporate action rows: 0

## Blockers
- price table missing or empty
- universe table missing or empty
- universe lacks PIT/delisting columns
- no delisted/inactive rows in PIT universe
- corporate-action reference missing
- candidate local price/universe traceability below 95%

## Required Next Actions
- Import or build a delisted-inclusive point-in-time universe with active/delisted timestamps.
- Bind every price row to the universe state valid at that historical date.
- Collect split/dividend/symbol-change corporate actions for every traded candidate.
- Keep candidate traceability >=95% before any 9/10 research-quality claim.

PIT coverage is an evidence audit only. Candidate price traceability does not close survivorship bias unless the universe is delisted-inclusive and point-in-time.

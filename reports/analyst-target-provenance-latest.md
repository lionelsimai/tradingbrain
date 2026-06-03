# Analyst Target Provenance - weak

Generated: 2026-06-03T01:45:35.379505+00:00
Confidence ceiling: low
Candidates: 15

## Coverage
- Any recent target rows: 0.0%
- Independent broker/analyst provenance: 0.0%
- Usable research context: 0.0%
- High-confidence context: 0.0%
- Aggregate-only targets: 0.0%
- Missing/stale targets: 100.0%

## Candidate Rows
| Ticker | Status | Verdict | Recent | Independent | Aggregate | Brokers | Concentration | Median Target | Cautions |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| MU | missing | do_not_use | 0 | 0 | 0 | 0 | 0.0 | None | No analyst-target rows found for candidate. |
| AAOI | missing | do_not_use | 0 | 0 | 0 | 0 | 0.0 | None | No analyst-target rows found for candidate. |
| MRVL | missing | do_not_use | 0 | 0 | 0 | 0 | 0.0 | None | No analyst-target rows found for candidate. |
| INTC | missing | do_not_use | 0 | 0 | 0 | 0 | 0.0 | None | No analyst-target rows found for candidate. |
| ARM | missing | do_not_use | 0 | 0 | 0 | 0 | 0.0 | None | No analyst-target rows found for candidate. |
| AAPL | missing | do_not_use | 0 | 0 | 0 | 0 | 0.0 | None | No analyst-target rows found for candidate. |
| AMD | missing | do_not_use | 0 | 0 | 0 | 0 | 0.0 | None | No analyst-target rows found for candidate. |
| STX | missing | do_not_use | 0 | 0 | 0 | 0 | 0.0 | None | No analyst-target rows found for candidate. |
| WDC | missing | do_not_use | 0 | 0 | 0 | 0 | 0.0 | None | No analyst-target rows found for candidate. |
| ALAB | missing | do_not_use | 0 | 0 | 0 | 0 | 0.0 | None | No analyst-target rows found for candidate. |
| DDOG | missing | do_not_use | 0 | 0 | 0 | 0 | 0.0 | None | No analyst-target rows found for candidate. |
| COHR | missing | do_not_use | 0 | 0 | 0 | 0 | 0.0 | None | No analyst-target rows found for candidate. |
| QCOM | missing | do_not_use | 0 | 0 | 0 | 0 | 0.0 | None | No analyst-target rows found for candidate. |
| GEV | missing | do_not_use | 0 | 0 | 0 | 0 | 0.0 | None | No analyst-target rows found for candidate. |
| LITE | missing | do_not_use | 0 | 0 | 0 | 0 | 0.0 | None | No analyst-target rows found for candidate. |

## Blockers
- no candidate has recent independent broker/analyst target provenance
- no candidate satisfies independent-broker count and concentration policy

## Required Next Actions
- Ingest lawful broker/analyst-level target rows with ticker, broker, analyst, target, date, source_url, provider, and provenance_level.
- Keep provider aggregates tagged as provider_aggregate so they remain discounted.
- Require multiple independent broker sources before analyst targets can raise research confidence.

Analyst targets are research context only, not predictions or trade instructions. Provider aggregates are discounted and do not satisfy independent broker/analyst provenance.

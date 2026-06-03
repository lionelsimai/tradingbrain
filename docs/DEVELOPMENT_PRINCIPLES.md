# TradingBrain Development Principles

TradingBrain development uses layers, not open-ended loops.

## Strong Starting Prompt

Every new module or change starts from the project architecture rules:

- Keep risk policy, go-live authority, incident management, and source separation as first-class boundaries.
- Keep paper, replay, and live evidence separate.
- Fail closed on unknown data, broker state, approval state, or risk state.
- Prefer small typed modules with deterministic tests.

## Targeted Refinement

Refinement prompts must be specific. Examples:

- Add error handling for this API failure.
- Add input validation for this schema.
- Add edge-case tests for stale quotes, duplicate orders, and missing stops.
- Optimize this query without changing trading behavior.

Avoid vague prompts like "make this better" unless they are turned into concrete, testable acceptance criteria first.

## Separate Review

After building, review from a different perspective:

- Architecture boundaries
- Data validation
- Error handling
- API edge cases
- Safety gates
- Evidence separation
- Tests that prove the behavior

## Test-Driven Gates

Code is strong when tests and reports prove it, not when the AI says it is strong.

The loop is:

1. Build.
2. Review.
3. Test.
4. Fix specific failures.
5. Repeat on the failure evidence.

Open-ended self-refinement is not a safety mechanism. TradingBrain improves through targeted failures, tests, reports, and evidence.

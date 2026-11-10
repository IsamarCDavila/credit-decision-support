# Policy catalog and financial checks

**English** | [Español](es/policy-engine.md)

## Implemented scope

Phase 3 adds a published synthetic policy catalog, version-filtered lexical retrieval, deterministic DSCR calculation, rule evaluation, and a reproducible model-free baseline. Policies in `data/policies/` apply to SME/USD standalone statements. The 2026 example requires DSCR of at least 1.20; the 2027 example requires at least 1.30. These are fictional engineering fixtures, not lending recommendations.

The case cutoff selects the policy's half-open validity interval. It does not select by financial year, search relevance, model judgment, or the newest identifier. Exactly one published version must match. Each evaluation pins its policy hash and formula version before processing.

## Catalog publication

Docker Compose applies migrations and publishes both demo bundles before starting the API/worker. Repeated startup accepts identical bundles without creating duplicate versions. For an independently managed database, run Alembic and then the catalog CLI under a database-owner configuration:

```sh
uv run alembic upgrade head
uv run python -m credit_support.policy_catalog
```

The CLI can also receive explicit JSON file paths. It validates scope, dates, allowed operators, and threshold range; renders both policy languages from the typed rule; and atomically stores the specification, text fragments, hash, and publication time. Changed content under an existing identifier and overlapping published validity are rejected. Schema-owner credentials belong only to migration/publication administration; the API and worker continue to use the restricted runtime identity.

## API workflow

| Operation | Purpose |
|---|---|
| `GET /v1/policies` | List published catalog version identifiers |
| `GET /v1/policies/{version}` | Read the verified specification and bilingual fragments |
| `GET /v1/policies/{version}/fragments?q=DSCR&locale=en` | Search within exactly that version; locale supports `en` and `es` |
| `GET /v1/cases/{id}/policy` | Resolve the case's applicable policy with case-level authorization |
| `POST /v1/cases/{id}/evaluate` | Queue checks from a successful extraction, with `source_evaluation_id` and `Idempotency-Key` |
| `GET /v1/cases/{id}/evaluations/{evaluation_id}` | Read facts, source evidence, calculations, rule outcomes, and policy citations |

Catalog reads require authentication. Case operations require membership; only analysts may queue evaluation. Extraction must have completed successfully for the current document set. Uploading another document makes the source extraction stale for new policy checks until extraction is repeated. Idempotency replays the original response for 24 hours; another key still deduplicates the same pinned inputs.

Full-text retrieval is a lexical baseline, not semantic RAG. Search never changes rule parameters or policy selection. Unknown terms may yield an empty list, and citations always include version, fragment identifier, bilingual text, and hash. The worker uses all normative fragments for the selected rule rather than relying on search ranking to decide which constraints apply.

## DSCR conventions

DSCR is annual available cash flow divided by annual debt service. Inputs must be verified USD amounts with matching complete-calendar-year periods and at most two decimal places, within the statement amount range. Missing or ambiguous inputs produce MISSING_INPUT. Invalid amounts, units, periods, or negative debt service produce INVALID_INPUT. Zero debt service is NOT_APPLICABLE and requires review. Negative cash flow produces a valid negative ratio.

The displayed ratio has four decimals with half-up rounding; threshold comparison uses exact cross multiplication. For example, `119999.99 / 100000.00` displays `1.2000` but fails the 1.20 minimum. The calculation retains its operands, input fact IDs, formula version, and high-precision quotient. No float participates in monetary or threshold calculations.

Rule statuses are PASS, FAIL, and REQUIRES_REVIEW. Overall outcomes are:

- `meets_rules`: the synthetic rule passes and all six extracted fields are verified.
- `exceptions`: the rule fails with verified inputs and no other field-quality exception.
- `insufficient_evidence`: the metric cannot be evaluated or any extracted field is missing, ambiguous, or invalid.

These outcomes do not approve or reject credit. Completed checks remain at POLICY_CHECK; recommendation drafting and human-review endpoints are subsequent milestones. Calculations and their inputs are sealed after completion, with citations constrained to the pinned policy version.

## Reproducible verification

After configuration and startup:

```sh
uv run python scripts/smoke_ingestion.py
uv run python scripts/smoke_policy.py
uv run python scripts/evaluate_baseline.py
```

The baseline uploads the ten committed CSV/PDF pairs through the live API and waits for worker processing. It compares field outcomes against the independent fixture manifest and DSCR/rule outcomes against Python Fraction arithmetic, including integer-based half-up display rounding. It verifies policy citation content against the published catalog and writes `evaluations/reports/deterministic-baseline.json`.

The report records observed agreement, case-level timings from creation through policy completion, environment, and model usage. P95 uses nearest rank; with ten observations it is the largest timing. Infrastructure cost is unmeasured. This is a small controlled engineering baseline, not a real-world accuracy estimate, a service guarantee, or evidence of manual time savings. CI repeats the baseline in Docker Compose.

Unit and PostgreSQL integration tests cover exact boundaries, invalid/missing inputs, context independence, policy publication, date boundaries, search abstention/version isolation, concurrent deduplication, stale sources, immutable outputs, and cross-version citation rejection. [ADR-003](adr/003-policy-engine.md) records the design tradeoffs.

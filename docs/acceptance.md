# Evaluation and acceptance criteria

**English** | [Español](es/acceptance.md)

## Protocol

Use a deterministic generator with a seed, version, and ground truth independent of model outputs. Split train/dev/test by case and template family to reduce format leakage. Freeze the test set before prompt tuning. Ten end-to-end cases are smoke tests, not sufficient evidence of 99% reliability.

Compare A: deterministic extraction; B: one LLM workflow using the same tools; and C: specialized agents. B and C use the same model, maximum budget, documents, policy, and tools. Report actual tokens, cost, and latency, with at least three repetitions per case. Manual comparisons require human evaluators and a timing protocol.

Accuracy is correct fields divided by all expected fields; report correctly absent fields, errors, and abstentions separately. Financial values require decimal equality with the correct unit and period. Evidence coverage is supported material claims divided by all emitted material claims. Report field-level and case-level abstention separately against requested fields and cases. Empty output has N/A coverage, never 100%. Unsupported-claim rate uses the same claim population and includes an absolute count. Define materiality before evaluation: financial figures, calculations, rule outcomes, and recommendation reasons.

Reliability is validly completed jobs divided by initiated jobs under a declared protocol; report induced failures as a separate cohort. Publish sample sizes and 95% Wilson confidence intervals for proportions without inferring a service guarantee. Report median and p95 time from complete upload to draft, including environment and concurrency. Reconstruction is verifiable snapshots divided by retained snapshots, with deleted snapshots reported separately. Zero observed errors does not imply zero risk.

## Minimum scenario matrix

1. Complete case: available cash flow 150000, debt service 100000, DSCR 1.5000, synthetic rule satisfied.
2. Exact threshold 1.20 and values immediately below/above it: comparison before rounding.
3. Zero debt service: NOT_APPLICABLE and review, without division.
4. Negative debt service: INVALID_INPUT.
5. Negative cash flow with positive debt service: valid negative ratio.
6. Missing amount or conflicting sources: missing/ambiguous, without invented calculations.
7. Unsupported currency, period, or accounting basis: explicit block.
8. Missing/overlapping policy or citation from another version: block.
9. PDF prompt injection, nonexistent citation, or broken parser: controlled failure.
10. Restart, duplicate request, or stale review: no duplicate effects and the expected 409 response.

## Phase 0 gate

- Architecture decision, domain contracts, preliminary DDL, initial OpenAPI, threat model, and example are available.
- Fixture consistency and the PowerShell checks pass.
- Open decisions remain visible: demo identity implementation, license, and live-model provider/budget.
- Backend behavior, applied migrations, and complete OpenAPI validation are outside the design-stage evidence.

## Implementation gates

1. Foundation: healthy Compose services, migrations from an empty database, case-authorized API, pytest/Ruff/mypy CI, and secret scanning. Implement and test the transactional invariants described in the DDL.
2. Ingestion: reproducible synthetic PDF/CSV inputs, verifiable locators, and enforced limits.
3. Policies: non-overlapping selection, exact ratios, and an LLM-free baseline.
4. AI: offline mock, interchangeable adapter, citation validation, and B/C benchmark.
5. Human review: interface, mandatory reasons, concurrency controls, simulation reports, and reconstructible audit history.
6. Hardening: at least ten end-to-end scenarios, adversarial/resilience tests, and measured load limits. Report each design target as met or unmet with supporting evidence.

## Phase 6 evidence

See [hardening and measured load](hardening.md) for the ten-scenario protocol, 40 runs, confidence intervals, and status of every target. Timed human intervention and infrastructure cost allocation remain unmet; a complete version 1.0 release is not claimed.

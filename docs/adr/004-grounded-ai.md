# ADR-004: Bounded AI roles and durable model budgets

**English** | [Español](../es/adr/004-grounded-ai.md)

Status: accepted for Phase 4. Date: 2026-11-10.

## Decisions

1. Use the OpenAI Responses API through a small HTTP adapter and a deterministic offline provider. Live usage requires an explicit configuration opt-in and a private API key. The model is pinned in each evaluation; there is no silent provider or model fallback.
2. Keep orchestration explicit: source-observation proposal, deterministic validation and financial tools, then grounded draft organization. Two specialized roles and one generalist baseline share validators and the financial engine. This does not implement autonomous planning or agent shell access.
3. Require exact observation coverage of the existing structured formats. Contradictory observations cannot be omitted. The deterministic extractor remains authoritative, and missing, ambiguous, or invalid values cannot become verified facts through model confidence.
   Version 2 uses short evaluation-local source references and a per-request schema enum. Version 1 measurements exposed a model copying error in a long UUID reference; the amount itself was preserved. The mapping is reproducible from pinned document order, and the exact observation validator remains authoritative. AI source catalogs are bounded at 500 units.
4. Generate material bilingual wording from verified claim cards. The model chooses their selection/order subject to complete required coverage. Restrict factual output rather than attempting to prove arbitrary prose fully supported. This sacrifices expressive freedom and does not benchmark narrative reasoning or free-text hallucination.
5. Reserve costs durably before external calls, serialize reservations per database, and cap the initial campaign at US$2. Retain uncertain-call reservations and prohibit automatic paid retries. Persist completed output for recovery. Protect completed call records and drafts from mutation.
6. Perform network operations outside business transactions while maintaining worker heartbeats. Fence writes with case/job locks and the lease token. Deterministic tool results may survive a failed drafting stage; a failed evaluation never exposes a valid final draft.
7. Keep model measurements separate from mock checks. Report the generalist's smaller intermediate context and equal output caps explicitly. Record provider failures as blocked measurements, not quality or financial-calculation failures. No small-sample result establishes superiority over a single-role workflow.

## Consequences

The existing structured format can be verified without model trust, and tests incur no paid usage. Live behavior depends on account/model access and provider quota. Narrative extraction, semantic policy retrieval, unconstrained drafting, account-wide billing enforcement, and human-review UI remain separate extensions or milestones. See [AI workflow](../ai-workflow.md) for configuration, persistence, and measured limits.

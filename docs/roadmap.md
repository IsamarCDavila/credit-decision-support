# Implementation roadmap

**English** | [Español](es/roadmap.md)

The project progresses through independently reviewable milestones. Phase 0 defines the system; subsequent phases implement and verify it.

| Phase | Branch | Deliverable | Acceptance evidence |
|---|---|---|---|
| 0 — Specification | `docs/phase-0-specification` | Architecture, domain, initial SQL/HTTP contracts, synthetic fixture | Contract checks and documented design limits |
| 1 — Foundation | `feat/phase-1-foundation` | FastAPI, persistence, migrations, demo identity, authorization, minimal persistent worker, Compose, CI | Healthy services, clean migrations, passing CI |
| 2 — Ingestion | `feat/phase-2-ingestion` | Synthetic generator and PDF/CSV ingestion with evidence | Parser, locator, and input-limit tests |
| 3 — Policy engine | `feat/phase-3-policy-engine` | Versioned policy selection and deterministic financial calculations | Baseline evaluation and boundary cases |
| 4 — AI workflow | `feat/phase-4-ai-workflow` | Validated extraction, drafting, model adapter, offline mock | Reproducible evaluation and measured costs |
| 5 — Human review | `feat/phase-5-human-review` | Review interface, audit history, JSON/PDF reports | End-to-end demo, authorization, concurrency tests |
| 6 — Hardening | `test/phase-6-hardening` | Security, resilience, observability, load verification | Measured limits and reproducible test reports |

## Delivery process

Each phase uses a branch and pull request targeting `main`. A milestone includes a reviewable diff, reproducible validation, current documentation in both languages, and relevant limitations. Merge after acceptance criteria and applicable checks pass; start the next branch from the updated `main`. Squash commits when a single milestone commit improves clarity, or retain small commits when they help review.

Version `v0.1.0` marks an executable foundation. Version `v1.0.0` requires the complete MVP acceptance criteria. The initial design baseline does not constitute a product release.

## Dependencies and extensions

The foundation requires Python 3.12 and Docker Compose. Phase 4 provides an offline mock and optional OpenAI integration with a cumulative US$2 application allowance; see the [AI workflow](ai-workflow.md). Live-model measurements are distinct from offline orchestration tests.

Temporal, MCP, Kafka, Kubernetes, OCR, currency conversion, and additional financial segments remain separate extensions. Each requires an architecture decision, a defined need, and appropriate benchmark evidence. Small synthetic fixtures may be versioned; credentials, real documents, and provider logs are excluded.

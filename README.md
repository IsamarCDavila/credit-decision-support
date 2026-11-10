# Credit Decision Support

**English** | [Español](README.es.md)

Auditable AI-assisted credit analysis with synthetic data, deterministic financial rules, and human review.

## Project status

**Human review workspace — Phase 5.** The application ingests synthetic PDF/CSV statements, verifies model-proposed observations, calculates DSCR, checks versioned policies, and prepares grounded bilingual drafts. A browser workspace supports case assignment, independent human review, evidence/audit inspection, and verified JSON/PDF reports. OpenAI remains optional and disabled by default, with a cumulative US$2 application allowance. Security, resilience, and measured load hardening remain Phase 6.

The MVP supports SME cases in USD, full annual periods, and standalone financial statements. It prepares evidence-backed analysis for a human reviewer. Reports are marked **SIMULATION**; recommendations do not authorize real credit.

## Documentation

| Document | Purpose |
|---|---|
| [Human review workspace](docs/human-review.md) | Browser access, assignment, decisions, report reconstruction, and demo |
| [Grounded AI workflow](docs/ai-workflow.md) | Model roles, source validation, OpenAI setup, costs, and comparison limits |
| [Policy catalog and financial checks](docs/policy-engine.md) | Policy selection, DSCR, citations, and baseline verification |
| [Document ingestion](docs/ingestion.md) | Supported formats, evidence extraction, limits, and demo |
| [Foundation operations](docs/foundation.md) | Setup, API access, worker behavior, and verification |
| [Project specification](docs/specification.md) | Problem, scope, architecture, and design targets |
| [Architecture decision](docs/adr/001-mvp.md) | MVP scope and technical choices |
| [Domain contracts](docs/domain.md) | Evidence, financial calculations, policies, and review states |
| [HTTP API contract](contracts/openapi.json) | Implemented API operations |
| [PostgreSQL schema](contracts/schema.sql) | Foundation schema and database controls |
| [Threat model](docs/threat-model.md) | Threats, planned controls, and verification scenarios |
| [Evaluation and acceptance](docs/acceptance.md) | Metrics, test cases, and phase gates |
| [Roadmap](docs/roadmap.md) | Implementation milestones and release process |
| [Phase 0 status](docs/phase-0-delivery.md) | Available artifacts and validation limits |
| [Measured synthetic baseline](evaluations/reports/deterministic-baseline.json) | Observed agreement and timings on ten controlled cases |
| [Synthetic example](data/synthetic/case-001.json) | Evidence references and expected DSCR calculation |

## Validate the design fixture

Prerequisite: PowerShell 7.2 or later. From the repository root:

```powershell
./scripts/check-phase0.ps1
```

The check verifies initial routes, evidence references, CSV locators, the document SHA-256, and the example's decimal DSCR. It does not validate the complete OpenAPI specification, execute PostgreSQL DDL, or test a backend.

## Run locally

Prerequisites: Python 3.12, uv, and Docker Compose v2.

```sh
uv sync --frozen --extra dev
uv run python scripts/configure_demo.py
docker compose up --build --wait api worker
uv run python scripts/smoke_ingestion.py
uv run python scripts/smoke_policy.py
uv run python scripts/evaluate_ai.py --provider mock --output storage/ai-mock.json
uv run python scripts/smoke_review.py
```

The workspace opens at `http://127.0.0.1:8000/`; interactive API documentation is at `/docs`. Configuration generation creates private local credentials and refuses to overwrite `.env`. See [human review](docs/human-review.md) for signing in and the review workflow, [document ingestion](docs/ingestion.md) for supported inputs, and [foundation operations](docs/foundation.md) for database/identity configuration.

## Data and licensing

Only synthetic documents and cases are permitted. Credentials, real customer data, and provider logs must remain outside version control. No license has been selected; no open-source license is granted by default.

# Credit Decision Support

**English** | [Español](README.es.md)

Auditable AI-assisted credit analysis with synthetic data, deterministic financial rules, and human review.

## Project status

**Design stage — Phase 0.** The repository contains the MVP specification, architecture decisions, initial contracts, and acceptance criteria. The backend is not implemented. Performance and model-quality targets have not been measured.

The MVP supports SME cases in USD, full annual periods, and standalone financial statements. It prepares evidence-backed analysis for a human reviewer. Reports are marked **SIMULATION**; recommendations do not authorize real credit.

## Documentation

| Document | Purpose |
|---|---|
| [Project specification](docs/specification.md) | Problem, scope, architecture, and design targets |
| [Architecture decision](docs/adr/001-mvp.md) | MVP scope and technical choices |
| [Domain contracts](docs/domain.md) | Evidence, financial calculations, policies, and review states |
| [Initial HTTP contract](contracts/openapi.json) | Proposed API operations |
| [Initial PostgreSQL schema](contracts/schema.sql) | Proposed persistence model |
| [Threat model](docs/threat-model.md) | Threats, planned controls, and verification scenarios |
| [Evaluation and acceptance](docs/acceptance.md) | Metrics, test cases, and phase gates |
| [Roadmap](docs/roadmap.md) | Implementation milestones and release process |
| [Phase 0 status](docs/phase-0-delivery.md) | Available artifacts and validation limits |
| [Synthetic example](data/synthetic/case-001.json) | Evidence references and expected DSCR calculation |

## Validate the design fixture

Prerequisite: PowerShell 7.2 or later. From the repository root:

```powershell
./scripts/check-phase0.ps1
```

The check verifies initial routes, evidence references, CSV locators, the document SHA-256, and the example's decimal DSCR. It does not validate the complete OpenAPI specification, execute PostgreSQL DDL, or test a backend.

## Planned runtime

Python 3.12, FastAPI, Pydantic v2, PostgreSQL 16 with pgvector, SQLAlchemy, Alembic, and Docker Compose. An explicit Python state machine and database-backed worker handle orchestration. React/TypeScript is planned for the review interface. Runtime installation and startup instructions belong to the foundation milestone.

## Data and licensing

Only synthetic documents and cases are permitted. Credentials, real customer data, and provider logs must remain outside version control. No license has been selected; no open-source license is granted by default.

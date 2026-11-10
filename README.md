# Credit Decision Support

**English** | [Español](README.es.md)

Auditable AI-assisted credit analysis with synthetic data, deterministic financial rules, and human review.

## Project status

**Policy checks — Phase 3.** The backend ingests synthetic PDF/CSV statements, extracts source-backed facts, selects versioned policies, and calculates DSCR with deterministic rule outcomes and policy citations. A controlled baseline report is available; real-world performance and model quality have not been established. Model-assisted drafting and human review remain later milestones.

The MVP supports SME cases in USD, full annual periods, and standalone financial statements. It prepares evidence-backed analysis for a human reviewer. Reports are marked **SIMULATION**; recommendations do not authorize real credit.

## Documentation

| Document | Purpose |
|---|---|
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
```

The API runs at `http://127.0.0.1:8000`; interactive documentation is at `/docs`. Configuration generation creates private local credentials and refuses to overwrite `.env`. See [document ingestion](docs/ingestion.md) for the extraction workflow and [foundation operations](docs/foundation.md) for database and identity configuration.

## Data and licensing

Only synthetic documents and cases are permitted. Credentials, real customer data, and provider logs must remain outside version control. No license has been selected; no open-source license is granted by default.

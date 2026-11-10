# Foundation operations

**English** | [Español](es/foundation.md)

## Implemented scope

Phase 1 provides a FastAPI service, PostgreSQL persistence through SQLAlchemy Core, Alembic migrations, server-resolved demo identities, case-level permissions, idempotent case creation, an audit chain, and a persistent worker. SQL migrations are the authoritative persistence model. The foundation uses PostgreSQL 16; Phase 3 uses full-text policy retrieval as a baseline; embeddings and pgvector require later evaluation under [ADR-003](adr/003-policy-engine.md).

| Operation | Behavior |
|---|---|
| `GET /healthz` | Process liveness, without authentication |
| `GET /readyz` | Database connection and migration revision check |
| `POST /v1/cases` | Analyst-only creation with `Idempotency-Key`; expires after 24 hours |
| `GET /v1/cases/{id}` | Read a case only when actor and role match its membership |
| `GET /v1/cases/{id}/audit-events` | Authorized audit access with sequence pagination |

Interactive API documentation is available at `/docs`. `contracts/openapi.json` is generated from the implemented service. `contracts/openapi-design.json` retains the proposed complete MVP API; document upload, financial evaluation, review, and report export are not available yet.

## Startup

Prerequisites: Python 3.12, uv, Docker Engine or Docker Desktop, and Docker Compose v2. From the repository root:

```sh
uv sync --frozen --extra dev
uv run python scripts/configure_demo.py
docker compose up --build --wait api worker
uv run python scripts/smoke_api.py
```

Configuration generation creates random local database passwords and bearer tokens in `.env`, refuses to overwrite an existing file, and does not print credentials. The smoke command creates and reads a synthetic case without printing its bearer token. Repeating it returns the same case within the idempotency window.

The API binds to `127.0.0.1:8000`. PostgreSQL is not published to the host. The database health check precedes migrations; API and worker start only after migrations succeed. `docker compose down` stops services and retains the database volume. Credentials used to initialize that volume must remain stable across restarts.

## Identity and authorization

The configuration maps tokens to analyst, reviewer, auditor, and admin identities. Case creation adds the analyst as a case member. Other identities have no access unless case membership is explicitly provisioned in the database. There is no public membership-management endpoint in this milestone. Admin identity does not bypass case authorization. This local demo authentication is not a production identity service; deployment authentication and transport protection remain separate requirements.

API and worker connect as `cds_runtime`, which does not own tables and cannot alter the schema, modify published policies, or update/delete/truncate protected audit, document, and review records. Migrations use the schema owner. Database triggers also protect published policies and finalized evaluations, enforce same-case/same-evaluation references, require evidence for extracted facts, prevent overlapping published policies, and require an independent member reviewer for a current, ready evaluation.

## Worker

Jobs are stored in PostgreSQL. Workers claim them with `FOR UPDATE SKIP LOCKED`, use unique lease tokens, support heartbeats, and allow at most three claims per job. An expired worker cannot commit a result after a new worker claims the job. Result and completion audit event commit together.

The only implemented step is `foundation_check`, which verifies that an evaluation snapshot is available. It does not extract documents or produce a credit recommendation. No public API queues this internal verification step; integration tests populate the job table directly. Unsupported steps terminate explicitly. Crashed work is reclaimed after lease expiry; exhausted jobs become terminal. Extended processing, retry classification, and multi-step scheduling belong to later milestones.

## Validation

Use a dedicated PostgreSQL test database whose name ends in `_test`; the suite clears project tables in that database. Set `CDS_TEST_ADMIN_URL` to its SQLAlchemy PostgreSQL/psycopg URL, then run:

```sh
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run python scripts/export_openapi.py
```

Foundation integration scenarios cover API authentication and authorization, concurrent idempotency, audit hashes, runtime permissions, policy overlap, immutable snapshots, review guards, required evidence, invalid locators, worker concurrency/lease recovery, and migration upgrade/downgrade. Migration rollback removes project tables and functions while preserving unrelated tables. Downgrading discards project data and is intended for disposable development databases.

GitHub Actions additionally checks generated OpenAPI drift, builds and starts Compose services, checks readiness, and runs secret scanning. A passing local Python suite does not establish a successful container build; container verification is reported independently by CI. There are no financial-performance or model-quality measurements in Phase 1.

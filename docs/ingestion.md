# Synthetic document ingestion

**English** | [Español](es/ingestion.md)

## Supported statement format

Phase 2 accepts UTF-8 CSV and text-based PDF statements following `synthetic-statement-v1`. It extracts six fields: `annual_revenue`, `ebitda`, `total_debt`, `debt_service`, `available_cash_flow`, and `obligations`. This is a known-schema deterministic extractor, not a general PDF understanding system.

CSV requires this exact header order:

```csv
key,value,currency,period_start,period_end,basis,synthetic
annual_revenue,2500000.00,USD,2025-01-01,2025-12-31,individual,true
```

PDF statements use text labels such as:

```text
synthetic: true
currency: USD
period_start: 2025-01-01
period_end: 2025-12-31
basis: individual
annual_revenue: 2500000.00
```

All rows and documents in a case must share one complete calendar year, ending on or before the case cutoff. Only USD and standalone statements are supported. Amounts use an optional minus sign, at most 18 integer digits, a decimal point, and up to two decimal places. Thousands separators, scientific notation, and inferred units are excluded. Unknown field labels are retained as source content but do not produce financial facts.

An absent or blank field is `missing`; a malformed amount is `invalid`; differing supported values for the same field are `ambiguous`. Matching values from several sources remain `extracted` with all supporting evidence. Negative and zero values are retained; financial rules are evaluated in Phase 3.

## API workflow

| Operation | Purpose |
|---|---|
| `POST /v1/cases/{id}/documents` | Upload one file with matching filename/MIME, `synthetic=true`, and `Idempotency-Key` |
| `GET /v1/cases/{id}/documents/{document_id}` | Read metadata and the normalized pages or CSV rows |
| `GET /v1/cases/{id}/documents/{document_id}/content` | Download the original bytes as an attachment |
| `POST /v1/cases/{id}/extract` | Queue an extraction snapshot with `Idempotency-Key`; returns evaluation/job IDs |
| `GET /v1/cases/{id}/evaluations/{evaluation_id}` | Read processing status, facts, evidence, and whether the snapshot is current |

Only analysts who belong to the case can upload or queue extraction. Source and result reads require case membership. Filenames never determine storage paths or download names. Stored bytes and their metadata are immutable. Byte-identical uploads within a case reuse the existing document and do not invalidate the current extraction.

The upload response is 202 after synchronous format validation and transactional persistence. The separate extraction job combines sources and writes facts/evidence. Repeated requests reuse responses for 24 hours; extraction of the same pinned input deduplicates even under another key. Reusing an extraction key after new uploads returns its original evaluation; use a new key to request the new snapshot.

A successful extraction leaves processing at `VALIDATING` and the job at `SUCCEEDED`. It does not produce a policy outcome, recommendation, or credit decision. New documents clear the current evaluation pointer; old snapshots and their evidence remain readable. Terminal integrity failures produce no partial facts.

## Limits and controls

- 10 MiB per document, 20 documents per case, and 100 pages per PDF.
- Total HTTP body limit: 10 MiB plus 64 KiB multipart overhead, including streamed requests.
- Up to 2,000 CSV data rows; exact headers and single-line cells are required.
- Up to 2,000,000 extracted PDF characters and 20,000,000 expanded content bytes per page.
- Separate parser process, 15-second timeout, and Linux process memory/CPU limits described in [ADR-002](adr/002-ingestion.md).
- Encrypted, scanned/blank, malformed, unsupported, or out-of-scope inputs are rejected with 422. Oversized uploads and document-count overflow return 413.

The synthetic declaration is a caller assertion. No automatic PII detector or authenticity classifier is implemented. The parser does not perform OCR or interpret narrative instructions.

## Reproducible fixtures and demo

Ten seeded cases are committed as CSV/PDF pairs under `data/synthetic/generated/`. Their manifest records independent expected fact outcomes and SHA-256 values. Cases cover complete data, missing/blank fields, conflicting and invalid values, zero/negative amounts, large values, and untrusted narrative text.

```sh
uv sync --frozen --extra dev
uv run python scripts/generate_synthetic_cases.py
docker compose up --build --wait api worker
uv run python scripts/smoke_ingestion.py
```

Generate private configuration with `scripts/configure_demo.py` before first startup; existing configuration is retained during upgrades. The smoke command uploads the first CSV/PDF pair, queues extraction, waits for the worker, and prints facts and evidence counts without credentials.

## Verification

The PostgreSQL suite checks every generated variant in both formats against independent expected outcomes, resolves each citation back to its source, and verifies original-byte downloads. Additional scenarios cover unsupported scope, unreadable/encrypted/oversized files, empty PDF pages, parser timeout, concurrent deduplication, document limits, tampered storage, and historical evaluations. Generator reproducibility is checked against the committed manifest. The PDF fixture pages are also rendered for visual inspection.

These checks establish behavior on the controlled synthetic format, not accuracy or safety on arbitrary customer documents. CI also builds and starts the containers and checks API readiness. Financial calculations and policy retrieval are available in [Phase 3](policy-engine.md). Live models and human review remain later milestones.

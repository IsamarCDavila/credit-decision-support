# Human review workspace and reports

**English** | [Español](es/human-review.md)

Phase 5 adds a browser workspace, assigned reviewers/auditors, immutable human decisions, and English/Spanish JSON/PDF exports. Every view and report is a **SIMULATION** of synthetic credit analysis. A human decision does not authorize real credit.

## Start and access

Use Python 3.12, uv, and Docker Compose v2 as described in [foundation operations](foundation.md). Existing installations must apply the latest migration; Compose's migration service applies `0006_guided_demo` before the API starts.

```sh
uv sync --frozen --extra dev
# Only for a new installation without .env:
uv run python scripts/configure_demo.py
docker compose up --build --wait api worker
```

Open `http://127.0.0.1:8000/`. English is the default; the language selector switches to Spanish. Each person uses an assigned workspace bearer token, not an OpenAI API key. Retrieve a local demo credential privately:

```sh
uv run python scripts/demo_access.py --role analyst --show-token
uv run python scripts/demo_access.py --role reviewer --show-token
uv run python scripts/demo_access.py --role auditor --show-token
```

Keep those credentials private. The helper hides the token unless `--show-token` is explicitly supplied. The UI holds the entered token in memory, clears the field after sign-in, and clears credentials on sign-out or page reload. Only the language preference is stored in browser local storage. Demo tokens are server-configured identities, not production account sessions or an identity-provider integration.

To explore a prepared case without copying credentials, select **Try demo**. The [guided demo](guided-demo.md) uses isolated sessions and a simulated model. Token-based access above remains available under **Advanced workspace access**.

## Case workflow

1. An assigned analyst creates a synthetic SME/USD case and uploads supported annual CSV/text PDF statements. The **Prepare demonstration draft** action performs extraction and the source-checked AI workflow with the offline provider. It makes no paid OpenAI calls.
2. The analyst assigns a configured independent reviewer or auditor to the case. The assignment directory lists actor IDs and roles, never credentials. Analysts can assign only reviewer/auditor roles on their own cases; there is no role elevation or implicit administrator access.
3. Assigned users inspect findings, the financial fact table, exact source excerpts/locators, retained documents, policy outcomes, evaluation history, and the audit trail. Display labels are localized; underlying API identifiers and stored draft content remain unchanged.
4. An independent reviewer chooses `APPROVED`, `REJECTED`, or `NEEDS_MORE_INFO` and supplies a nonblank reason of at most 4,000 characters. Decisions apply to the simulation only. The reviewer cannot be the evaluation's preparer, even when another credential resolves to the same actor ID.
5. A final review is immutable. `NEEDS_MORE_INFO` does not reopen an evaluation; new documents require another evaluation. Uploading a document clears the case's current evaluation. Historical reviews remain visible but cannot be resubmitted or replaced.

The original draft retains `DRAFT_ONLY` and `requires_human_review`; the separate `review.state` records whether human review has actually occurred. A policy result never becomes a human decision automatically.

The workspace shows up to 50 recent evaluations, prioritizing the current evaluation; `history_truncated` indicates additional history. Cases and audit events have paginated API reads. Source inspection uses normalized PDF text with page/character offsets or CSV row/column locators; the original document remains downloadable. Graphical PDF region highlighting is outside this milestone.

## Review consistency

Review submissions identify the evaluation and `expected_review_state: PENDING`. The server checks identity, case membership, independence, ready draft, current pointer, and absence of a prior review. A case-row lock serializes review, upload, and evaluation-pointer changes. Concurrent decision submissions have one winner; stale or already-reviewed evaluations return 409. Review and audit event commit together.

`Idempotency-Key` is required for assignments and decisions, scoped to actor/route for 24 hours. Replaying the same validated payload returns the stored response without another decision/event. Changing the payload under the same key returns 409. UI visibility is a convenience; server-side authorization remains mandatory.

```json
{
  "expected_review_state": "PENDING",
  "decision": "NEEDS_MORE_INFO",
  "reason": "Additional synthetic evidence is required for the assessment."
}
```

## API operations

| Operation | Purpose / access |
|---|---|
| `GET /v1/me` | Current actor and role; no credentials returned |
| `GET /v1/assignment-directory` | Configured reviewer/auditor choices; analysts only |
| `GET /v1/cases?limit=30&offset=0` | Cases assigned to the current actor and role |
| `GET /v1/cases/{id}/workspace` | Case, document inventory, recent evaluations, and members |
| `POST /v1/cases/{id}/members` | Assign configured reviewer/auditor; assigned analyst only |
| `GET /v1/cases/{id}/evaluations/{evaluation_id}/review` | Review state and whether this actor may review |
| `POST /v1/cases/{id}/evaluations/{evaluation_id}/review` | Record the independent decision and reason |
| `GET /v1/cases/{id}/evaluations/{evaluation_id}/report.json?locale=en` | Verified ready-draft JSON export; assigned users |
| `GET /v1/cases/{id}/evaluations/{evaluation_id}/report.pdf?locale=es` | Verified PDF export with embedded JSON; assigned users |

See [OpenAPI](../contracts/openapi.json) for request/response schemas. Invisible cases return 404; unavailable/stale review or export state returns 409; invalid fields or reasons return 422.

## Report reconstruction

Reports require a ready draft but may be exported before or after human review. They include the selected evaluation's current/historical flag, immutable draft, facts/evidence, calculations, pinned policy/citations, retained-document metadata, human review, and a point-in-time case audit chain. Reasons remain in the language entered by the reviewer; the application does not translate or rewrite a human assessment.

Before export, the server verifies original document SHA-256 values, reparses bytes against retained parser output, checks exact evidence locators, verifies draft/policy hashes, recomputes DSCR and its rule, and verifies the complete audit hash chain. A failed integrity check blocks export with 409. Reconstruction reuses retained model results and does not call an LLM. Reports are limited to 2 MB of canonical content and 2,000 audit events.

JSON exports include `integrity.payload_sha256`: SHA-256 of the UTF-8 canonical report body **without** its `integrity` field. Canonical JSON uses sorted keys, separators `(',', ':')`, and unescaped Unicode. Times are normalized to UTC.

Each PDF embeds the exact `report.json` used to render it. Its displayed hash can be checked against that embedded snapshot. Separately requested JSON/PDF exports can have different generation times and therefore different hashes. The PDF is not digitally signed; application hashes and the database audit chain do not provide an independent trust anchor against a database owner who can rewrite data and hashes. Downloads are read-only and do not append audit events.

The UI renders untrusted content with text nodes, and PDF paragraphs escape markup. Static scripts/styles are served with explicit MIME types, a same-origin content-security policy, no external frontend resources, no-store responses, and no-referrer headers. The demo remains local and synthetic; production identity, operational retention, load limits, and further resilience verification belong to Phase 6 or later decisions.

## Verification

```sh
uv run python scripts/smoke_review.py --output-dir storage/review-demo
uv run pytest -q
```

The smoke workflow creates synthetic CSV/PDF sources, prepares an offline-model draft, assigns reviewer/auditor access, records `NEEDS_MORE_INFO`, verifies idempotent replay and duplicate rejection, and exports both formats/locales. Private credentials are never printed. Generated artifacts stay under ignored `storage/`.

PostgreSQL-backed tests cover authorization, assignment, mandatory reasons, terminal decisions, concurrent submissions, stale/cross-case reviews, source/audit corruption, report checksums, and PDF text/embedded snapshots. Browser verification covers analyst assignment, independent Spanish review, source inspection, PDF download, and desktop/mobile presentation. Representative English/Spanish PDFs are rasterized and visually checked for clipping, pagination, and glyphs. GitHub Actions repeats backend and Compose smoke checks; the live OpenAI allowance is unchanged by these offline tests.

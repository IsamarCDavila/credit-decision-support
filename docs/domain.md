# Domain contracts v0.1

**English** | [Español](es/domain.md)

## Facts and evidence

A fact contains `fact_id`, `evaluation_id`, a key, a decimal value encoded as a string or null, currency, unit, an ISO period with start and end dates, the `individual` accounting basis, status, and `evidence_ids`. Status values are `extracted`, `missing` (no source), `ambiguous` (incompatible sources or interpretations), and `invalid` (contract violation). There is no `unknown` status. Only `extracted` facts enter calculations. Optional confidence is an uncalibrated signal and never replaces validation.

Evidence contains `evidence_id`, a document reference, SHA-256, and an exact excerpt. PDF locators use a page number starting at 1 and offsets into normalized page text starting at 0, with an exclusive end offset and parser version. CSV locators use rows starting at 2, with the header in row 1, and a unique column name. Hash integrity and correspondence between excerpt and extracted value must be verified. Visual regions are a future extension.

A calculation contains `calculation_id`, formula identifier and version, input fact IDs, a decimal or null result, and status. A report claim contains `claim_id`, text, materiality, `evidence_ids`, and `calculation_ids`. Rules cite `policy_fragment_ids`. Unsupported conclusions cannot be presented as verified; missing-data warnings must be explicit. Critical results use report templates.

## Independent states

- Processing: `CREATED → DOCUMENTS_RECEIVED → EXTRACTING → VALIDATING → POLICY_CHECK → DRAFT_READY`. The evaluation is immutable after draft publication.
- Review: `NOT_READY → PENDING → APPROVED | REJECTED | NEEDS_MORE_INFO`. DRAFT_READY starts PENDING. Every human transition records the actor, reason, and UTC timestamp.
- Recommendation: `DRAFT_ONLY`, with an outcome of `meets_rules`, `exceptions`, or `insufficient_evidence`. It never changes the human review state directly.

FAILED_RETRYABLE resumes from the last committed step, with at most three attempts per step, followed by FAILED_TERMINAL. Each step has a unique `(evaluation_id, step, input_hash)` key to deduplicate results and events. An expired lease allows another worker to claim the job. Effects and events commit within the same transaction when both reside in the database.

NEEDS_MORE_INFO does not reopen an evaluation: new documents create another evaluation. A case retains `current_evaluation_id`; replacing it makes previous reviews historical without deleting them. Review requires the evaluation ID and expected review state. An evaluation that is no longer current or has already been reviewed returns 409. Case-row locking during selection and review prevents races.

## Policy publication and versions

A published policy fixes scope, validity dates, text, fragments, rules, and hashes. Publication is transactional, with locking by scope to prevent overlaps. The engine uses allowed operators and typed rules without `eval` or arbitrary code. Published policies require a new version for changes. The evaluator pins the version before retrieving text.

## HTTP and authorization

Roles are `analyst`, `reviewer`, `auditor`, and `admin`, with additional case-level authorization. Analysts create cases, upload documents, and request evaluations. Reviewers review; auditors read reports and events. Administrators publish policies but do not automatically receive access to every case. A stable demo identity is resolved server-side rather than trusting a client-supplied role.

`Idempotency-Key` is required for case creation, upload, evaluation, and review, scoped to actor and route with a 24-hour lifetime. Store the payload hash and response. An identical request returns the same response; a different payload under the same key returns 409. Active execution of the same snapshot is deduplicated even if the key changes. Subsequent uploads never alter previous snapshots.

Common errors: 400 malformed input; 401 missing identity; 403 unauthorized; 404 absent or invisible resource; 409 conflicting state; 413 upload limit exceeded; 422 syntactically valid but unacceptable content. Limits are 10 MiB per document, 20 documents per case, and 100 pages per PDF. Reports require DRAFT_READY and always include the simulation label and current human review state: SIMULATION in English, SIMULACIÓN in Spanish.

## Reconstruction and retention

Reconstruction retrieves stored snapshots and outputs and verifies hashes, rules, citations, and review. It does not guarantee identical LLM regeneration. Model responses, parameters, prompts, and versions are retained with restricted access; secrets are excluded. The local demo retains data until explicit deletion. Documented cleanup removes attachments and outputs while leaving content-free tombstones; the affected case can no longer be described as reconstructible. Real PII is excluded.

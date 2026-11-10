# ADR-002: Transactional synthetic document ingestion

**English** | [Español](../es/adr/002-ingestion.md)

Status: accepted for Phase 2. Date: 2026-11-10.

## Context

The bounded demo admits at most 20 synthetic documents per case and 10 MiB per document. Ingestion must retain the original bytes, evidence locators, hashes, and parser version without creating inconsistencies between file storage, metadata, and audit events.

## Decisions

1. Store immutable document bytes and parsed source representations in PostgreSQL, under a restricted runtime role. Original bytes, metadata, and the upload audit event commit in one transaction. This replaces the initial private-filesystem storage proposal for the bounded MVP. Object storage remains a possible extension with explicit recovery and retention rules.
2. Accept a versioned synthetic statement schema rather than claiming support for arbitrary financial PDFs. CSV uses exact columns; PDF uses explicit text labels. Inputs declare synthetic data, USD, a complete calendar year, and standalone statements. A declaration is not automated proof of provenance or absence of PII.
3. Parse in a separate process without a shell, with a 15-second timeout. Linux imposes a 512 MiB address-space and 12-second CPU ceiling. Windows has the process timeout and file/text/page limits but no equivalent hard memory ceiling. Parsing does not execute document instructions, scripts, or embedded actions.
4. Persist normalized PDF page text and CSV rows with a parser version. PDF offsets use zero-based Unicode code-point indices into NFC-normalized page text with LF line endings, with an exclusive end. CSV rows start at 2 after the header; multiline cells are excluded.
5. Extraction snapshots pin document identifiers, SHA-256 values, and parser versions. The worker verifies integrity and locators before storing facts and evidence atomically. New uploads invalidate the current pointer without deleting historical evaluations.
6. Use deterministic extraction only. Missing, invalid, and conflicting values remain explicit, without filling gaps or calculating financial ratios. Completion leaves the evaluation at VALIDATING; policy checks, recommendation drafts, and human decisions are later stages.

## Consequences

The demo is reproducible and does not require an LLM or a separate object store. Database and backup size grow with uploaded documents, so this design does not establish a production storage strategy. Known-schema extraction does not establish accuracy on real financial documents. Converting to object storage or expanding supported formats requires a new decision and corresponding evidence tests.

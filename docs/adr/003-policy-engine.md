# ADR-003: Deterministic policy checks and lexical retrieval baseline

**English** | [Español](../es/adr/003-policy-engine.md)

Status: accepted for Phase 3. Date: 2026-11-10.

## Decisions

1. Policy applicability is selected before retrieval by segment, currency, standalone accounting basis, publication status, and case cutoff. Validity is `valid_from <= cutoff < valid_to`, with an unbounded upper endpoint when null. Zero or multiple matches block evaluation; retrieval rank cannot select a policy.
2. The catalog accepts one explicit synthetic rule: `DSCR >= threshold`. Rule parameters generate versioned English and Spanish policy fragments. The original specification, rendered fragments, and rule parameters share a content hash. Publication is transactional, idempotent for identical content, and rejects identifier reuse with changed content or overlapping validity. Published content is immutable.
3. Publication runs through an administrator CLI using the database owner. The API/worker runtime role has read-only catalog access. The API exposes policy reads and searches, not publication. This separates policy administration from ordinary case processing without giving runtime users schema-owner credentials.
4. PostgreSQL full-text search provides the initial English/Spanish retrieval baseline, always filtered by an explicit policy version. It can return no results. Embeddings, pgvector, reranking, and LLM drafting remain later options that require evidence against this baseline. This supersedes the proposed Phase 3 pgvector timing, not the requirement for version-filtered citations.
5. DSCR uses annual available cash flow divided by annual debt service, with USD amounts, matched full-calendar-year periods, and verified input facts. Zero debt service is NOT_APPLICABLE; negative debt service is INVALID_INPUT; negative cash flow remains a valid negative ratio. Missing or ambiguous inputs are not calculated. EBITDA is not substituted.
6. Ratio division uses a local 80-digit Decimal context. Display uses four decimals with ROUND_HALF_UP. Threshold decisions compare `cash_flow >= threshold * debt_service` before rounding, preserving exact finite-decimal comparison within the supported amount range. Numerator, denominator, formula version, and input fact IDs are retained; the stored quotient is a finite-precision representation, not an exact representation of every rational number.
7. A policy evaluation creates a separate snapshot that pins documents, policy hash, formula version, and source extraction ID. It deterministically rebuilds its own facts from the retained sources and stores calculations, citations, result, and completion event atomically. Completed check inputs are sealed. The extraction history remains unchanged.
8. Results are `meets_rules`, `exceptions`, or `insufficient_evidence`; none is a credit approval or rejection. Any field-quality exception makes the overall result insufficient, even if the DSCR rule passes. This stage ends at POLICY_CHECK, with no model-generated draft or human resolution.

## Consequences

The baseline works without a model provider and can be compared against independent exact-fraction references. Supported rules and statement formats remain deliberately narrow. The two catalog examples are fictitious and do not represent bank lending standards. Adding rules, policy amendment/retirement workflows, semantic retrieval, or production publishing requires additional design and tests.

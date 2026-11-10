# Phase 0: Specification baseline

**English** | [Español](es/phase-0-delivery.md)

## Available artifacts

The design baseline defines SME cases in USD, full annual periods, and standalone financial statements. It includes an architecture decision; evidence, policy, calculation, review, and idempotency contracts; preliminary PostgreSQL DDL; nine initial HTTP routes; a synthetic fixture; a threat model; and phase acceptance criteria.

## Validation scope

`./scripts/check-phase0.ps1` checks initial route structure, evidence references, CSV locators, document SHA-256, and decimal DSCR. The supplied fixture passes these checks.

This validation does not include complete OpenAPI schema validation, executed PostgreSQL DDL, backend behavior, or performance measurements. SQL constraints and API descriptions represent planned behavior until implemented and tested.

## Foundation acceptance requirements

The foundation milestone completes HTTP response schemas and validates the OpenAPI contract, translates the preliminary DDL into migrations, and tests transactional constraints. It also establishes demo identity, authorization, persistence, runtime configuration, and CI. Live-model provider selection is required before AI evaluation; licensing remains an open project decision.

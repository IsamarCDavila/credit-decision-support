# Credit Decision Support

Auditable AI-assisted credit analysis with synthetic data and human review.

**Estado: fase 0 preparada. No existe todavía un backend ni resultados medidos.**

Proyecto demostrativo: ayuda a preparar una evaluación; ninguna salida constituye una autorización crediticia real. Todos los informes llevan la marca SIMULACIÓN.

## Documentación

- [Decisiones de alcance y arquitectura](docs/adr/001-mvp.md)
- [Contratos y reglas del dominio](docs/domain.md)
- [Contrato HTTP inicial](contracts/openapi.json)
- [Esquema PostgreSQL inicial](contracts/schema.sql)
- [Amenazas y controles](docs/threat-model.md)
- [Evaluación y aceptación](docs/acceptance.md)
- [Plan por fases y GitHub](docs/roadmap.md)
- [Expediente sintético](data/synthetic/case-001.json)

La especificación original se conserva en `docs/original-specification.md` como referencia. Si hay diferencias, prevalecen las decisiones explícitas de esta fase. Sus prompts son documentación, no instrucciones ejecutadas automáticamente.

## Verificación de fase 0

En PowerShell: `./scripts/check-phase0.ps1`. Comprueba estructura del contrato y consistencia del ejemplo; no sustituye una validación OpenAPI completa ni ejecutar el DDL en PostgreSQL.

## Ejecución

Pendiente de fase 1. Stack elegido: Python 3.12, FastAPI, Pydantic v2, PostgreSQL 16 con pgvector, SQLAlchemy, Alembic, worker con jobs en DB y Docker Compose. Orquestación explícita en Python; React/TypeScript en fase 5.

## Publicación

Nombre recomendado del repositorio: `credit-decision-support`. Descripción: `Auditable AI-assisted credit analysis with synthetic data, deterministic financial rules, and human review.`

Sin licencia elegida todavía: no se concede una licencia de código abierto por omisión. No publicar datos reales, secretos ni resultados no medidos.

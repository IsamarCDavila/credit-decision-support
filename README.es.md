# Credit Decision Support

[English](README.md) | **Español**

Análisis crediticio asistido por IA con trazabilidad, datos sintéticos, reglas financieras deterministas y revisión humana.

## Estado del proyecto

**Etapa de diseño — Fase 0.** El repositorio contiene la especificación del MVP, decisiones de arquitectura, contratos iniciales y criterios de aceptación. El backend no está implementado. Las metas de rendimiento y calidad del modelo todavía no se han medido.

El MVP admite expedientes PyME en USD, periodos anuales completos y estados financieros individuales. Prepara análisis respaldados por evidencia para un revisor humano. Los informes llevan la marca **SIMULACIÓN**; las recomendaciones no autorizan créditos reales.

## Documentación

| Documento | Propósito |
|---|---|
| [Especificación del proyecto](docs/es/specification.md) | Problema, alcance, arquitectura y metas de diseño |
| [Decisión de arquitectura](docs/es/adr/001-mvp.md) | Alcance del MVP y elecciones técnicas |
| [Contratos de dominio](docs/es/domain.md) | Evidencia, cálculos, políticas y estados de revisión |
| [Contrato HTTP inicial](contracts/openapi.json) | Operaciones propuestas de la API |
| [Esquema PostgreSQL inicial](contracts/schema.sql) | Modelo de persistencia propuesto |
| [Modelo de amenazas](docs/es/threat-model.md) | Amenazas, controles previstos y verificación |
| [Evaluación y aceptación](docs/es/acceptance.md) | Métricas, casos de prueba y criterios por fase |
| [Hoja de ruta](docs/es/roadmap.md) | Hitos de implementación y proceso de entrega |
| [Estado de fase 0](docs/es/phase-0-delivery.md) | Artefactos disponibles y límites de validación |
| [Ejemplo sintético](data/synthetic/case-001.json) | Referencias de evidencia y cálculo DSCR esperado |

## Validar el ejemplo de diseño

Requisito: PowerShell 7.2 o posterior. Desde la raíz del repositorio:

```powershell
./scripts/check-phase0.ps1
```

La comprobación verifica rutas iniciales, referencias de evidencia, localizadores CSV, SHA-256 del documento y DSCR decimal del ejemplo. No valida la especificación OpenAPI completa, no ejecuta el DDL de PostgreSQL ni prueba un backend.

## Entorno de ejecución previsto

Python 3.12, FastAPI, Pydantic v2, PostgreSQL 16 con pgvector, SQLAlchemy, Alembic y Docker Compose. Una máquina de estados explícita en Python y un worker con trabajos persistidos en base de datos gestionan la orquestación. React/TypeScript está previsto para la interfaz de revisión. Las instrucciones de instalación y arranque corresponden al hito de infraestructura base.

## Datos y licencia

Solo se admiten documentos y expedientes sintéticos. Las credenciales, los datos reales de clientes y los registros del proveedor deben permanecer fuera del control de versiones. No se ha seleccionado una licencia; no se concede una licencia de código abierto por omisión.

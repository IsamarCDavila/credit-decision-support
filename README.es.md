# Credit Decision Support

[English](README.md) | **Español**

Análisis crediticio asistido por IA con trazabilidad, datos sintéticos, reglas financieras deterministas y revisión humana.

## Estado del proyecto

**Espacio de revisión humana — Fase 5.** La aplicación ingiere estados sintéticos PDF/CSV, verifica observaciones propuestas por modelos, calcula DSCR, comprueba políticas versionadas y prepara borradores bilingües con evidencia. La interfaz permite asignar expedientes, realizar una revisión independiente, consultar fuentes/auditoría y exportar JSON/PDF verificados. OpenAI sigue siendo opcional y está desactivado por defecto, con asignación acumulada de US$2. Seguridad, resiliencia y carga medida corresponden a la fase 6.

El MVP admite expedientes PyME en USD, periodos anuales completos y estados financieros individuales. Prepara análisis respaldados por evidencia para un revisor humano. Los informes llevan la marca **SIMULACIÓN**; las recomendaciones no autorizan créditos reales.

## Probar la demo

Con la aplicación en ejecución, abrir `http://127.0.0.1:8000/`, seleccionar **Probar demo** y elegir Analista, Revisor o Auditor. Cada sesión incluye un expediente ficticio propio y permite cambiar de rol, revisar evidencia y exportar informes. No requiere copiar tokens ni consume OpenAI. La misma persona puede simular los tres roles; no demuestra separación entre personas reales. Consultar la [demo guiada](docs/es/guided-demo.md).

## Documentación

| Documento | Propósito |
|---|---|
| [Espacio de revisión humana](docs/es/human-review.md) | Acceso web, asignación, decisiones, reconstrucción de informes y demo |
| [Flujo de IA con evidencia](docs/es/ai-workflow.md) | Roles, validación, configuración de OpenAI, costos y límites de comparación |
| [Catálogo y controles financieros](docs/es/policy-engine.md) | Selección de políticas, DSCR, citas y verificación de referencia |
| [Ingesta documental](docs/es/ingestion.md) | Formatos, extracción con evidencia, límites y demo |
| [Operación de infraestructura base](docs/es/foundation.md) | Arranque, acceso a API, worker y verificación |
| [Especificación del proyecto](docs/es/specification.md) | Problema, alcance, arquitectura y metas de diseño |
| [Decisión de arquitectura](docs/es/adr/001-mvp.md) | Alcance del MVP y elecciones técnicas |
| [Contratos de dominio](docs/es/domain.md) | Evidencia, cálculos, políticas y estados de revisión |
| [Contrato HTTP](contracts/openapi.json) | Operaciones implementadas de la API |
| [Esquema PostgreSQL](contracts/schema.sql) | Esquema base y controles de datos |
| [Modelo de amenazas](docs/es/threat-model.md) | Amenazas, controles previstos y verificación |
| [Evaluación y aceptación](docs/es/acceptance.md) | Métricas, casos de prueba y criterios por fase |
| [Hoja de ruta](docs/es/roadmap.md) | Hitos de implementación y proceso de entrega |
| [Estado de fase 0](docs/es/phase-0-delivery.md) | Artefactos disponibles y límites de validación |
| [Referencia sintética medida](evaluations/reports/deterministic-baseline.json) | Concordancia y tiempos observados sobre diez casos controlados |
| [Ejemplo sintético](data/synthetic/case-001.json) | Referencias de evidencia y cálculo DSCR esperado |

## Validar el ejemplo de diseño

Requisito: PowerShell 7.2 o posterior. Desde la raíz del repositorio:

```powershell
./scripts/check-phase0.ps1
```

La comprobación verifica rutas iniciales, referencias de evidencia, localizadores CSV, SHA-256 del documento y DSCR decimal del ejemplo. No valida la especificación OpenAPI completa, no ejecuta el DDL de PostgreSQL ni prueba un backend.

## Ejecución local

Requisitos: Python 3.12, uv y Docker Compose v2.

```sh
uv sync --frozen --extra dev
uv run python scripts/configure_demo.py
docker compose up --build --wait api worker
uv run python scripts/smoke_ingestion.py
uv run python scripts/smoke_policy.py
uv run python scripts/evaluate_ai.py --provider mock --output storage/ai-mock.json
uv run python scripts/smoke_review.py
uv run python scripts/smoke_guided_demo.py
```

La interfaz abre en `http://127.0.0.1:8000/`; la documentación interactiva de la API está en `/docs`. La configuración crea credenciales locales privadas y rechaza sobrescribir `.env`. La [guía de revisión](docs/es/human-review.md) explica el acceso y el flujo de revisión; la [guía de ingesta](docs/es/ingestion.md), los formatos; y la [operación base](docs/es/foundation.md), la identidad y base de datos.

## Datos y licencia

Solo se admiten documentos y expedientes sintéticos. Las credenciales, los datos reales de clientes y los registros del proveedor deben permanecer fuera del control de versiones. No se ha seleccionado una licencia; no se concede una licencia de código abierto por omisión.

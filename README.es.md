# Credit Decision Support

[English](README.md) | **Español**

Análisis crediticio asistido por IA con trazabilidad, datos sintéticos, reglas financieras deterministas y revisión humana.

## Estado del proyecto

**Infraestructura base — Fase 1.** El backend permite crear expedientes sintéticos, aplicar permisos por expediente, gestionar idempotencia y consultar auditoría. Se implementaron migraciones PostgreSQL y un worker persistente. La ingesta documental, evaluación financiera e interfaz de revisión corresponden a hitos posteriores. Las metas de rendimiento y calidad de modelos permanecen sin medir.

El MVP admite expedientes PyME en USD, periodos anuales completos y estados financieros individuales. Prepara análisis respaldados por evidencia para un revisor humano. Los informes llevan la marca **SIMULACIÓN**; las recomendaciones no autorizan créditos reales.

## Documentación

| Documento | Propósito |
|---|---|
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
uv run python scripts/smoke_api.py
```

La API se ejecuta en `http://127.0.0.1:8000`; su documentación interactiva se encuentra en `/docs`. La generación de configuración crea credenciales locales privadas y rechaza sobrescribir `.env`. La [guía de operación](docs/es/foundation.md) describe permisos, requisitos de base de datos, pruebas y limitaciones actuales.

## Datos y licencia

Solo se admiten documentos y expedientes sintéticos. Las credenciales, los datos reales de clientes y los registros del proveedor deben permanecer fuera del control de versiones. No se ha seleccionado una licencia; no se concede una licencia de código abierto por omisión.

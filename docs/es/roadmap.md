# Hoja de ruta de implementación

[English](../roadmap.md) | **Español**

El proyecto avanza mediante hitos revisables de forma independiente. La fase 0 define el sistema; las fases posteriores lo implementan y verifican.

| Fase | Rama | Entregable | Evidencia de aceptación |
|---|---|---|---|
| 0 — Especificación | `docs/phase-0-specification` | Arquitectura, dominio, contratos SQL/HTTP iniciales y ejemplo sintético | Comprobaciones de contratos y límites del diseño |
| 1 — Infraestructura base | `feat/phase-1-foundation` | FastAPI, persistencia, migraciones, identidad demo, autorización, worker persistente mínimo, Compose y CI | Servicios saludables, migraciones desde cero y CI aprobado |
| 2 — Ingesta | `feat/phase-2-ingestion` | Generador sintético e ingesta PDF/CSV con evidencia | Pruebas de parser, localizadores y límites de entrada |
| 3 — Motor de políticas | `feat/phase-3-policy-engine` | Selección de políticas versionadas y cálculos financieros deterministas | Evaluación de referencia y casos límite |
| 4 — Flujo de IA | `feat/phase-4-ai-workflow` | Extracción validada, redacción, adaptador de modelos y mock sin conexión | Evaluación reproducible y costes medidos |
| 5 — Revisión humana | `feat/phase-5-human-review` | Interfaz de revisión, historial de auditoría e informes JSON/PDF | Demo de extremo a extremo, autorización y concurrencia |
| 6 — Robustecimiento | `test/phase-6-hardening` | Seguridad, resiliencia, observabilidad y verificación de carga | Límites medidos e informes reproducibles de pruebas |

## Proceso de entrega

Cada fase utiliza una rama y un pull request dirigido a `main`. Cada hito incluye cambios revisables, validación reproducible, documentación actualizada en ambos idiomas y limitaciones relevantes. La integración requiere criterios de aceptación y comprobaciones aprobados; la siguiente rama parte de `main` actualizado. Se pueden agrupar commits si un único commit del hito aporta claridad, o conservar commits pequeños si facilitan la revisión.

La versión `v0.1.0` identifica una base ejecutable. La versión `v1.0.0` requiere cumplir todos los criterios del MVP. La especificación inicial no constituye una versión del producto.

## Dependencias y ampliaciones

La infraestructura base requiere Python 3.12 y Docker Compose. La fase 4 incorpora un mock sin conexión e integración opcional con OpenAI y asignación acumulada de US$2 en la aplicación; véase el [flujo de IA](ai-workflow.md). Las mediciones reales se distinguen de las pruebas simuladas de orquestación.

Temporal, MCP, Kafka, Kubernetes, OCR, conversión de moneda y segmentos financieros adicionales permanecen como ampliaciones separadas. Cada una requiere una decisión de arquitectura, una necesidad definida y mediciones apropiadas. Se pueden versionar ejemplos sintéticos pequeños; se excluyen credenciales, documentos reales y registros de proveedores.

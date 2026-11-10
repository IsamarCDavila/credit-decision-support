# Entregas por fase y GitHub

Repositorio sugerido: `credit-decision-support`. Fase 0 describe el sistema; no representa una implementación terminada.

| Fase | Rama | Commit propuesto | Evidencia para PR |
|---|---|---|---|
| 0 | docs/phase-0-specification | docs: define MVP contracts and acceptance criteria | comprobación de contratos y limitaciones |
| 1 | feat/phase-1-foundation | feat: bootstrap API persistence and CI | Compose, migraciones y CI |
| 2 | feat/phase-2-ingestion | feat: ingest synthetic documents with evidence | parser y generador probados |
| 3 | feat/phase-3-policy-engine | feat: add versioned policy rules and financial calculations | baseline y casos límite |
| 4 | feat/phase-4-ai-workflow | feat: add validated AI extraction and drafting | evaluación reproducible y costes |
| 5 | feat/phase-5-human-review | feat: add human review and audit reports | demo E2E, permisos y concurrencia |
| 6 | test/phase-6-hardening | test: verify resilience security and performance | informe de límites medidos |

Cada fase termina con diff revisable, comandos y resultados reales, README actualizado y lista de limitaciones. Abrir PR hacia main, revisar y fusionar solo con checks aprobados; después empezar la siguiente rama desde main. Usar squash para un commit claro por fase o conservar commits pequeños si facilitan revisión. Crear etiquetas v0.1.0 al tener la base ejecutable y v1.0.0 solo al completar el MVP; la documentación inicial no necesita release de producto.

No subir .env, claves, PDFs reales, logs de proveedor ni datos bancarios. Los fixtures sintéticos pequeños sí pueden versionarse. Mantener cambios de infraestructura avanzada en PR separados, cada uno con ADR y benchmark.

## Siguiente trabajo concreto

Fase 1 implementa configuración, identidad demo por token local, permisos por caso, modelos/migraciones, endpoints base, worker persistente mínimo, Compose y CI. No requiere elegir proveedor LLM todavía. Verificar Docker y Python antes de prometer ejecución local; en este entorno Python no está disponible actualmente.

## Conexión inicial a GitHub

Crear repositorio vacío con el nombre sugerido en la cuenta elegida; usar descripción del README. La visibilidad y licencia se eligen explícitamente. Con el remoto confirmado, iniciar Git en esta carpeta, crear la rama de fase 0 y subirla. No se ha creado un repositorio remoto durante esta entrega.

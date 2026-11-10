# Entrega de fase 0 — 2026-11-10

## Resultado

Especificación original preservada y decisiones complementarias documentadas. Alcance PyME/USD/anual/individual. Contratos de evidencia, política, cálculo, revisión e idempotencia; DDL preliminar; nueve rutas HTTP; fixture sintético; amenazas y evaluación; roadmap por PR.

## Validación ejecutada

`./scripts/check-phase0.ps1`: PASS para rutas iniciales, referencias, localizadores CSV, SHA-256 y DSCR decimal. No es un validador completo de OpenAPI. No se ejecutó el DDL, ni existe todavía backend o suite pytest. Python, Docker y psql no estaban disponibles en PATH; Git y Node sí.

## Trabajo que continúa en fase 1

Completar esquemas de respuestas HTTP y validarlos contra OpenAPI, traducir DDL a migraciones y probar restricciones transaccionales. No confundir presencia de un contrato preliminar con comportamiento implementado. Configurar runtime Python y Docker, identidad demo y CI. Proveedor LLM y licencia permanecen pendientes y no bloquean el backend inicial.

## Texto sugerido para PR

Título: `docs: define credit decision support MVP and phase gates`

Define un MVP de evaluación crediticia simulada con políticas seleccionadas de forma determinista, evidencia identificable y decisiones humanas sobre snapshots inmutables. Añade contratos iniciales de dominio, SQL y HTTP, un expediente sintético verificable y criterios de aceptación por fase.

Validación: comprobación PowerShell aprobada para las rutas y el expediente de ejemplo. El contrato HTTP y el DDL son preliminares: la validación completa, migraciones ejecutadas y pruebas del backend corresponden a fase 1. No hay resultados de rendimiento medidos.

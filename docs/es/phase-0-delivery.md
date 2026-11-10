# Fase 0: Especificación inicial

[English](../phase-0-delivery.md) | **Español**

## Artefactos disponibles

La especificación inicial define expedientes PyME en USD, periodos anuales completos y estados financieros individuales. Incluye una decisión de arquitectura; contratos de evidencia, políticas, cálculos, revisión e idempotencia; DDL preliminar de PostgreSQL; nueve rutas HTTP iniciales; un ejemplo sintético; un modelo de amenazas y criterios de aceptación por fase.

## Alcance de validación

`./scripts/check-phase0.ps1` comprueba la estructura inicial de rutas, referencias de evidencia, localizadores CSV, SHA-256 del documento y DSCR decimal. El ejemplo incluido supera estas comprobaciones.

La validación no incluye la especificación OpenAPI completa, ejecución del DDL de PostgreSQL, comportamiento del backend ni mediciones de rendimiento. Las restricciones SQL y las descripciones de API representan comportamiento previsto hasta implementarse y probarse.

## Requisitos de aceptación de infraestructura base

El hito de infraestructura base completa los esquemas de respuestas HTTP y valida el contrato OpenAPI, traduce el DDL preliminar a migraciones y prueba las restricciones transaccionales. También establece identidad demo, autorización, persistencia, configuración de ejecución y CI. La elección del proveedor de modelos es necesaria antes de evaluar IA; la licencia permanece como decisión abierta del proyecto.

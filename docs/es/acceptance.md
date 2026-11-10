# Evaluación y criterios de avance

[English](../acceptance.md) | **Español**

## Protocolo

Generador determinista con seed, versión y ground truth independiente de las salidas del modelo. Separar train/dev/test por expediente y familia de plantilla para reducir filtración de formato. Test se congela antes de ajustar prompts. Los diez casos E2E son smoke tests, no evidencia suficiente de una fiabilidad del 99 %.

Comparación: A extracción determinista; B un solo flujo LLM con las mismas herramientas; C agentes especializados. B y C usan mismo modelo, presupuesto máximo, documentos, política y herramientas. Reportar tokens, coste y latencia reales, y realizar al menos tres repeticiones por caso. Una comparación manual requiere personas y protocolo temporal; no fabricar tiempos.

Exactitud: campos correctos / todos los campos esperados; reportar ausentes correctos, errores y abstenciones por separado. Dinero exige igualdad decimal bajo unidad y periodo correctos. Cobertura: afirmaciones materiales respaldadas / todas las afirmaciones materiales emitidas. Abstención: campos y casos abstendidos / campos y casos solicitados, separadamente. Una salida vacía tiene cobertura N/A, nunca 100 %. Tasa de afirmaciones sin soporte usa el mismo conjunto de afirmaciones y reporta además cantidad absoluta. La materialidad se define en una rúbrica antes de evaluar: cifras, cálculos, resultados de reglas y razones de recomendación.

Fiabilidad: trabajos completados válidamente / trabajos iniciados bajo protocolo declarado; fallos inducidos se reportan como cohorte separada. Publicar tamaño de muestra e intervalo de confianza Wilson 95 % para proporciones; no inferir garantía de servicio. Tiempo: mediana y p95 de carga completa a borrador, con entorno y concurrencia. Reconstrucción: snapshots verificables / snapshots retenidos, reportando también los eliminados. Cero errores observados no significa riesgo cero.

## Matriz mínima de casos

1. Completo: flujo 150000, servicio 100000, DSCR 1.5000, regla sintética satisfecha.
2. Umbral exacto 1.20 y valores inmediatamente por debajo/encima: comparación sin redondeo.
3. Servicio cero: NOT_APPLICABLE y revisión, sin división.
4. Servicio negativo: INVALID_INPUT.
5. Flujo negativo con servicio positivo: ratio negativo válido.
6. Cifra ausente y fuentes contradictorias: missing/ambiguous, sin cálculo inventado.
7. Moneda/periodo/base fuera de alcance: bloqueo explícito.
8. Política ausente/solapada y cita de otra versión: bloqueo.
9. Inyección en PDF, cita inexistente y parser roto: fallo controlado.
10. Reinicio, doble envío y revisión obsoleta: sin duplicados y 409 esperado.

## Puerta fase 0

- ADR, dominio, DDL preliminar, OpenAPI inicial, amenazas y ejemplo disponibles.
- Ejemplo coherente y comprobaciones PowerShell aprobadas.
- Decisiones pendientes visibles: identidad demo, licencia y proveedor/presupuesto real.
- No se declara backend, migración aplicada ni OpenAPI validado por herramienta completa.

## Puertas posteriores

1. Base: Compose saludable, migraciones desde cero, API autorizada por caso, CI pytest/Ruff/mypy y escaneo de secretos; invariantes transaccionales del DDL implementadas y probadas.
2. Ingesta: PDFs/CSV sintéticos reproducibles con localizadores verificables y límites.
3. Políticas: selección sin solapamiento, ratios exactos y baseline sin LLM.
4. IA: mock offline, adaptador intercambiable, validación de citas y benchmark B/C.
5. Humano: UI, revisión con motivo, concurrencia, reporte SIMULACIÓN y auditoría reconstruible.
6. Hardening: diez E2E como mínimo, pruebas adversariales/resiliencia y límites de carga medidos. Metas del original se reportan como cumplidas o incumplidas con evidencia.

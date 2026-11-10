# ADR-003: Políticas deterministas y referencia de recuperación léxica

[English](../../adr/003-policy-engine.md) | **Español**

Estado: aceptado para la fase 3. Fecha: 2026-11-10.

## Decisiones

1. La política se selecciona antes de recuperar fragmentos por segmento, moneda, base individual, publicación y fecha de corte del expediente. La vigencia es `valid_from <= cutoff < valid_to`, sin límite superior cuando es null. Cero o varias coincidencias bloquean la evaluación; la relevancia de búsqueda no elige la política.
2. El catálogo admite una regla sintética explícita: `DSCR >= threshold`. Sus parámetros generan fragmentos versionados en inglés y español. La especificación original, fragmentos y parámetros comparten un hash de contenido. La publicación es transaccional, idempotente para contenido idéntico y rechaza identificadores reutilizados con cambios o vigencias solapadas. El contenido publicado es inmutable.
3. La publicación se ejecuta mediante CLI de administración con el propietario de la base. El rol de API/worker solo lee el catálogo. La API permite consultas y búsquedas, no publicación. Esto separa la administración de políticas del procesamiento de expedientes sin entregar credenciales de propietario al runtime.
4. PostgreSQL full-text search constituye la referencia inicial de recuperación en inglés/español, siempre filtrada por una versión explícita. Puede devolver cero resultados. Embeddings, pgvector, reranking y redacción LLM permanecen como opciones posteriores que requieren evidencia frente a esta referencia. Esto sustituye el calendario propuesto de pgvector en fase 3, no el requisito de citas filtradas por versión.
5. El DSCR utiliza flujo anual disponible dividido por servicio de deuda anual, importes USD, periodos de año calendario completo coincidentes y hechos verificados. Servicio cero produce NOT_APPLICABLE; negativo produce INVALID_INPUT; flujo negativo conserva un ratio negativo válido. Los datos faltantes o ambiguos no se calculan. No se sustituye el flujo por EBITDA.
6. La división utiliza un contexto Decimal local de 80 dígitos. La presentación usa cuatro decimales y ROUND_HALF_UP. El umbral se decide mediante `cash_flow >= threshold * debt_service` antes de redondear, conservando comparación exacta de decimales finitos dentro del rango admitido. Se guardan numerador, denominador, versión e identificadores de hechos; el cociente almacenado tiene precisión finita y no representa exactamente cualquier número racional.
7. Una evaluación crea un snapshot separado que fija documentos, hash de política, versión de fórmula e identificador de extracción origen. Reconstruye sus propios hechos de forma determinista desde las fuentes y guarda cálculos, citas, resultado y evento de finalización atómicamente. Las entradas quedan selladas al completar el control. El historial de extracción no cambia.
8. Los resultados son `meets_rules`, `exceptions` o `insufficient_evidence`; ninguno aprueba o rechaza un crédito. Cualquier excepción de calidad produce insuficiencia global, incluso cuando pasa el DSCR. La etapa termina en POLICY_CHECK, sin borrador generado por modelo ni resolución humana.

## Consecuencias

La referencia funciona sin proveedor de modelos y permite comparación contra fracciones exactas independientes. Las reglas y formatos admitidos son deliberadamente acotados. Las dos políticas de ejemplo son ficticias y no representan estándares bancarios. Nuevas reglas, modificación/retiro de políticas, recuperación semántica o publicación de producción requieren diseño y pruebas adicionales.

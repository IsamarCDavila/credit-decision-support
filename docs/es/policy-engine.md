# Catálogo de políticas y controles financieros

[English](../policy-engine.md) | **Español**

## Alcance implementado

La fase 3 incorpora catálogo publicado de políticas sintéticas, recuperación léxica filtrada por versión, cálculo DSCR determinista, evaluación de reglas y referencia reproducible sin modelos. Las políticas en `data/policies/` corresponden a estados individuales PyME/USD. El ejemplo 2026 exige DSCR mínimo de 1,20; el de 2027, mínimo de 1,30. Son ejemplos ficticios de ingeniería, no recomendaciones crediticias.

La fecha de corte del expediente selecciona el intervalo de vigencia semiabierto. No se elige por año financiero, relevancia de búsqueda, criterio del modelo ni identificador más reciente. Debe existir exactamente una versión publicada aplicable. Cada evaluación fija hash de política y versión de fórmula antes de procesar.

## Publicación del catálogo

Docker Compose ejecuta migraciones y publica ambos ejemplos antes de iniciar API/worker. Reiniciar admite paquetes idénticos sin duplicar versiones. Para una base administrada por separado, se ejecutan Alembic y el CLI bajo configuración del propietario de la base:

```sh
uv run alembic upgrade head
uv run python -m credit_support.policy_catalog
```

El CLI también recibe rutas JSON explícitas. Valida ámbito, fechas, operadores y rango de umbral; genera ambos idiomas desde la regla tipada; y almacena especificación, fragmentos, hash y fecha de publicación atómicamente. Rechaza contenido cambiado bajo el mismo identificador y vigencias publicadas solapadas. Las credenciales del propietario se reservan para migración/publicación; API y worker conservan su identidad restringida.

## Flujo de API

| Operación | Propósito |
|---|---|
| `GET /v1/policies` | Listar identificadores publicados del catálogo |
| `GET /v1/policies/{version}` | Consultar especificación verificada y fragmentos bilingües |
| `GET /v1/policies/{version}/fragments?q=DSCR&locale=en` | Buscar exclusivamente en esa versión; admite `en` y `es` |
| `GET /v1/cases/{id}/policy` | Resolver la política aplicable con autorización por expediente |
| `POST /v1/cases/{id}/evaluate` | Encolar controles desde una extracción correcta, con `source_evaluation_id` e `Idempotency-Key` |
| `GET /v1/cases/{id}/evaluations/{evaluation_id}` | Consultar hechos, fuentes, cálculos, resultados y citas de política |

El catálogo requiere autenticación. Las operaciones del expediente requieren membresía; solo analyst puede solicitar evaluación. La extracción debe haber terminado correctamente sobre los documentos actuales. Añadir un documento vuelve obsoleta la extracción origen para nuevos controles hasta repetirla. La idempotencia devuelve la respuesta original durante 24 horas; otra clave también deduplica las mismas entradas fijadas.

La recuperación full-text es una referencia léxica, no RAG semántico. La búsqueda no cambia parámetros ni selecciona políticas. Los términos desconocidos pueden devolver una lista vacía; las citas incluyen versión, identificador, texto bilingüe y hash. El worker utiliza todos los fragmentos normativos de la regla seleccionada, sin depender del ranking para decidir qué restricciones aplicar.

## Convenciones del DSCR

El DSCR divide flujo anual disponible entre servicio de deuda anual. Requiere importes USD verificados, periodos de año calendario completo coincidentes y hasta dos decimales, dentro del rango admitido. Entradas faltantes o ambiguas producen MISSING_INPUT. Importes, unidades o periodos inválidos y servicio de deuda negativo producen INVALID_INPUT. Servicio cero es NOT_APPLICABLE y requiere revisión. El flujo negativo produce un ratio negativo válido.

La presentación utiliza cuatro decimales con redondeo half-up; el umbral se compara mediante multiplicación cruzada exacta. Por ejemplo, `119999.99 / 100000.00` se muestra como `1.2000`, pero no cumple el mínimo de 1,20. Se conservan operandos, identificadores de hechos, versión de fórmula y cociente de alta precisión. No se utiliza float en importes ni comparación de umbrales.

Los estados de regla son PASS, FAIL y REQUIRES_REVIEW. Los resultados globales son:

- `meets_rules`: pasa la regla sintética y los seis campos están verificados.
- `exceptions`: falla la regla con entradas verificadas y sin otras excepciones de calidad.
- `insufficient_evidence`: no se puede evaluar el indicador o algún campo está ausente, ambiguo o inválido.

Estos resultados no aprueban ni rechazan créditos. La etapa termina en POLICY_CHECK; los borradores y endpoints de revisión humana corresponden a hitos posteriores. Los cálculos y entradas quedan sellados, y las citas se restringen a la política fijada.

## Verificación reproducible

Después de configurar y arrancar:

```sh
uv run python scripts/smoke_ingestion.py
uv run python scripts/smoke_policy.py
uv run python scripts/evaluate_baseline.py
```

La referencia carga los diez pares CSV/PDF mediante la API y espera al worker. Compara campos contra el manifiesto independiente y resultados DSCR/regla contra aritmética Fraction, incluido redondeo half-up mediante enteros. Verifica el contenido de las citas contra el catálogo y escribe `evaluations/reports/deterministic-baseline.json`.

El informe registra concordancia observada, tiempos por caso desde creación hasta completar políticas, entorno y uso de modelos. P95 utiliza rango más próximo; con diez observaciones es el mayor tiempo. El coste de infraestructura no se mide. Es una referencia pequeña de ingeniería controlada, no una estimación de exactitud real, garantía de servicio ni evidencia de ahorro frente a revisión manual. CI la repite con Docker Compose.

Las pruebas unitarias y PostgreSQL cubren límites exactos, entradas inválidas/faltantes, independencia de contexto, publicación, fechas, abstención/aislamiento de búsqueda, deduplicación concurrente, fuentes obsoletas, salidas inmutables y citas cruzadas. [ADR-003](adr/003-policy-engine.md) registra las decisiones y sus consecuencias.

# Flujo de IA con evidencia verificable

[English](../ai-workflow.md) | **Español**

La fase 4 incorpora un adaptador de OpenAI y un flujo acotado para preparar borradores de análisis crediticio sintético. Admite los formatos CSV y PDF de texto estructurados existentes. Los estados narrativos, OCR, planificación autónoma y decisiones crediticias de producción quedan fuera de este hito.

## Contrato de procesamiento

1. Un analista carga estados sintéticos y completa `/v1/cases/{id}/extract`.
2. `POST /v1/cases/{id}/ai-evaluate` fija los documentos actuales de esa extracción, hash de la política, fórmula, proveedor, modelo, flujo y versión del prompt.
3. El rol de extracción propone observaciones con identificadores de fuente y valores originales exactos. Un validador determinista exige todas las observaciones admitidas no vacías, incluidos duplicados contradictorios, y todas las claves faltantes. Las fuentes desconocidas, importes alterados, omisiones y campos no admitidos fallan la validación.
4. Herramientas deterministas reconstruyen hechos con evidencia, calculan DSCR y evalúan la política fijada. El modelo no puede modificar esas herramientas ni sus resultados.
5. El rol de redacción selecciona y ordena tarjetas de afirmaciones verificadas. El renderizador genera el texto material en inglés y español y sus referencias a evidencia, hechos, cálculos y fragmentos de política. Identificadores inventados, hallazgos duplicados u omitidos y secciones inválidas fallan la validación.
6. Una ejecución correcta produce una evaluación inmutable `DRAFT_READY` con `ai_draft`. Conserva las marcas **SIMULACIÓN**, **DRAFT_ONLY** y el requisito de revisión humana independiente.

La extracción y organización asistidas por modelos son deliberadamente restringidas. El parser ya reconoce las etiquetas financieras admitidas; el modelo no aporta comprensión narrativa. El código genera las afirmaciones materiales, por lo que su respaldo no demuestra la fiabilidad de redacción libre de un modelo general.

La versión `grounded-agents-v2` asigna referencias locales estables (`S000001`, etc.) según el orden de documentos y filas fijados. El esquema de respuesta enumera las referencias permitidas; después se aplica igualmente la validación completa de fuentes y valores. El catálogo se reconstruye desde los documentos inmutables, sin copiar UUID de base de datos a través del modelo. Se admiten hasta 500 unidades de fuente por solicitud de IA, además de los límites de bytes/tokens. Los límites de ingesta determinista no cambian.

## Flujos y API

```json
{
  "source_evaluation_id": "<uuid-de-extraccion-correcta>",
  "provider": "mock",
  "workflow": "multi_agent"
}
```

Se utilizan la identidad bearer existente y `Idempotency-Key`. Solo un analista asignado al caso puede iniciar el análisis. La extracción debe corresponder a los documentos actuales. Las entradas equivalentes reutilizan la evaluación existente; cambiar la clave de idempotencia no repite silenciosamente una llamada pagada.

| Flujo | Etapas del modelo | Acceso a herramientas | Máximo total de tokens de salida |
|---|---|---|---|
| `generalist` | Extracción y selección de identificadores en una respuesta | Las herramientas deterministas se ejecutan tras validar la propuesta | 4.096 |
| `multi_agent` | Rol de extracción y luego rol de redacción | El redactor recibe tarjetas verificadas después de las herramientas | 2 × 2.048 |

El flujo especializado utiliza dos roles acotados con el mismo modelo, sin agentes autónomos independientes. Igualar el máximo de salida no iguala prompts, contexto intermedio, tokens de entrada ni consumo real. Ambos utilizan las mismas fuentes, política, validadores y motor financiero.

`GET /v1/cases/{id}/evaluations/{evaluation_id}` devuelve el borrador, cálculos, política y metadatos de llamadas. Las respuestas originales del proveedor permanecen en la base local; este endpoint no las devuelve ni se versionan en Git.

## Configuración de OpenAI y controles de costo

El consumo real está desactivado por defecto. Guardar la clave privada en `.env` bajo `CDS_OPENAI_API_KEY` y configurar:

```dotenv
CDS_LLM_LIVE_ENABLED=true
CDS_LLM_MODEL=gpt-5.6-terra
CDS_LLM_BUDGET_USD=2.00
CDS_LLM_MAX_CALLS=64
```

Reiniciar API y worker después de cambiar la configuración. En Compose, recrearlos con `docker compose up --build --wait api worker`. Agregar una clave por sí solo no activa el consumo. Para desactivar nuevas llamadas pagadas, establecer `CDS_LLM_LIVE_ENABLED=false` y reiniciar los servicios.

El adaptador utiliza [Responses API y salidas estructuradas estrictas](https://developers.openai.com/api/docs/guides/structured-outputs), con `store=false`, sin herramientas alojadas, reintentos automáticos ni redirecciones, y con endpoint fijo de OpenAI. Modelo y precios estándar verificados el 2026-11-10: [GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra), US$2 por millón de tokens de entrada y US$12 por millón de salida. No se presuponen descuentos de caché. Revisar precios antes de ampliar la campaña.

El registro `phase4-openai` acumula consumo en una base PostgreSQL. Antes de enviar HTTP, una transacción bloquea la fila de presupuesto y reserva un máximo conservador de entrada y salida. El límite de aplicación y base es US$2, incluidas llamadas pendientes e inciertas; la configuración permite reducirlo. También se aplican 64 llamadas por defecto y 60.000 bytes por solicitud. El uso conocido se registra con los precios estándar configurados. Uso desconocido, fallos de transporte y reservas no resueltas conservan la reserva completa. Las solicitudes idénticas completadas reutilizan la respuesta; las fallidas o inciertas no generan otro consumo automáticamente.

Es una asignación local de la aplicación, no un límite de facturación de toda la cuenta OpenAI. Otras bases y aplicaciones tienen consumo independiente. Conservar el registro al reiniciar; no recrear la base para reanudar la misma campaña. Las reservas protegen frente a workers concurrentes bajo los supuestos de precios documentados. La conciliación de facturación continúa siendo una responsabilidad operativa.

## Persistencia y fallos

Las llamadas externas se ejecutan fuera de las transacciones de negocio. Un heartbeat separado mantiene el arrendamiento del worker. Bloqueos y tokens de arrendamiento controlan la persistencia; un worker vencido no publica borradores. Las llamadas conservan hash de solicitud, versión de prompt, uso y costo. La recuperación reutiliza las respuestas completadas.

Las herramientas deterministas se confirman antes de redactar, por lo que un fallo puede conservar hechos y verificaciones válidas. La evaluación queda `FAILED_TERMINAL`, sin borrador final. Rechazo del modelo, respuesta incompleta o mal formada, presupuesto agotado y falta de respaldo también terminan el trabajo. Las llamadas fallidas o inciertas requieren investigación operativa explícita. Cargar documentos limpia el puntero de evaluación actual; terminar un trabajo histórico no lo restablece.

## Evaluación reproducible

Después de disponer de la demostración de ingesta:

```sh
uv run python scripts/evaluate_ai.py --provider mock --output storage/ai-mock.json
uv run python scripts/evaluate_ai.py --provider openai --repetitions 2 --output storage/ai-openai.json
```

El modo mock cubre diez variantes y ambos flujos, sin cargos de modelo. OpenAI utiliza casos CSV completos, contradictorios y con instrucciones maliciosas; dos repeticiones producen doce ejecuciones y hasta dieciocho llamadas. La campaña se detiene ante un fallo real. Los informes se guardan tras cada ejecución e incluyen concordancia con una referencia financiera independiente, integridad y respaldo del borrador, latencia, tokens, versiones de prompt/modelo y costo cobrado o reservado. Se excluyen registros originales y credenciales.

Los informes distinguen las comprobaciones simuladas de orquestación de las mediciones reales. La muestra controlada pequeña no demuestra precisión real, superioridad estadística, menor esfuerzo manual ni niveles de servicio de producción. La interfaz, revisión humana y exportación de informes corresponden a la fase 5.

## Verificación registrada

La [comparación mock](../../evaluations/reports/ai-mock-comparison.json) completó veinte ejecuciones con concordancia financiera independiente y borradores completos con referencias válidas. Son resultados del proveedor determinista de prueba, no mediciones de calidad de OpenAI.

El [intento inicial de OpenAI](../../evaluations/reports/ai-openai-initial-attempt.json) devolvió `OPENAI_HTTP_429`, sin respuesta completada ni uso disponible. Su reserva incierta de US$0,064468 se conserva en el registro acumulado.

La [campaña real de versión 1](../../evaluations/reports/ai-openai-v1-comparison.json) realizó diez de los doce intentos previstos antes de detenerse por un fallo de cobertura. El flujo especializado produjo cinco borradores válidos de cinco intentos; el generalista, cuatro de cinco. La inspección de la propuesta conservada identificó un UUID alterado en la referencia de `total_debt`, con el importe correcto. Fue un error al copiar la referencia, no evidencia de que se descartara el importe contradictorio. El validador lo rechazó antes de persistir herramientas o publicar el borrador. La respuesta fallida permanece sin cambios en el informe histórico. No se intentaron los dos flujos restantes de esa campaña.

Las quince llamadas medidas de versión 1 consumieron US$0,077378. Con la reserva inicial incierta, su acumulado utilizado o reservado fue US$0,141846 de US$2. Las mediciones posteriores de versión 2 se registran por separado en la [comparación actual](../../evaluations/reports/ai-openai-comparison.json), sin sobrescribir el fallo histórico ni reiniciar el presupuesto. La reserva no es un cargo confirmado del proveedor. Ni la muestra histórica ni una muestra posterior correcta demuestran superioridad de un flujo.

La versión 2 completó las doce ejecuciones reales previstas sobre casos completos, contradictorios y con instrucciones maliciosas, con dos repeticiones por flujo. Las doce coincidieron con la referencia financiera independiente y generaron borradores completos con evidencia. La suite contiene 148 pruebas correctas con PostgreSQL; la comparación mock actual completó 20/20 flujos.

| Flujo de versión 2 | Borradores válidos con evidencia | Llamadas | Costo según tokens | Mediana del tiempo por flujo |
|---|---|---|---|---|
| Generalista | 6/6 | 6 | US$0,025832 | 3,8066 s |
| Roles especializados | 6/6 | 12 | US$0,041942 | 4,7998 s |

Son mediciones locales en serie, sin garantías de servicio ni potencia estadística para comparar. Ambos flujos pasaron la muestra; los roles especializados requirieron más llamadas y mayor costo en esta ejecución. La versión 2 utilizó US$0,067774. Entre ambas campañas, el uso medido es US$0,145152 más la reserva inicial de US$0,064468: US$0,209620 utilizados/reservados; quedan US$1,790380 de la asignación de US$2. El consumo pagado está desactivado tras la verificación.

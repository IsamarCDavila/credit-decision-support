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

El consumo real está desactivado por defecto. Configuración privada en `.env`:

```dotenv
CDS_OPENAI_API_KEY=<clave-api-privada>
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

El [registro de la campaña OpenAI](../../evaluations/reports/ai-openai-comparison.json) está **bloqueado**: la primera solicitud generalista devolvió `OPENAI_HTTP_429`. No hubo respuesta completada ni uso de tokens disponible; las ejecuciones restantes no se intentaron. La aplicación conserva US$0,064468 como reserva por llamada incierta, no como cargo confirmado del proveedor. No se afirma haber completado una comparación real de modelos. Revisar facturación, cuota y límites de la API del proyecto antes de reanudar explícitamente la campaña; conservar el registro existente.

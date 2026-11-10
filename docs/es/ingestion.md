# Ingesta de documentos sintéticos

[English](../ingestion.md) | **Español**

## Formato de estados admitido

La fase 2 admite CSV UTF-8 y PDF con texto bajo `synthetic-statement-v1`. Extrae seis campos: `annual_revenue`, `ebitda`, `total_debt`, `debt_service`, `available_cash_flow` y `obligations`. Es un extractor determinista de esquema conocido, no un sistema de comprensión de cualquier PDF.

CSV requiere esta cabecera en el orden indicado:

```csv
key,value,currency,period_start,period_end,basis,synthetic
annual_revenue,2500000.00,USD,2025-01-01,2025-12-31,individual,true
```

Los PDF utilizan etiquetas de texto como estas:

```text
synthetic: true
currency: USD
period_start: 2025-01-01
period_end: 2025-12-31
basis: individual
annual_revenue: 2500000.00
```

Todas las filas y documentos del expediente deben compartir un año calendario completo, terminado a más tardar en la fecha de corte. Solo se admiten USD y estados individuales. Los importes utilizan signo negativo opcional, hasta 18 dígitos enteros, punto decimal y hasta dos decimales. Se excluyen separadores de miles, notación científica y unidades inferidas. Las etiquetas desconocidas permanecen como contenido de la fuente, sin producir hechos financieros.

Un campo ausente o vacío es `missing`; un importe mal formado es `invalid`; los valores válidos diferentes para el mismo campo son `ambiguous`. Los valores coincidentes entre varias fuentes permanecen como `extracted`, con toda su evidencia. Se conservan ceros y negativos; las reglas financieras se evalúan en la fase 3.

## Flujo de la API

| Operación | Propósito |
|---|---|
| `POST /v1/cases/{id}/documents` | Cargar un archivo con nombre/MIME coincidentes, `synthetic=true` e `Idempotency-Key` |
| `GET /v1/cases/{id}/documents/{document_id}` | Consultar metadatos, páginas normalizadas o filas CSV |
| `GET /v1/cases/{id}/documents/{document_id}/content` | Descargar los bytes originales como adjunto |
| `POST /v1/cases/{id}/extract` | Encolar un snapshot con `Idempotency-Key`; devuelve identificadores de evaluación/trabajo |
| `GET /v1/cases/{id}/evaluations/{evaluation_id}` | Consultar estado, hechos, evidencia y vigencia del snapshot |

Solo los analyst miembros del expediente pueden cargar o solicitar extracción. Consultar fuentes y resultados requiere membresía. Los nombres de archivo no determinan rutas de almacenamiento ni nombres de descarga. Los bytes y metadatos conservados son inmutables. Las cargas idénticas dentro del expediente reutilizan el documento y no invalidan la extracción actual.

La carga devuelve 202 después de validar el formato y persistir transaccionalmente. El trabajo separado combina fuentes y escribe hechos/evidencia. Las solicitudes repetidas reutilizan la respuesta durante 24 horas; la extracción de la misma entrada fijada se deduplica incluso con otra clave. Reutilizar una clave de extracción después de nuevas cargas devuelve la evaluación original; una nueva clave solicita el nuevo snapshot.

Una extracción correcta deja el procesamiento en `VALIDATING` y el trabajo en `SUCCEEDED`. No produce resultados de políticas, recomendaciones ni decisiones crediticias. Los documentos nuevos limpian el puntero de evaluación actual; los snapshots anteriores y su evidencia siguen disponibles. Los fallos terminales de integridad no dejan hechos parciales.

## Límites y controles

- 10 MiB por documento, 20 documentos por expediente y 100 páginas por PDF.
- Límite HTTP total: 10 MiB más 64 KiB de sobrecarga multipart, incluidas solicitudes transmitidas por partes.
- Hasta 2.000 filas CSV de datos; se requieren cabeceras exactas y celdas de una sola línea.
- Hasta 2.000.000 de caracteres extraídos del PDF y 20.000.000 de bytes expandidos de contenido por página.
- Proceso separado, timeout de 15 segundos y límites Linux de memoria/CPU descritos en [ADR-002](adr/002-ingestion.md).
- Los archivos cifrados, escaneados/vacíos, dañados, no admitidos o fuera de alcance se rechazan con 422. Exceder tamaño o cantidad de documentos devuelve 413.

La declaración de datos sintéticos es una afirmación del remitente. No se implementó un detector automático de datos personales ni un clasificador de autenticidad. El parser no realiza OCR ni interpreta instrucciones narrativas.

## Ejemplos reproducibles y demo

Se incluyen diez casos con semilla como pares CSV/PDF en `data/synthetic/generated/`. Su manifiesto registra resultados esperados independientes y SHA-256. Los casos abarcan datos completos, campos ausentes/vacíos, valores contradictorios e inválidos, ceros/negativos, cifras grandes y texto narrativo no confiable.

```sh
uv sync --frozen --extra dev
uv run python scripts/generate_synthetic_cases.py
docker compose up --build --wait api worker
uv run python scripts/smoke_ingestion.py
```

La configuración privada se genera con `scripts/configure_demo.py` antes del primer arranque; se conserva la existente durante actualizaciones. La comprobación carga el primer par CSV/PDF, solicita extracción, espera al worker e imprime hechos y cantidad de evidencias sin credenciales.

## Verificación

La suite PostgreSQL comprueba cada variante en ambos formatos frente a resultados esperados independientes, resuelve cada cita contra su fuente y verifica las descargas originales. Otros escenarios cubren alcance no admitido, archivos ilegibles/cifrados/excesivos, páginas PDF vacías, timeout, deduplicación concurrente, límites de documentos, almacenamiento alterado y evaluaciones históricas. La reproducibilidad se compara con el manifiesto versionado. Las páginas PDF también se renderizan para revisión visual.

Estas comprobaciones demuestran comportamiento sobre el formato sintético controlado, no exactitud ni seguridad sobre cualquier documento real. CI también construye y arranca los contenedores y comprueba disponibilidad de la API. Los cálculos financieros y la recuperación de políticas están disponibles en la [fase 3](policy-engine.md). Los modelos reales y la revisión humana corresponden a hitos posteriores.

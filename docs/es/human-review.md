# Espacio de revisión humana e informes

[English](../human-review.md) | **Español**

La fase 5 incorpora una interfaz web, asignación de revisores/auditores, decisiones humanas inmutables e informes JSON/PDF en inglés y español. Todas las vistas e informes son una **SIMULACIÓN** de análisis crediticio sintético. Una decisión humana no autoriza créditos reales.

## Inicio y acceso

Se requieren Python 3.12, uv y Docker Compose v2, según la [operación base](foundation.md). Las instalaciones existentes deben aplicar la última migración; el servicio de migración de Compose aplica `0005_human_review` antes de iniciar la API.

```sh
uv sync --frozen --extra dev
# Solo para una instalación nueva sin .env:
uv run python scripts/configure_demo.py
docker compose up --build --wait api worker
```

Abrir `http://127.0.0.1:8000/`. El idioma inicial es inglés y el selector permite cambiar a español. Cada persona utiliza su token de acceso asignado, no una clave API de OpenAI. Para obtener una credencial local de demostración de forma privada:

```sh
uv run python scripts/demo_access.py --role analyst --show-token
uv run python scripts/demo_access.py --role reviewer --show-token
uv run python scripts/demo_access.py --role auditor --show-token
```

Conservar esas credenciales en privado. El comando oculta el token salvo que se indique `--show-token`. La interfaz mantiene el token en memoria, limpia el campo después del acceso y elimina las credenciales al cerrar sesión o recargar la página. Solo la preferencia de idioma se guarda en el almacenamiento local del navegador. Los tokens demo son identidades configuradas en el servidor, no sesiones de cuentas de producción ni una integración con un proveedor de identidad.

## Flujo del expediente

1. Un analista asignado crea un expediente sintético SME/USD y carga estados anuales CSV/PDF de texto admitidos. **Preparar borrador de demostración** ejecuta extracción y análisis con el proveedor sin conexión. No realiza llamadas pagadas a OpenAI.
2. El analista asigna un revisor independiente o auditor configurado. El directorio muestra identificadores y roles, nunca credenciales. Solo se asignan roles de revisor/auditor en expedientes propios; no se elevan roles ni se concede acceso implícito al administrador.
3. Los usuarios asignados consultan hallazgos, datos financieros, extractos/localizadores exactos, documentos conservados, política, historial y auditoría. Se traducen los rótulos; los identificadores de API y el borrador almacenado no cambian.
4. El revisor independiente elige `APPROVED`, `REJECTED` o `NEEDS_MORE_INFO` y registra un motivo no vacío de hasta 4.000 caracteres. La decisión corresponde solo a la simulación. El preparador no puede revisar su evaluación, aunque utilice otra credencial que corresponda al mismo identificador de actor.
5. La revisión final es inmutable. `NEEDS_MORE_INFO` no reabre la evaluación: nuevos documentos requieren otra evaluación. Cargar documentos limpia el puntero de evaluación actual. Las revisiones históricas siguen visibles, sin reenviarse ni reemplazarse.

El borrador conserva `DRAFT_ONLY` y `requires_human_review`; `review.state` registra por separado si ocurrió la revisión. Un resultado de política nunca se convierte automáticamente en decisión humana.

La interfaz muestra hasta 50 evaluaciones recientes, priorizando la actual; `history_truncated` indica si existen más. Expedientes y eventos tienen lectura paginada. La inspección utiliza texto normalizado de PDF con página/offset o fila/columna CSV; el original sigue disponible para descarga. El resaltado gráfico de regiones PDF queda fuera de este hito.

## Consistencia de la revisión

La solicitud identifica la evaluación y `expected_review_state: PENDING`. El servidor verifica identidad, pertenencia, independencia, borrador listo, puntero actual y ausencia de revisión previa. Un bloqueo de fila del expediente serializa revisión, carga y cambios de puntero. Las solicitudes concurrentes tienen un solo ganador; una evaluación desactualizada o ya revisada devuelve 409. Revisión y evento se confirman en la misma transacción.

`Idempotency-Key` es obligatorio para asignar acceso y decidir, con ámbito actor/ruta y vigencia de 24 horas. Repetir el mismo contenido validado devuelve la respuesta almacenada sin duplicar decisiones/eventos. Cambiar el contenido con la misma clave devuelve 409. Ocultar controles en la interfaz no reemplaza la autorización del servidor.

```json
{
  "expected_review_state": "PENDING",
  "decision": "NEEDS_MORE_INFO",
  "reason": "Se requiere evidencia sintética adicional para la evaluación."
}
```

## Operaciones de API

| Operación | Propósito / acceso |
|---|---|
| `GET /v1/me` | Actor y rol actuales, sin devolver credenciales |
| `GET /v1/assignment-directory` | Revisores/auditores configurados; solo analistas |
| `GET /v1/cases?limit=30&offset=0` | Expedientes asignados al actor y rol actuales |
| `GET /v1/cases/{id}/workspace` | Expediente, inventario documental, evaluaciones recientes y miembros |
| `POST /v1/cases/{id}/members` | Asignar revisor/auditor configurado; solo analista del caso |
| `GET /v1/cases/{id}/evaluations/{evaluation_id}/review` | Estado de revisión y permiso para revisar |
| `POST /v1/cases/{id}/evaluations/{evaluation_id}/review` | Registrar decisión independiente y motivo |
| `GET /v1/cases/{id}/evaluations/{evaluation_id}/report.json?locale=en` | JSON verificado de un borrador listo; usuarios asignados |
| `GET /v1/cases/{id}/evaluations/{evaluation_id}/report.pdf?locale=es` | PDF verificado con JSON adjunto; usuarios asignados |

Los esquemas están en [OpenAPI](../../contracts/openapi.json). Un caso invisible devuelve 404; un estado desactualizado o no disponible para revisar/exportar, 409; campos o motivos inválidos, 422.

## Reconstrucción del informe

Se requiere un borrador listo; es posible exportarlo antes o después de revisar. El informe incluye indicador actual/histórico, borrador inmutable, hechos/evidencia, cálculos, política/citas, metadatos documentales, revisión humana y cadena de auditoría del expediente al exportar. El motivo conserva el idioma del revisor; la aplicación no traduce ni reescribe su evaluación.

Antes de exportar se verifican SHA-256 de documentos originales, correspondencia entre bytes reparsados y salida conservada, localizadores exactos, hashes de borrador/política, recálculo de DSCR/regla y cadena completa de auditoría. Un fallo bloquea la exportación con 409. Reconstruir reutiliza resultados conservados y no llama a un LLM. El límite es 2 MB de contenido canónico y 2.000 eventos.

El JSON incluye `integrity.payload_sha256`: SHA-256 del cuerpo canónico UTF-8 **sin** su campo `integrity`. La serialización usa claves ordenadas, separadores `(',', ':')` y Unicode sin escapar. Los tiempos se normalizan a UTC.

Cada PDF adjunta el `report.json` exacto que utilizó para generarse. Su hash visible puede verificarse frente a esa instantánea. Las descargas JSON/PDF independientes pueden tener distinta hora y hash. El PDF no tiene firma digital; los hashes y la cadena de base no constituyen una referencia de confianza independiente frente a un propietario capaz de reescribir datos y hashes. Descargar es una operación de lectura y no añade eventos.

La interfaz representa contenido no confiable mediante nodos de texto y el PDF escapa el marcado. Scripts/estilos tienen tipos MIME explícitos, política de seguridad del mismo origen, ningún recurso externo, respuestas no almacenables y política de no enviar referencias. La demostración permanece local y sintética; identidad de producción, retención operativa, límites de carga y mayor verificación de resiliencia corresponden a fase 6 o decisiones posteriores.

## Verificación

```sh
uv run python scripts/smoke_review.py --output-dir storage/review-demo
uv run pytest -q
```

La prueba crea fuentes sintéticas CSV/PDF, prepara un borrador sin conexión, asigna revisor/auditor, registra `NEEDS_MORE_INFO`, verifica repetición idempotente y rechazo de duplicados y exporta ambos formatos/idiomas. Nunca imprime credenciales privadas. Los artefactos quedan en `storage/`, excluido de Git.

Las pruebas con PostgreSQL cubren permisos, asignación, motivos, estados finales, concurrencia, casos cruzados/desactualizados, corrupción de fuentes/auditoría, hashes y texto/instantáneas adjuntas al PDF. La verificación de navegador cubre asignación del analista, revisión independiente en español, fuentes, descarga PDF y presentación de escritorio/móvil. Los informes representativos se rasterizan y revisan visualmente para detectar cortes, errores de paginación o glifos. GitHub Actions repite backend y demostración Compose; estas pruebas sin conexión no modifican la asignación de OpenAI.

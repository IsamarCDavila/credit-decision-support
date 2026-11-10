# Operación de la infraestructura base

[English](../foundation.md) | **Español**

## Alcance implementado

La fase 1 proporciona un servicio FastAPI, persistencia PostgreSQL mediante SQLAlchemy Core, migraciones Alembic, identidades demo resueltas en el servidor, permisos por expediente, creación idempotente, cadena de auditoría y worker persistente. Las migraciones SQL son el modelo autoritativo de persistencia. La base utiliza PostgreSQL 16; la fase 3 utiliza recuperación full-text como referencia; embeddings y pgvector requieren evaluación posterior según [ADR-003](adr/003-policy-engine.md).

| Operación | Comportamiento |
|---|---|
| `GET /healthz` | Disponibilidad del proceso, sin autenticación |
| `GET /readyz` | Conexión a base de datos y revisión de migración |
| `POST /v1/cases` | Creación exclusiva para analyst con `Idempotency-Key`; caduca a las 24 horas |
| `GET /v1/cases/{id}` | Lectura cuando actor y rol coinciden con la membresía del expediente |
| `GET /v1/cases/{id}/audit-events` | Acceso autorizado a auditoría con paginación por secuencia |

La documentación interactiva de la API se encuentra en `/docs`. `contracts/openapi.json` se genera desde el servicio implementado. `contracts/openapi-design.json` conserva la API propuesta para el MVP completo; la carga de documentos, evaluación financiera, revisión y exportación de informes todavía no están disponibles.

## Arranque

Requisitos: Python 3.12, uv, Docker Engine o Docker Desktop y Docker Compose v2. Desde la raíz del repositorio:

```sh
uv sync --frozen --extra dev
uv run python scripts/configure_demo.py
docker compose up --build --wait api worker
uv run python scripts/smoke_api.py
```

La generación de configuración crea contraseñas de base de datos y tokens aleatorios locales en `.env`, rechaza sobrescribir un archivo existente y no imprime credenciales. El comando de comprobación crea y consulta un expediente sintético sin imprimir su token. Al repetirse devuelve el mismo expediente dentro de la ventana de idempotencia.

La API se limita a `127.0.0.1:8000`. PostgreSQL no publica un puerto en el equipo anfitrión. La comprobación de salud de la base precede las migraciones; API y worker solo arrancan después de que estas terminen correctamente. `docker compose down` detiene los servicios y conserva el volumen de la base. Las credenciales utilizadas para inicializar ese volumen deben permanecer estables entre reinicios.

## Identidad y autorización

La configuración asocia tokens con identidades analyst, reviewer, auditor y admin. La creación del expediente incorpora al analyst como miembro. Las demás identidades no tienen acceso salvo que su membresía se configure explícitamente en la base. Este hito no incluye un endpoint público para gestionar membresías. La identidad admin no evita la autorización por expediente. La autenticación demo local no es un servicio de identidad de producción; la autenticación de despliegue y la protección de comunicaciones permanecen como requisitos separados.

API y worker utilizan `cds_runtime`, que no es propietario de las tablas y no puede modificar el esquema, modificar políticas publicadas ni actualizar/eliminar/truncar los registros protegidos de auditoría, documentos y revisiones. Las migraciones utilizan al propietario del esquema. Los triggers también protegen políticas publicadas y evaluaciones finalizadas, exigen referencias al mismo expediente/evaluación, requieren evidencia para hechos extraídos, impiden políticas publicadas solapadas y exigen un revisor miembro independiente sobre una evaluación actual y lista.

## Worker

Los trabajos se almacenan en PostgreSQL. Los workers los adquieren mediante `FOR UPDATE SKIP LOCKED`, utilizan tokens únicos de lease, admiten heartbeat y permiten un máximo de tres adquisiciones por trabajo. Un worker cuyo lease expiró no puede confirmar resultados después de que otro adquiera el trabajo. El resultado y su evento de finalización se confirman en una misma transacción.

El único paso implementado es `foundation_check`, que comprueba la disponibilidad de un snapshot de evaluación. No extrae documentos ni produce recomendaciones crediticias. No existe una API pública que encole este paso interno; las pruebas de integración insertan trabajos directamente. Los pasos no admitidos terminan explícitamente. Los trabajos interrumpidos se recuperan tras vencer el lease; los que agotan intentos quedan en estado terminal. El procesamiento extendido, clasificación de reintentos y planificación de múltiples pasos corresponden a hitos posteriores.

## Validación

Se utiliza una base PostgreSQL exclusiva de pruebas cuyo nombre termina en `_test`; la suite vacía las tablas del proyecto en esa base. Se configura `CDS_TEST_ADMIN_URL` con su URL SQLAlchemy PostgreSQL/psycopg y se ejecuta:

```sh
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run python scripts/export_openapi.py
```

Los escenarios de integración de infraestructura base cubren autenticación y autorización, idempotencia concurrente, hashes de auditoría, permisos de ejecución, solapamiento de políticas, snapshots inmutables, restricciones de revisión, evidencia obligatoria, localizadores inválidos, concurrencia/recuperación de leases y migración de avance/retroceso. El retroceso elimina tablas y funciones del proyecto y conserva tablas ajenas. Descarta datos del proyecto y se destina a bases desechables de desarrollo.

GitHub Actions también comprueba diferencias del OpenAPI generado, construye y arranca los servicios Compose, verifica disponibilidad y detecta secretos. Aprobar las pruebas locales de Python no demuestra que la construcción del contenedor funcione; CI informa esa verificación de forma independiente. La fase 1 no contiene mediciones de rendimiento financiero ni calidad de modelos.

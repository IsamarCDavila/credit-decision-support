# Seguridad, resiliencia y carga medida

[English](../hardening.md) | **Español**

La fase 6 incorpora límites de admisión de demos, telemetría operativa sin datos sensibles, límites de espera de base de datos, recuperación del worker y un protocolo reproducible de carga sin conexión. No demuestra preparación para producción, garantía de servicio ni aptitud para decisiones crediticias reales.

## Controles operativos

La API genera un `X-Request-ID` nuevo en cada solicitud; no confía en el identificador enviado por el cliente. Los registros JSON incluyen únicamente ese identificador, método, plantilla de ruta, estado y milisegundos transcurridos. Omiten URL completa, parámetros, cuerpos, credenciales, direcciones de red y datos financieros. Las rutas y métodos desconocidos usan etiquetas acotadas. El servidor empaquetado desactiva registros de acceso y reescritura de cabeceras de proxy; los comandos Uvicorn personalizados también deben usar `--no-access-log --no-proxy-headers`. La recopilación, retención y derivación de alertas dependen del despliegue.

`GET /v1/operations` exige una identidad administradora configurada. Devuelve contadores HTTP del proceso actual, tiempo activo, duraciones agregadas, cantidades persistentes de trabajos por estado y antigüedad del trabajo ejecutable más antiguo. No expone expedientes, credenciales ni excepciones originales. Los contadores de API se reinician con el proceso y no se agregan entre réplicas. La disponibilidad verifica base de datos/migración, no el progreso del worker. Una cola cada vez más antigua requiere investigación operativa.

La creación de demos admite `CDS_DEMO_REQUESTS_PER_MINUTE=8` solicitudes por dirección de conexión en una ventana fija de 60 segundos, incluidos intentos fallidos. El rechazo devuelve 429 y `Retry-After`. El limitador no lee cabeceras reenviadas. Conserva como máximo 1.024 ventanas; si se llena, rechaza direcciones nuevas hasta que venza alguna ventana. Un bloqueo serializa la admisión dentro de cada proceso API. Los límites existentes de sesiones activas y conservadas también se serializan en la base entre procesos. El límite de frecuencia es por proceso y compartido por visitantes detrás del mismo proxy; no es una defensa distribuida contra abuso. Un alojamiento más amplio requiere un diseño de proxy confiable y un limitador externo.

Las conexiones usan cinco segundos para conexión/espera del pool, 15 segundos por sentencia, cinco segundos por bloqueo y 30 segundos para transacciones inactivas. `CDS_DB_STATEMENT_TIMEOUT_MS` y `CDS_DB_LOCK_TIMEOUT_MS` configuran tiempos SQL en ejecuciones nativas; Compose usa los valores predeterminados. Los errores devuelven un 503 sin detalles sensibles. El PostgreSQL local de Windows no interrumpió una consulta demorada deliberadamente; la interrupción se comprueba en Linux CI y no se afirma a partir de la ejecución local. Esa prueba debe aprobarse antes de aceptar la fase.

El worker captura errores de base de datos, registra un diagnóstico fijo sin SQL ni texto de la excepción, espera el intervalo configurado y continúa. Los trabajos confirmados persisten; las concesiones inconclusas se recuperan con otro token y un máximo de tres intentos. La prueba ejecuta otro proceso worker después de vencer la concesión y verifica un único efecto confirmado. Los errores de programación desconocidos siguen visibles y requieren investigación. Los reintentos de red/modelo conservan los límites del registro de llamadas; no se añaden reintentos pagados automáticos. El presupuesto acumulado de US$2 y sus reservas se conservan.

## Reproducir las mediciones

Se requieren API, worker persistente, PostgreSQL 16 y política sintética publicada. Se conserva la configuración privada existente de `.env`. Desde la raíz del repositorio:

```sh
uv run pytest -q
uv run python scripts/evaluate_hardening.py --output storage/hardening.json
```

El script ejecuta las diez variantes congeladas con concurrencias 1, 2, 4 y 8: un cliente por expediente en curso, un proceso API y un worker. Cada caso crea un espacio SME/USD, carga PDF y CSV con hashes verificados, extrae evidencia, prepara un borrador especializado simulado, contrasta valores financieros independientes, asigna un revisor, registra una decisión simulada con motivo y reconstruye un informe JSON con hash verificado. No oculta fallos con reintentos del cliente. Registra cada inicio, categorías acotadas de error, tamaños de muestra, p95 por rango más cercano, rendimiento e intervalos Wilson del 95%. Los fallos inducidos pertenecen a las pruebas de integración separadas, fuera del denominador de carga satisfactoria.

El [informe versionado](../../evaluations/reports/hardening-load.json) contiene entorno, hash del corpus, escenarios y agregados. CI repite concurrencias 1 y 4 en Compose y conserva `hardening-measurements` como artefacto. Los tiempos de CI describen ese entorno y no sustituyen la medición local.

La comprobación de admisión empaquetada es `uv run python scripts/smoke_operations.py`. Se ejecuta al final: alcanza deliberadamente el límite de frecuencia sin crear expedientes. Antes de iniciar otra demo desde esa dirección se debe esperar el plazo de `Retry-After`.

## Interpretación de aceptación

| Meta de diseño | Resultado y alcance |
|---|---|
| Extracción ≥95% | 240/240 pares estado/valor coinciden en el corpus controlado; las 16 abstenciones explícitas siguen incluidas en el denominador |
| Cobertura de evidencia material ≥99% | 320/320 tarjetas financieras/de política verificadas contra valores/reglas independientes y fuentes reconstruibles; corresponde a tarjetas deterministas simuladas, no a prosa libre de un LLM |
| Cero afirmaciones materiales sin respaldo | Cero discrepancias observadas en esas 320 tarjetas; pruebas adversariales separadas rechazan observaciones/citas inventadas |
| Intervención humana medida | **No cumplida:** falta un estudio independiente cronometrado; se conserva la revisión obligatoria |
| Borrador antes de 15 minutos | Cumplida en este protocolo: p95 de 16,18 s en el nivel mayor (8); p95 agregado de 14,02 s |
| Ejecución satisfactoria ≥99% | 40/40 observados; intervalo Wilson del 95%: 91,24–100%, insuficiente para demostrar fiabilidad poblacional del 99% |
| Reconstrucción de instantáneas de prueba conservadas | 40/40 informes de borrador verificados; no se probó una cohorte eliminada ni una población histórica de producción |
| Costo por caso con infraestructura | **No cumplida por completo:** costo de modelo simulado cero; falta asignación de infraestructura |

El rendimiento fue aproximadamente 0,32; 0,45; 0,44 y 0,45 casos satisfactorios/s con concurrencias 1, 2, 4 y 8. Con un worker, aumentar la concurrencia incrementó principalmente la espera en cola. Ocho es el máximo probado, no un límite de saturación descubierto ni una recomendación de alojamiento. No se representan pruebas prolongadas, carga de archivos grandes, múltiples réplicas, plantillas nuevas, restauración de copias ni una prueba de penetración independiente. La versión 0.6.0 sigue siendo una demostración sintética; estas metas abiertas impiden afirmar que se cumplan todos los criterios de versión 1.0.

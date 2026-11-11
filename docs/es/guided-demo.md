# Demostración guiada

[English](../guided-demo.md) | **Español**

La demostración guiada ofrece un expediente sintético SME/USD preparado, sin cuenta, comandos de terminal ni ingreso manual de tokens. Todos los resultados son una **SIMULACIÓN**. El proveedor siempre es `mock`; las credenciales guiadas no pueden solicitar procesamiento pagado de OpenAI, aunque esté habilitado para otros usuarios.

## Recorrido del usuario

1. Abrir la aplicación en ejecución y seleccionar **Probar demo**.
2. Elegir Analista, Revisor o Auditor. Una sesión nueva y aislada prepara un estado anual CSV, evidencia de origen, DSCR de `1.5000`, controles de política versionada y un borrador sin conexión mediante el worker persistente.
3. Consultar hallazgos y evidencia como Analista. Cambiar a Revisor con el selector de rol y registrar una decisión con su motivo. Los tres roles tienen identificadores de actor simulados distintos, pero una misma persona los controla. Esto demuestra permisos del flujo, no aprobación independiente entre personas reales ni verificación de identidad de producción.
4. Cambiar a Auditor para consultar el historial y descargar informes JSON o PDF en inglés/español. El PDF incluye una instantánea JSON verificable.
5. **Reiniciar demo** finaliza la sesión actual y crea un expediente nuevo. **Finalizar demo** revoca las tres credenciales de rol. Ambas acciones conservan el expediente anterior y su auditoría.

Las credenciales permanecen en memoria del navegador; recargar pierde el acceso. Solo persiste la preferencia de idioma. Las sesiones vencen a los 30 minutos por defecto. Cerrar el navegador no revoca inmediatamente la sesión del servidor; sigue aplicándose el vencimiento. Si el servidor no responde al finalizar, se borran las credenciales locales y el vencimiento del servidor actúa como respaldo.

## Configuración y límites

`CDS_GUIDED_DEMO_ENABLED=false` es el valor predeterminado. `scripts/configure_demo.py` lo habilita en una instalación demo nueva. Las instalaciones existentes pueden activarlo en `.env`; se debe reiniciar la API y aplicar la migración `0006_guided_demo`. No se deben sobrescribir credenciales ni registros de consumo existentes.

| Parámetro | Predeterminado | Propósito |
|---|---|---|
| `CDS_DEMO_SESSION_TTL_SECONDS` | `1800` | Vigencia de credenciales controlada por el servidor; 60–7200 segundos |
| `CDS_DEMO_MAX_ACTIVE_SESSIONS` | `20` | Máximo de sesiones simultáneas sin vencer |
| `CDS_DEMO_MAX_SESSIONS` | `200` | Máximo de sesiones conservadas, incluidas las vencidas o finalizadas |

La base de datos serializa la admisión y responde 429 al alcanzar la capacidad. No existe purga automática del historial. Antes de ampliar el alojamiento se debe revisar retención y capacidad; reiniciar la base también borraría el registro acumulado de costos y no debe utilizarse para reponer el presupuesto. Este hito no proporciona protección de tráfico público de producción ni un proveedor de identidad de producción.

Las credenciales son tokens aleatorios almacenados como hashes SHA-256 en el servidor. Las tres se devuelven una sola vez al crear la sesión. Cada una está restringida al expediente de su sesión, incluidos listados y acceso a documentos/evaluaciones. Los usuarios guiados no pueden crear más expedientes, cargar fuentes, asignar identidades ni invocar modelos pagados. El espacio avanzado conserva su flujo de tokens configurados.

`POST /v1/demo/sessions` exige `X-Demo-Request: 1`, un rol inicial válido y solicitudes de navegador del mismo origen. Esto impide creación desde otros orígenes del navegador; no autentica bots. `POST /v1/demo/session/end` exige una credencial guiada activa. La política preparada debe estar publicada antes de crear sesiones.

## Verificación

```sh
uv run pytest -q tests/test_guided_demo.py
uv run python scripts/smoke_guided_demo.py
```

Las pruebas de integración cubren acceso por rol, evidencia preparada, aislamiento incluso con una membresía insertada incorrectamente, mutaciones restringidas, bloqueo del proveedor pagado, permisos de revisión, hashes, vencimiento/revocación, mismo origen, capacidad concurrente y reversión si falta la política. La prueba de humo requiere API/worker activos, política sintética publicada y modo guiado habilitado. Verifica dos sesiones aisladas, instantáneas y hashes de informes bilingües, y revocación sin imprimir credenciales. La capacidad y los resultados de pruebas no demuestran preparación para producción.

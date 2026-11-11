# Despliegue gratuito de la demostración pública

[English](../public-hosting.md) | **Español**

El perfil utiliza un servicio web Render Free y un proyecto Neon Free con PostgreSQL 16 separado. Está destinado a una demo sintética pequeña. La configuración del repositorio no demuestra un despliegue activo: la aceptación exige una URL real, acceso por roles mediante HTTPS, avance del worker, exportación verificada y revisión de la cuenta sin cargos.

## Opciones de alojamiento

| Plataforma | Encaje con la aplicación existente |
|---|---|
| [Render](https://render.com/docs/free) | Ejecuta Docker/Python; API y worker comparten un contenedor web Free |
| [Vercel](https://vercel.com/docs/frameworks/backend/fastapi) | Admite FastAPI como función; el worker necesita adaptar su ejecución y recuperación al modelo de funciones |
| [Netlify](https://www.netlify.com/platform/core/functions/) | Aloja la interfaz; las funciones nativas usan JavaScript/TypeScript/Go, por lo que el backend Python necesita otro alojamiento o adaptación |
| [Neon](https://neon.com/docs/introduction/plans) | PostgreSQL persistente separado; se utiliza la conexión TLS directa, no la agrupada |

Render Free se suspende después de 15 minutos sin tráfico entrante y puede tardar aproximadamente un minuto en despertar. Su disco es efímero. PostgreSQL Free de Render vence a los 30 días; por eso este perfil usa Neon. Las horas, compilaciones y transferencias gratuitas tienen límites; **pueden existir cargos por exceso aunque las instancias sean gratuitas si hay un método de pago asociado**. Solo se seleccionan opciones Free/Hobby y una cuenta sin método de pago; si se exige pago o una mejora de plan, se debe detener la publicación. No se incluyen worker de pago, disco, base de datos, dominio personalizado ni servicios para evitar la suspensión. Consultar [límites actuales](https://render.com/docs/free) y [facturación](https://render.com/docs/faq).

Neon Free indica actualmente 100 CU-horas, 1 GB de almacenamiento y 5 GB de transferencia pública por proyecto, con suspensión automática. Los límites y la disponibilidad pueden cambiar. Se conserva el plan Free y se verifica el panel antes de publicar. El sondeo consume cómputo mientras Render está activo. La suspensión puede demorar trabajos; este perfil no ofrece una demo ininterrumpida.

## Límites del proceso público

`render.yaml` define un único servicio Free, despliegues manuales, `/readyz` y la imagen Docker existente. `python -m credit_support.hosted_demo` inicia una API y un worker, detiene ambos ante el cierre y termina si cualquiera de los dos se detiene. Las concesiones PostgreSQL conservan la recuperación. Al suspenderse el contenedor se detienen ambos procesos; los trabajos esperan hasta otro despertar.

El supervisor exige una URL TLS directa de `cds_runtime` y comprueba que el rol no tenga privilegios elevados, membresías, propiedad de esquema/base ni permiso de creación en el esquema público. Exige la migración vigente y una política publicada. No ejecuta migraciones con credenciales de propietario dentro del servicio público.

Los procesos hijos reciben solo variables permitidas. OpenAI está desactivado, su clave vacía y las identidades estáticas vacías. El modo público rechaza modelos reales, claves de proveedor o credenciales estáticas, e ignora `.env` locales. El registro de consumo y la configuración privada del proyecto local permanecen separados y no deben copiarse al alojamiento.

La página pública ofrece sesiones guiadas y oculta el formulario avanzado. Se conservan aislamiento, vencimiento, revisión inmutable e integridad de informes. El blueprint permite cinco sesiones activas y 100 conservadas, incluidas las finalizadas/vencidas. No hay purga automática: alcanzar la capacidad requiere revisión operativa, no reiniciar la base ni reponer presupuestos.

El `Origin` del navegador debe coincidir con el origen HTTPS explícito (`CDS_PUBLIC_ORIGIN` o `RENDER_EXTERNAL_URL`). Uvicorn sigue sin reescribir cabeceras de proxy. El limitador puede agrupar visitantes detrás de un proxy del proveedor: es un límite conservador por proceso, no una protección distribuida. No se confía en cabeceras reenviadas arbitrarias para evitarlo.

## Preparación privada de la base

Crear un proyecto Neon Free nuevo y aislado con PostgreSQL 16. Conservar la URL del propietario en privado y elegir la conexión **directa**. Los [roles creados mediante SQL](https://neon.com/docs/manage/roles) evitan los permisos elevados de los creados en consola. Las [conexiones agrupadas](https://neon.com/docs/connect/connection-errors) pueden rechazar los parámetros de timeout de la aplicación.

Crear el archivo local ignorado `.env.hosting`:

```dotenv
CDS_MIGRATION_DATABASE_URL=postgresql+psycopg://OWNER:PASSWORD@DIRECT_HOST/neondb?sslmode=require
```

Reemplazar los valores en privado y conservar los parámetros TLS adicionales proporcionados por Neon. No pegar credenciales en el chat, incidencias, Git ni argumentos de comandos. Desde la raíz del repositorio:

```sh
uv run python scripts/provision_public_demo.py
```

La utilidad rechaza un archivo de salida o rol existentes. En una transacción crea el rol restringido, aplica migraciones con la conexión del propietario y publica la política sintética. Guarda únicamente la URL restringida en `.env.hosting.runtime`, con creación exclusiva, y confirma la transacción. Nunca restablece contraseñas ni sobrescribe credenciales. Si la confirmación resulta incierta, se conserva cualquier archivo privado generado y se inspecciona el proyecto antes de reintentar; no hay reparación destructiva automática. Este flujo debe comprobarse en el proyecto Neon real antes de aceptar la publicación.

## Configuración en Render

1. Usar una cuenta/espacio gratuito sin método de pago. La creación de cuenta, los términos y los permisos de GitHub corresponden a la persona propietaria.
2. Conectar solo `credit-decision-support`, sin cambiar su visibilidad. Importar el blueprint desde el commit de despliegue aceptado en `main`.
3. Confirmar que se muestra **un servicio web Free**, sin base de datos Render ni recursos de pago, y despliegue automático desactivado. Configurar `CDS_DATABASE_URL` con la URL restringida de `.env.hosting.runtime`. No cargar `.env`, la URL propietaria ni claves OpenAI.
4. Desplegar manualmente. Render proporciona origen HTTPS y puerto. Esperar la verificación de rol/migración/política, la disponibilidad y ambos procesos.
5. Abrir la URL `onrender.com` devuelta. Iniciar como Analista, consultar evidencia, cambiar a Revisor, registrar motivo, cambiar a Auditor y exportar ambos formatos. Verificar aislamiento entre demos y rechazo de proveedores pagados.
6. Confirmar que el servicio, la facturación y Neon siguen en planes gratuitos. Registrar URL real, commit, arranque observado y resultado de prueba por separado de las mediciones locales.

No se afirma una URL pública ni una preparación exitosa en el proveedor hasta observar esos pasos. Si faltan cuentas o autorización, la preparación puede revisarse sin publicar.

# Amenazas y controles verificables

[English](../threat-model.md) | **Español**

| Amenaza | Control previsto | Prueba de aceptación |
|---|---|---|
| Instrucciones maliciosas en PDF/política | Contenido como dato, herramientas permitidas, sin shell y validación de salida | PDF ordena ignorar política: ninguna herramienta o regla cambia |
| Cifra/cita inventada | Verificar hash, extracto y valor; rechazo de conclusiones sin evidencia | Valor alterado o cita inexistente bloquea el hallazgo |
| Lectura de otro caso | Identidad servidor, autorización por caso en cada ruta | Actor ajeno recibe 404 sin metadatos |
| Autoaprobación o decisión del modelo | Reviewer distinto del preparador, endpoint humano separado | analyst y worker no pueden resolver |
| Revisión obsoleta | Bloqueo de caso, evaluation_id y revisión esperada | Carrera carga/revisión devuelve 409 para snapshot antiguo |
| Doble ejecución | Idempotencia y unicidad de paso/snapshot | Dos peticiones simultáneas producen un job y un resultado |
| PDF bomba o ruta manipulada | Límites, parser aislado con timeout, storage_key generado por servidor | Archivo excesivo/path traversal rechazado |
| Robo de claves | Entorno local ignorado, logs redactados, CI con secretos mínimos | Escaneo y prueba de redacción |
| Auditoría manipulada | Rol runtime sin UPDATE/DELETE; cadena hash y copias | Alteración detectada; registrar límite frente a administrador |
| Mezcla de políticas | Selección exacta antes de RAG, filtros y comprobación de citas | Fragmento de otra versión rechazado |
| Dependencia/proveedor caído | Timeout, tres intentos, lease y mock CI | Reinicio conserva pasos confirmados sin efectos duplicados |

Fronteras: usuario→API, archivos→parser, contenido→LLM, LLM→herramientas, API/worker→DB y almacenamiento, runtime→proveedor. No usar datos reales. El proveedor debe poder desactivarse; CI funciona sin llamadas externas. Una identidad demo no es autenticación apta para producción.

## Evidencia de implementación

La [evaluación de seguridad y carga](hardening.md) relaciona controles implementados, pruebas reproducibles y límites pendientes. Las pruebas de integración cubren rechazo de fuentes/citas inventadas, aislamiento, autoaprobación, revisión obsoleta, duplicados, límites de archivos, bloqueo del parser, hashes y errores de proveedor. La fase 6 añade límite de creación de demos, registros sin datos sensibles y recuperación de concesiones en otro proceso. La restauración de copias y las pruebas de penetración independientes siguen sin verificarse.

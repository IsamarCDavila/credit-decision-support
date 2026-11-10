# Guía de contribución

[English](CONTRIBUTING.md) | **Español**

## Documentación

El inglés es el idioma principal. Los Markdown de la raíz usan `.md` para inglés y `.es.md` para español. Los documentos técnicos en inglés se encuentran en `docs/`; sus equivalentes en español replican las rutas en `docs/es/`. Cada documento incluye enlaces recíprocos de idioma cerca del título. Ambas versiones deben actualizarse en el mismo pull request, incluidas tablas, advertencias y limitaciones de validación. Los identificadores de API, rutas, comandos y nombres de estados se conservan entre traducciones.

La documentación se dirige a lectores sin acceso a conversaciones de desarrollo. Describe el producto, arquitectura, requisitos, comportamiento verificado y limitaciones conocidas. Excluye instrucciones para asistentes, historial del chat, nombres sugeridos para el repositorio, pasos para conectar cuentas, observaciones de equipos de una sesión y borradores destinados a un pull request. Las instrucciones reutilizables de instalación deben indicar requisitos y resultados esperados.

Debe distinguirse entre comportamiento previsto, implementación y resultados medidos. Un contrato de diseño no demuestra que un control funcione. Los registros de validación identifican comando, cobertura y límites. Las afirmaciones de rendimiento requieren mediciones reproducibles. Los informes usan la marca de simulación correspondiente a su idioma: SIMULATION en inglés y SIMULACIÓN en español.

## Cambios y revisión

Se utiliza una rama y un pull request por hito de implementación. La descripción explica el cambio concreto, su motivo, validación y limitaciones relevantes. Los títulos de pull request y mensajes de commit se escriben en inglés; puede añadirse un resumen en español después del inglés. La integración requiere cumplir los criterios de aceptación de la fase y las comprobaciones aplicables.

## Tratamiento de datos

Solo se versionan ejemplos sintéticos. No se incluyen archivos `.env`, credenciales, documentos reales de clientes, registros de proveedores ni resultados generados sin revisar. Las ampliaciones de infraestructura requieren una decisión de arquitectura y evidencia de que la nueva dependencia resuelve un problema medido.

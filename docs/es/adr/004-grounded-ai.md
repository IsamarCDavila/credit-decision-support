# ADR-004: Roles de IA acotados y presupuesto persistente

[English](../../adr/004-grounded-ai.md) | **Español**

Estado: aceptado para la fase 4. Fecha: 2026-11-10.

## Decisiones

1. Utilizar Responses API de OpenAI mediante un adaptador HTTP pequeño y un proveedor determinista sin conexión. El consumo requiere activación explícita y clave privada. Cada evaluación fija el modelo; no hay sustitución silenciosa de proveedor o modelo.
2. Mantener una orquestación explícita: propuesta de observaciones, validación y herramientas financieras deterministas, y organización del borrador con evidencia. Dos roles especializados y una referencia generalista comparten validadores y motor financiero. No se implementan planificación autónoma ni acceso de agentes al shell.
3. Exigir cobertura exacta de observaciones en los formatos estructurados existentes. No se omiten contradicciones. El extractor determinista conserva la autoridad; la confianza del modelo no convierte datos faltantes, ambiguos o inválidos en hechos verificados.
4. Generar texto material bilingüe mediante tarjetas verificadas. El modelo selecciona y ordena con cobertura obligatoria completa. Se restringe la salida factual en lugar de intentar demostrar el respaldo de prosa arbitraria. Se limita la libertad expresiva y no se evalúan razonamiento narrativo ni alucinaciones de texto libre.
5. Reservar costos de forma persistente antes de llamar al proveedor, serializar reservas por base y limitar la campaña inicial a US$2. Conservar reservas inciertas y prohibir reintentos pagados automáticos. Persistir respuestas completadas para recuperación. Proteger registros completados y borradores frente a modificaciones.
6. Ejecutar operaciones de red fuera de transacciones de negocio, con heartbeat del worker. Controlar escrituras mediante bloqueos y token de arrendamiento. Los resultados deterministas pueden sobrevivir a un fallo de redacción; una evaluación fallida nunca expone un borrador final válido.
7. Separar mediciones reales de pruebas mock. Documentar el menor contexto intermedio del generalista y los máximos de salida iguales. Registrar fallos del proveedor como mediciones bloqueadas, no como fallos de calidad ni de cálculo financiero. La muestra pequeña no demuestra superioridad del flujo especializado.

## Consecuencias

El formato estructurado se verifica sin confiar en el modelo y las pruebas no generan consumo pagado. El comportamiento real depende del acceso al modelo y la cuota del proveedor. Extracción narrativa, recuperación semántica, redacción libre, límites de facturación de toda la cuenta e interfaz de revisión quedan como ampliaciones o hitos separados. La configuración, persistencia y límites medidos están en el [flujo de IA](../ai-workflow.md).

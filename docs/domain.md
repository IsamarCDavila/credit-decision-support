# Contratos de dominio v0.1

## Hechos y evidencia

Un hecho tiene `fact_id`, `evaluation_id`, clave, valor decimal como cadena o null, moneda, unidad, periodo ISO con inicio y fin, base `individual`, estado y `evidence_ids`. Estados: `extracted`, `missing` (sin fuente), `ambiguous` (fuentes o interpretaciones incompatibles), `invalid` (no cumple el contrato). No existe `unknown`. Solo `extracted` entra en cálculos. La confianza opcional es una señal sin calibrar y nunca sustituye validación.

Una evidencia tiene `evidence_id`, documento, SHA-256 y extracto exacto. PDF: página desde 1, y offsets del texto normalizado por página desde 0, fin exclusivo, con versión de parser. CSV: fila desde 2 contando cabecera en fila 1 y nombre de columna único. La integridad del hash y la correspondencia del valor con el extracto deben verificarse. Regiones visuales son una extensión futura.

Un cálculo tiene `calculation_id`, fórmula y versión, entradas por fact_id, salida decimal o null y estado. Una afirmación del informe tiene `claim_id`, texto, materialidad, evidence_ids y calculation_ids. Reglas citan `policy_fragment_ids`. Se prohíbe presentar como verificada una conclusión sin soporte; una advertencia de ausencia se marca explícitamente. El informe usa plantillas para resultados críticos.

## Estados independientes

- Procesamiento: CREATED → DOCUMENTS_RECEIVED → EXTRACTING → VALIDATING → POLICY_CHECK → DRAFT_READY. Después de publicar el borrador la ejecución es inmutable.
- Revisión: NOT_READY → PENDING → APPROVED | REJECTED | NEEDS_MORE_INFO. DRAFT_READY inicia PENDING. Cada transición humana conserva autor, motivo y hora UTC.
- Recomendación: DRAFT_ONLY con resultado `meets_rules`, `exceptions` o `insufficient_evidence`; nunca cambia directamente el estado humano.

Errores de procesamiento: FAILED_RETRYABLE puede reanudar desde el último paso confirmado, hasta tres intentos por paso; después FAILED_TERMINAL. Cada paso usa una clave única `(evaluation_id, step, input_hash)` para deduplicar resultados y eventos. La expiración de un lease permite a otro worker tomar el job. Efectos y eventos se confirman en la misma transacción cuando ambos residen en DB.

NEEDS_MORE_INFO no reabre una evaluación: nuevos documentos originan otra. Un caso conserva `current_evaluation_id`; cambiarlo marca la revisión anterior como histórica, sin borrarla. Una revisión requiere evaluation_id y revisión esperada; si la evaluación ya no es actual o fue revisada se responde 409. Bloquear la fila del caso durante selección y revisión evita carreras.

## Política, publicaciones y versiones

Una política publicada fija ámbito, vigencia, texto, fragmentos, reglas y hashes. Publicación transaccional con bloqueo por ámbito para evitar solapamientos. El motor tiene operadores permitidos y reglas tipadas, sin eval ni código arbitrario. No actualizar una política publicada: crear versión nueva. El evaluador fija la versión antes de recuperar texto.

## HTTP y autorización

Roles analyst, reviewer, auditor y admin, más autorización por caso. analyst crea/carga/evalúa; reviewer revisa; auditor consulta informes y eventos; admin publica políticas pero no obtiene acceso universal a casos. Una identidad demo estable debe resolverse del lado servidor, nunca de un role enviado por el cliente.

Idempotency-Key obligatorio en creación, carga, evaluación y revisión; ámbito actor+ruta, vigencia 24 h. Guardar hash del payload y respuesta: repetición idéntica devuelve la misma respuesta; payload distinto devuelve 409. La ejecución activa sobre el mismo snapshot se deduplica aunque cambie la clave. Cargas nuevas tras evaluación no alteran snapshots previos.

Errores comunes: 400 entrada mal formada, 401 sin identidad, 403 sin permiso, 404 inexistente/no visible, 409 conflicto o fase incorrecta, 413 límite de carga, 422 contenido válido sintácticamente pero no aceptable. Tamaño máximo 10 MiB/documento, 20 documentos/caso y 100 páginas/PDF. El reporte requiere DRAFT_READY; incluye siempre SIMULACIÓN y estado humano actual.

## Reconstrucción y retención

Reconstrucción significa recuperar el snapshot y las salidas almacenadas, verificar hashes, reglas, citas y revisión. No implica regeneración idéntica del LLM. Conservar respuestas del modelo, parámetros, prompts y versiones con acceso restringido; nunca secretos. La demo local conserva datos hasta borrado explícito. Una limpieza destruye adjuntos y salidas de manera documentada y deja tombstones sin contenido; ya no se declara reconstruible ese expediente. No contiene PII real.

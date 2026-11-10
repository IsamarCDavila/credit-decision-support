# ADR-002: Ingesta transaccional de documentos sintéticos

[English](../../adr/002-ingestion.md) | **Español**

Estado: aceptado para la fase 2. Fecha: 2026-11-10.

## Contexto

La demo acotada admite hasta 20 documentos sintéticos por expediente y 10 MiB por documento. La ingesta debe conservar bytes originales, localizadores de evidencia, hashes y versión del parser sin inconsistencias entre almacenamiento, metadatos y eventos de auditoría.

## Decisiones

1. Almacenar bytes inmutables y representaciones de las fuentes en PostgreSQL, con un rol de ejecución restringido. Los bytes originales, metadatos y evento de carga se confirman en una transacción. Esto sustituye la propuesta inicial de archivos privados para el MVP acotado. El almacenamiento de objetos permanece como posible ampliación, con reglas explícitas de recuperación y retención.
2. Admitir un esquema versionado de estados sintéticos, sin afirmar compatibilidad con cualquier PDF financiero. CSV utiliza columnas exactas; PDF utiliza etiquetas de texto explícitas. Las entradas declaran datos sintéticos, USD, año calendario completo y estados individuales. La declaración no prueba automáticamente procedencia ni ausencia de datos personales.
3. Ejecutar el parser en un proceso separado, sin shell y con timeout de 15 segundos. Linux aplica un máximo de 512 MiB de espacio de direcciones y 12 segundos de CPU. Windows dispone del timeout y límites de archivo/texto/páginas, sin un límite equivalente de memoria. El parser no ejecuta instrucciones, scripts ni acciones del documento.
4. Conservar el texto normalizado por página PDF y las filas CSV con una versión del parser. Los offsets PDF son índices de puntos de código Unicode desde cero sobre texto normalizado NFC y saltos LF, con fin exclusivo. Las filas CSV empiezan en 2 después de la cabecera; no se admiten celdas multilínea.
5. Fijar identificadores, SHA-256 y versiones de parser en los snapshots. El worker verifica integridad y localizadores antes de guardar hechos y evidencia de forma atómica. Las nuevas cargas invalidan el puntero actual y conservan evaluaciones históricas.
6. Utilizar exclusivamente extracción determinista. Los valores faltantes, inválidos y contradictorios quedan explícitos, sin completar datos ni calcular ratios. La extracción termina en VALIDATING; las políticas, borradores de recomendación y decisiones humanas corresponden a etapas posteriores.

## Consecuencias

La demo es reproducible y no requiere un LLM ni almacenamiento de objetos separado. La base y sus copias crecen con los archivos cargados; esta decisión no establece una estrategia de almacenamiento de producción. La extracción con esquema conocido no demuestra exactitud sobre documentos financieros reales. Adoptar almacenamiento de objetos o ampliar formatos requiere una nueva decisión y pruebas de evidencia correspondientes.

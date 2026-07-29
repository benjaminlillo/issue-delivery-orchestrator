# Criterios obligatorios de Refactor

Aplicar esta revisión únicamente al código humano creado o modificado por el run. Obedecer primero
los `AGENTS.md` aplicables cuando establezcan una regla más específica. Excluir lockfiles,
migraciones generadas, snapshots y otros artefactos generados mecánicamente; registrar cada
exclusión.

## Preparar la revisión

1. Construir el allowlist desde el diff de implementación y los commits adoptados de la issue.
2. Identificar archivos creados y modificados, su cantidad de líneas actual y, para archivos
   existentes, su cantidad de líneas en el baseline anterior al run.
3. Clasificar los archivos por responsabilidad: controller, service, repository, helper/utilidad,
   componente, test u otro.
4. Inspeccionar implementaciones y llamadas reales; no aprobar por nombre de archivo.

## Gate de capas

### Controllers

- Mantenerlos como adaptadores de transporte: recibir y validar la entrada, obtener contexto,
  delegar a un service y formar la respuesta.
- Rechazar reglas de negocio, decisiones de dominio, coordinación de casos de uso, acceso directo a
  repositories, formación de queries, filtrado de entidades o mutaciones de persistencia.
- Extraer toda lógica de negocio introducida hacia el service dueño.

### Services

- Mantener en el service dueño las reglas, decisiones, invariantes y coordinación del caso de uso.
- Rechazar formación de queries: query builders, joins, condiciones ORM, selects, ordenamiento,
  paginación o composición de filtros de persistencia.
- Delegar cada consulta a un método específico del repository, nombrado por la intención del caso
  de uso. Evitar pasar al repository una query formada por el service.
- No trasladar reglas de negocio al repository para eliminar lógica del service.

### Repositories

- Limitar su responsabilidad a consultas, persistencia y traducción de datos de su módulo.
- Permitir la construcción de queries necesaria para implementar sus métodos específicos.
- Rechazar reglas de negocio, decisiones de flujo, autorización de dominio, coordinación de casos
  de uso o comportamiento que dependa de la intención del usuario.

Marcar `NOT_APPLICABLE` con evidencia cuando el diff no cree ni modifique alguna de estas capas.

## Gate de helpers y reutilización

Antes de aceptar un helper nuevo:

1. Buscar por intención, nombre, firmas y operaciones equivalentes primero dentro de la app y luego
   en todo el repositorio.
2. Reutilizar una opción existente cuando su contrato y ownership sean compatibles; no duplicarla
   con otro nombre.
3. Si el mismo helper ya existe localizado en otro lugar y ambos son consumidores reales, extraer
   las dos implementaciones hacia el scope compartido más estrecho que las pueda poseer.
4. No crear una abstracción compartida para un único consumidor ni ampliar un contrato sólo para
   aparentar reutilización.

Registrar búsquedas ejecutadas, coincidencias evaluadas y decisión de reuse, extracción o
implementación local.

## Gate de diseño y clean code

Revisar y corregir únicamente problemas introducidos o agravados por el run:

- responsabilidades mezcladas o ownership duplicado;
- lógica duplicada, divergente o conocimiento repetido;
- god objects, módulos superficiales o wrappers pass-through sin conocimiento propio;
- funciones largas, anidamiento evitable, control de flujo difícil de seguir o side effects
  ocultos;
- APIs con boolean flags ambiguos, parámetros primitivos sin semántica o contratos más amplios que
  sus consumidores reales;
- acoplamiento indebido entre módulos, abstracciones con fugas o dependencias en dirección
  contraria a la arquitectura;
- estado global mutable, magic values relevantes, código muerto y generalización especulativa;
- nombres que no expresen intención o comentarios usados para compensar una estructura confusa.

No aplicar patrones de diseño por catálogo. Cada refactor debe eliminar un problema observable y
mantener interfaces pequeñas, cohesión alta y complejidad oculta por el dueño correcto.

## Gate de tamaño

Medir con `wc -l` todos los archivos humanos creados o modificados:

- Un archivo nuevo no puede superar 200 líneas. Dividirlo por responsabilidades cohesivas antes de
  aprobarlo.
- Un archivo existente de hasta 200 líneas no puede cruzar el límite debido al run.
- Un archivo que ya superaba 200 líneas puede conservar su deuda previa, pero el run no debe
  aumentarlo materialmente. Usar como umbral operativo un crecimiento neto superior a 20 líneas o
  la incorporación de una responsabilidad nueva: cualquiera de ambos exige extraer el nuevo bloque
  hacia su dueño correcto.
- No dividir mecánicamente sólo para satisfacer el conteo. La extracción debe mejorar ownership,
  cohesión o profundidad del módulo.

Si un formato humano es indivisible por contrato y supera el límite, bloquear o registrar una
excepción sustentada en el spec o `AGENTS.md`; no inventar excepciones por conveniencia.

## Recibo y cierre

Guardar un recibo Markdown bajo
`.local-runtime/issue-delivery-orchestrator/<run-id>/validation/refactor-review.md` con:

| Gate | Resultado | Evidencia | Cambios realizados |
| --- | --- | --- | --- |
| Controllers | PASS / FIXED / NOT_APPLICABLE | Paths y símbolos | Resumen |
| Services | PASS / FIXED / NOT_APPLICABLE | Paths y símbolos | Resumen |
| Repositories | PASS / FIXED / NOT_APPLICABLE | Paths y símbolos | Resumen |
| Helpers/reuse | PASS / FIXED / NOT_APPLICABLE | Búsquedas y paths | Resumen |
| Diseño/clean code | PASS / FIXED | Findings inspeccionados | Resumen |
| Tamaño | PASS / FIXED | Conteos baseline/final | Resumen |

Incluir además:

- allowlist final;
- excepciones y exclusiones justificadas;
- archivos que salieron del allowlist para corregir `AGENTS.md`;
- comandos de unit tests y typecheck ejecutados después del último refactor;
- resultado final y validaciones no ejecutadas.

No emitir el checkpoint de Refactor mientras exista un gate `FAIL`, una excepción sin fuente o una
validación atribuible al refactor pendiente.

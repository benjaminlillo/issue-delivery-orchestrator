---
name: issue-delivery-implement
description: "Implementar o reparar un ticket aprobado con alcance YAGNI, obediencia a AGENTS.md, seguimiento exacto del spec, validaciones enfocadas del repositorio y un commit local por ticket o causa raíz. Usar también ante ajustes dentro de Issue Delivery Orchestrator; exigir revisión UI en delivery full o refresco verificable del runtime en manual-runtime."
---

# Implement

Implementar una unidad de trabajo a la vez. Exigir como entrada el spec vigente —incluyendo
`Architecture Constraints`—, ticket o finding, SHA inicial y criterios de aceptación. Leer todos
los `AGENTS.md` y fuentes arquitectónicas citadas por el spec antes de editar.

Leer [validation.md](references/validation.md) antes de calcular o ejecutar validaciones.

## Delimitar

1. Inspeccionar código, tests y patrones existentes.
2. Verificar si el comportamiento ya está satisfecho. En ese caso devolver `NO_OP` con evidencia y validación; no crear commit vacío.
3. Identificar la solución mínima compatible con el spec. No añadir abstracciones, compatibilidad ni defensas especulativas.
4. Tratar las `Architecture Constraints` aprobadas como contrato vinculante. Si el pedido o el spec
   contradicen un `AGENTS.md` aplicable o una fuente arquitectónica citada, no editar. Devolver
   `NEEDS_USER_DECISION` con las fuentes en conflicto.
5. Mantener cualquier log, prompt o memoria bajo el directorio del run en `.local-runtime`.

## Implementar

- Respetar la arquitectura y política de auditoría del backend dueño.
- Mantener interfaces pequeñas y cambios localizados.
- Inspeccionar cobertura existente antes de añadir tests; extender un seam estable para comportamiento o riesgo distinto.
- No editar migraciones comprometidas; generarlas con el script del proyecto dueño.
- Mantener llamadas externas fuera de transacciones.
- No alterar archivos ajenos al ticket, salvo que sean indispensables para la causa raíz.
- No pushear.

## Validar

1. Calcular el delta del ticket desde su SHA inicial, incluyendo archivos creados, modificados, renombrados y eliminados.
2. Ejecutar todos los comandos declarados en `## Validation`.
3. Usar el mecanismo existente del repositorio para calcular proyectos o paquetes afectados por ese
   delta y sus dependientes. En un workspace Nx, aplicar el procedimiento de `validation.md`.
4. Ejecutar typecheck sólo para proyectos afectados que lo expongan.
5. Ejecutar unit tests sólo para proyectos afectados que los expongan.
6. No ejecutar lint, E2E ni validación de todo el repo salvo comando focalizado explícito del ticket.
7. Reparar y repetir hasta tres ciclos. Si sigue rojo, devolver `BLOCKED` con logs reales.
8. No reparar fallos demostrablemente presentes en el SHA integrado de la branch target del run;
   reportarlos como base failures.

## Reparaciones posteriores a Implement

Cuando el input sea un ajuste, corrección o reporte de algo que no funciona, cualquiera sea su origen:

1. Convertir el reporte en un escenario de aceptación reproducible y listar las historias afectadas.
2. Implementar y ejecutar la validación enfocada habitual.
3. Leer `handoffMode` del estado del run. En `full`, marcar la salida como `UI_REVIEW_REQUIRED` y
   entregar el SHA candidato, escenario y superficies afectadas al reviewer fijado por el modo. En
   `manual-runtime`, marcarla como `FINAL_RUNTIME_RESET_REQUIRED` y entregar el SHA y los
   servicios afectados al orquestador.
4. En `full`, invocar `$issue-delivery-cua-review` en modo `superset` o `vanilla`,
   `$issue-delivery-browser-review` en modo `codex`, o `$issue-delivery-playwright-review` en modo
   `conductor-cloud`, después del último cambio. Para runs legacy, usar el `reviewerMethod`
   existente. No concluir ni hacer handoff mientras no exista un PASS de ese reviewer para el
   mismo SHA. En `manual-runtime`, no invocar un reviewer: detener los
   procesos previos, reemplazar el Local Runtime, levantar de nuevo las apps, verificar endpoints y
   exigir un nuevo `final-runtime-handoff.json` sobre ese SHA antes de entregar los links al usuario.
5. Si la revisión falla, usar el finding como nueva entrada de reparación y repetir, hasta el límite de cinco ciclos administrado por `$issue-delivery-orchestrator`.
6. Invalidar el PASS previo ante cualquier edición posterior capaz de afectar el flujo.

En `full`, no omitir la revisión UI porque el cambio parezca trivial, sea backend, provenga de
review/Actions, tenga tests verdes o no estuviera modelado como historia UI. El skill padre debe
crear un escenario `REPAIR-<n>` y verificar el comportamiento por la UI real; si eso es imposible,
devolver `BLOCKED` en lugar de declarar éxito. La excepción `manual-runtime` sólo sustituye ese gate
por salud del runtime y un handoff honesto; nunca permite declarar la UI aprobada.

## Entregar

Antes del commit, devolver:

- Archivos del delta.
- Proyectos o paquetes afectados.
- Comandos ejecutados y resultados.
- Tests no ejecutados y razón.
- Historias UI invalidadas por el cambio.
- Estado del gate: `UI_REVIEW_REQUIRED`, `FINAL_RUNTIME_RESET_REQUIRED`, `PASS` o `BLOCKED`,
  incluyendo reviewer o runtime según corresponda.

Crear un commit descriptivo sólo cuando todo lo atribuible al ticket esté verde. Para una reparación de review, usar un commit por causa raíz; agrupar únicamente findings inseparables.

Durante Refactor, limitar cambios al allowlist entregado. Salir de él sólo para una violación concreta de `AGENTS.md` y registrar regla, path y razón.

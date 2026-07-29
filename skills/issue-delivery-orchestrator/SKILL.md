---
name: issue-delivery-orchestrator
description: "Orquestar de extremo a extremo una issue de Linear en modo Codex o Superset: adoptar el worktree, usar la rama de Linear, publicar spec/tickets, implementar, refactorizar, integrar la branch objetivo, revisar UI, crear la PR y converger bots y Actions. Usar también para ajustes posteriores; toda reparación requiere una nueva revisión UI antes del handoff."
---

# Issue Delivery Orchestrator

Operar como plano de control conversacional. Usar el CLI privado como motor determinista; no ejecutar un segundo Grill interactivo mediante `codex exec`. Mantener toda decisión humana en la conversación actual.

Leer [workflow-contract.md](references/workflow-contract.md) antes de iniciar o reanudar una ejecución.

## Iniciar o reanudar

1. Resolver `<plugin-root>` como el directorio que contiene `.codex-plugin/plugin.json`. Ejecutar
   `python3 <plugin-root>/scripts/issue-delivery config` y bloquear si faltan
   `LINEAR_EXPECTED_EMAIL`, `GITHUB_EXPECTED_LOGIN` o no puede resolverse el repositorio objetivo
   desde la configuración o el worktree actual.
2. Exigir una issue existente de Linear por ID o URL. Para un run nuevo, permitir un modo explícito
   del usuario o detectarlo desde el worktree actual:

   - `codex`: iniciar el chat en la app de Codex con **Worktree** seleccionado y elegir la base
     solicitada, o la `defaultBase` del perfil. Codex crea el worktree antes de ejecutar el loop.
     Fijar el chat hasta el merge y cleanup final.
   - `superset`: crear en Superset el worktree sobre la rama entregada por Linear y abrir la sesión
     dentro de ese workspace.

3. Antes de cambiar de directorio, ejecutar `git rev-parse --show-toplevel` en el workspace actual y
   conservar esa ruta absoluta. No iniciar modo `codex` desde Local ni modo `superset` desde otro
   checkout.
4. Ejecutar, agregando `--mode <codex|superset>` sólo cuando el usuario lo haya indicado:

   ```bash
   python3 <plugin-root>/scripts/issue-delivery <issue> --worktree <ruta> \
     [--mode <codex|superset>] \
     [--base <branch>] [--new-run]
   ```

5. Confirmar `modeSource` y `developmentMode` en la respuesta. La detección usa, en orden:
   `SUPERSET_WORKSPACE_PATH` coincidente, raíces configuradas y componentes inequívocos de la ruta
   como `.codex` o `superset-worktrees`. Si no puede decidir o detecta ambas señales, pedir el modo
   al usuario; no elegir un default. El modo determina el workspace y reviewer durante todo el run:

   - `codex` adopta el worktree del chat, acepta su `detached HEAD`, lo conecta a la rama de Linear
     y usa `$issue-delivery-browser-review`.
   - `superset` adopta el worktree ya conectado a la rama de Linear y usa `$issue-delivery-cua-review`. También
     acepta `SUPERSET_WORKSPACE_PATH`.

6. Usar la branch base del perfil por defecto. En modo Codex, crear una rama inexistente desde el
   último `origin/<base>`; reutilizar la rama local o remota de la issue cuando exista.
7. No cambiar modo, worktree ni reviewer después de crear el run. Obedecer `currentPhase`,
   `developmentMode` y `reviewerMethod`; no recrear un run preservado.
   En modo Codex, no usar Handoff a Local: el estado ignorado bajo `.local-runtime` debe permanecer
   en el mismo worktree/chat.
8. Trabajar exclusivamente en el worktree retornado. Guardar prompts, snapshots, logs y evidencias
   bajo `.local-runtime/issue-delivery-orchestrator/<run-id>/`.
9. No guardar tokens, cookies ni secretos en el worktree. El CLI valida las identidades Linear y
   GitHub configuradas antes de mutar servicios.

Los runs anteriores sin `mode` persistido conservan su worktree y reviewer históricos; exponer
`developmentMode=codex` sólo para `codex-browser` y `developmentMode=superset` para `cua-driver`,
sin migrar estado, ramas ni procesos. Las sesiones que ya están ejecutando el loop continúan sobre
ese contrato legacy.

Toda adopción exige el mismo repositorio y `.local-runtime` ignorado. Superset exige la rama exacta
de Linear o un prefijo truncado con el mismo ID. Codex admite el `detached HEAD` recién creado, pero
bloquea si tendría que abandonar commits propios o mezclar cambios locales con otra base. Conservar
`adoptedStatus` como baseline: no atribuir, descartar ni incluir silenciosamente cambios
preexistentes en commits del loop.

Si una fase se bloquea, registrar y detener procesos propios:

```bash
python3 <plugin-root>/scripts/issue-delivery <issue> block --reason "<causa>"
```

Agregar `--decision` cuando se requiera una elección del usuario. Tras resolverla:

```bash
python3 <plugin-root>/scripts/issue-delivery <issue> resume
```

## Invariante de reparación y handoff

Aplicar esta regla en cualquier fase y también después de `completed_preserved`. Aplicarla a toda modificación correctiva posterior al inicio de Implement, sin importar si nace de un reporte del usuario, finding de Cua, review humano o automatizado, Action fallida, conflicto o descubrimiento del agente.

Considerar ciclo de reparación toda instrucción que pida ajustar, corregir o cambiar una implementación existente, o que reporte que algo no funciona, se ve mal o no cumple lo esperado. No tratarla como una edición aislada.

1. Reanudar el mismo run y worktree. Capturar el reporte exacto como escenario de aceptación de reparación.
2. Identificar las historias afectadas. Si el caso no estaba en el spec, crear una historia temporal `REPAIR-<n>` dentro del estado ignorado del run con precondición, pasos y resultado esperado; no ampliar el spec remoto por un bug compatible con su intención.
3. Invocar `$issue-delivery-implement`, ejecutar la validación enfocada y dejar la branch en su estado final.
4. Levantar o refrescar el Local Runtime y las apps desde ese estado final.
5. Invocar siempre el reviewer fijado por el modo: `$issue-delivery-cua-review` en `superset` o
   `$issue-delivery-browser-review` en `codex`, aunque el ajuste sea pequeño o los tests estén verdes.
6. Si la revisión detecta un fallo, volver a `$issue-delivery-implement` y repetir. Permitir como máximo cinco ciclos reparación-revisión.
7. Considerar obsoleto todo PASS UI si después se modifica código, configuración, datos sembrados o dependencias que puedan afectar el flujo. Repetir el mismo reviewer después del último cambio.
8. Actualizar capturas y evidencia publicada cuando exista PR.

Prohibir el handoff —incluido afirmar que está arreglado o pedir al usuario que lo verifique— hasta disponer de un PASS del reviewer del modo posterior al último cambio, con provider, SHA verificado y evidencia final. Si no está disponible o no puede verificar el flujo, bloquear y explicar el impedimento; no cambiar de modo o reviewer dentro del run.

## 1. Grill

1. Leer la issue, el repositorio y todos los `AGENTS.md` aplicables.
2. Invocar `$issue-delivery-grill` en esta conversación. Si ya existe spec/tickets, tratarlos como base y reconciliar los mismos bloques e IDs.
3. Si existe Figma, inspeccionarlo mediante su MCP. Si no es accesible, bloquear antes de implementar, salvo que el usuario entregue explícitamente un PNG o PDF como fallback.
4. Etiquetar cada user story con una superficie verificable: `UI`, `API-assembled` o `command-test`.
5. Obtener aprobación explícita del spec y del desglose.
6. Invocar, en orden, `$issue-delivery-spec-publisher` y `$issue-delivery-ticket-publisher`.
7. Informar inmediatamente todo ticket HITL: ID, título, justificación, acción humana, dependencias y momento aproximado de pausa. No usar HITL para tareas difíciles que un agente sí puede resolver.
8. Guardar snapshots aprobados dentro del run y completar:

   ```bash
   python3 <plugin-root>/scripts/issue-delivery <issue> checkpoint --phase grill \
     --artifact spec=<ruta> --artifact tickets=<ruta>
   ```

## 2. Implement

Procesar tickets en su orden aprobado. Antes de cada uno, entregar a `$issue-delivery-implement` el spec completo, el ticket, el SHA inicial del ticket y su validación declarada.

- Terminar primero los tickets AFK no bloqueados.
- Pausar justo antes de un HITL y pedir la acción mínima al usuario.
- Crear un commit descriptivo por ticket validado, sin push.
- Si ya está satisfecho, registrar `NO_OP` con evidencia y validación; no crear commits vacíos.
- Limitar a tres ciclos implementación-reparación por ticket. Bloquear si sigue rojo.
- Incluir commits preexistentes adoptados en la revisión del diff completo, sin reescribirlos.

Completar `implement` sólo con todos los tickets aceptados:

```bash
python3 <plugin-root>/scripts/issue-delivery <issue> checkpoint --phase implement
```

## 3. Refactor

Leer [refactor-review.md](references/refactor-review.md) completamente. Revisar el diff de
implementación contra los `AGENTS.md` aplicables y ejecutar cada gate de esa referencia.

- Allowlist: archivos cambiados por la implementación de este run y por commits preexistentes adoptados de la issue.
- Salir del allowlist sólo para corregir una violación concreta de `AGENTS.md`; registrar regla, archivo y razón.
- No hacer refactors especulativos.
- Repetir unit tests y typecheck afectados antes de cada commit de refactor.
- Guardar el recibo de revisión bajo el directorio ignorado del run. No completar la fase con
  criterios `FAIL` o sin evidencia.

Completar la fase con:

```bash
python3 <plugin-root>/scripts/issue-delivery <issue> checkpoint --phase refactor \
  --artifact refactor-review=<ruta-del-recibo>
```

## 4. Integrar la branch objetivo

Leer `pr_target_branch` desde `issue-delivery config`. Ejecutar `git fetch origin <target>` y
mergear `origin/<target>` antes de revisión manual, incluso si la rama nació desde otra base.
Resolver conflictos preservando spec y comportamiento de ambas ramas. Revalidar los proyectos
afectados.

No reparar fallos heredados del target. Atribuirlos reproduciendo el mismo fallo en su SHA
integrado exacto; si no es causado ni agravado por la branch, registrarlo como base failure.

Completar la fase con `python3 <plugin-root>/scripts/issue-delivery <issue> checkpoint --phase merge-target`.

## 5. Revisión manual

1. Inicializar un runtime persistente:

   ```bash
   python3 <plugin-root>/scripts/issue-delivery <issue> runtime-init
   ```

2. Levantar sólo las apps necesarias mediante `pnpm local-runtime` o `pnpm agent:*`, registrar sus PID y usar el runtime activo.
3. Ramificar exclusivamente por `developmentMode`:

   - `superset`: abrir el navegador dedicado mediante
     `python3 <plugin-root>/scripts/issue-delivery <issue> launch-browser --url <url-local>` e invocar `$issue-delivery-cua-review`.
   - `codex`: no ejecutar `launch-browser`; exigir la app de Codex y Browser disponible,
     e invocar `$issue-delivery-browser-review`.

4. Verificar las historias `UI` con el reviewer seleccionado y las demás mediante su superficie declarada.
5. Ningún reviewer edita código. Entregar findings a `$issue-delivery-implement`, reparar y repetir sólo las historias invalidadas con el mismo método.
6. Permitir como máximo cinco ciclos revisión-reparación.
7. Conservar únicamente capturas del estado final aceptado y producir el manifiesto con `provider` igual al método seleccionado.

El Browser de modo Codex no es elegible para otra aplicación, UI nativa, selector de archivos ni
upload. Si una historia lo exige, bloquear antes de probar; no degradar cobertura ni cambiar
automáticamente a Superset o Cua.

Completar la fase con `python3 <plugin-root>/scripts/issue-delivery <issue> checkpoint --phase manual-revision --artifact ui-manifest=<ruta>`.

## 6. PR

Crear el body dentro del run y ejecutar:

```bash
python3 <plugin-root>/scripts/issue-delivery <issue> ensure-pr --body-file <ruta>
python3 <plugin-root>/scripts/issue-delivery <issue> publish-evidence --manifest <ruta>
```

Publicar cada PNG en dos destinos distintos:

- Linear: copia privada para `## UI enhancements`.
- GitHub: copia en la evidence branch del perfil, fuera de la branch y diff de producto.

El comentario de la PR debe usar exclusivamente las rutas relativas devueltas por el motor. No
insertar URLs privadas de uploads de Linear: el proxy de imágenes de GitHub no puede renderizarlas.

Si un run antiguo ya publicó links rotos, repararlos sin repetir la validación funcional:

```bash
python3 <plugin-root>/scripts/issue-delivery <issue> repair-evidence-links
```

Este comando debe rehostear exactamente las PNG ya aceptadas y actualizar el comentario idempotente; no autoriza a sustituirlas por capturas distintas.

La PR debe ser normal, no draft, siempre hacia la branch target del perfil, sin asignar reviewers.
Reutilizar una PR abierta compatible. Una PR cerrada sin merge requiere decisión; una ya mergeada
exige issue/branch de seguimiento.

Completar la fase con `python3 <plugin-root>/scripts/issue-delivery <issue> checkpoint --phase pr-creation`.

## 7. Convergencia remota

Ejecutar hasta cinco rondas:

```bash
python3 <plugin-root>/scripts/issue-delivery <issue> wait-review
```

Cada ronda usa los tiempos y autores automatizados declarados por el perfil. En el perfil TurboShop,
esperar diez minutos de quietud desde el último cambio relevante, con un máximo de veinte minutos
por ronda y polling cada quince segundos. Procesar sólo problemas concretos de los bots configurados
y sólo la sección `BLOCKERS` del `blockerBot`; ignorar summaries, walkthroughs, sugerencias
opcionales y comentarios humanos durante el ciclo automático.

1. Invocar `$issue-delivery-blocker-triage` con el snapshot.
2. Si una solicitud contradice spec, ticket o decisión del Grill, registrar `NEEDS_USER_DECISION` y pausar.
3. Si el usuario mantiene el spec, guardar `SKIP` pegajoso. Si acepta al reviewer, actualizar primero spec y tickets en Linear y recién después editar.
4. Reparar cada `FIX` mediante `$issue-delivery-implement` y aplicar íntegramente la invariante de reparación y handoff. Usar un commit por causa raíz; agrupar sólo cambios íntimamente relacionados.
5. Validar antes de un único push por ronda.
6. Después de validar y pushear cada `FIX`, resolver su thread inline o reconocer su comentario
   general del `blockerBot` con:

   ```bash
   python3 <plugin-root>/scripts/issue-delivery <issue> acknowledge-blocker --comment-id <id> --decision FIX
   ```

7. Cuando todo feedback automatizado todavía pendiente tenga decisión `SKIP` —sin `FIX` ni `NEEDS_USER_DECISION` restantes— crear dentro del run:

   ```json
   {
     "skips": [
       {
         "commentId": 123,
         "title": "Título breve",
         "reason": "Motivo público, concreto y autocontenido."
       }
     ]
   }
   ```

   Publicar una explicación visible antes de cerrar o reconocer esos blockers:

   ```bash
   python3 <plugin-root>/scripts/issue-delivery <issue> publish-skip-summary --input <ruta-json>
   ```

   El comando consulta ambas superficies en vivo y exige que el archivo cubra exactamente todos los
   blockers automatizados pendientes. Crea o actualiza idempotentemente un único comentario general
   de la PR bajo la identidad GitHub configurada. No incluir datos privados del ledger.
8. Sólo después de publicar el resumen, resolver los threads inline con `SKIP` y reconocer cada
   comentario general del `blockerBot`:

   ```bash
   python3 <plugin-root>/scripts/issue-delivery <issue> acknowledge-blocker --comment-id <id> --decision SKIP
   ```

   `acknowledge-blocker` añade idempotentemente `+1` bajo la identidad configurada, registra el
   recibo y rechaza un `SKIP` sin resumen público.
9. Monitorear Actions. Reparar sólo fallos causados o agravados por la branch.
10. Ejecutar el reviewer seleccionado después del último cambio de la ronda, incluso si el FIX no estaba modelado como UI. Crear `REPAIR-<n>` cuando sea necesario, recalcular historias afectadas y volver a publicar evidencia invalidada.

Terminar como `completed_with_base_failures` cuando sólo queden fallos demostrablemente heredados. Si después de la quinta ronda aparece un FIX válido nuevo, bloquear.

Antes de aceptar la ronda final, ejecutar un refetch determinista de ambas superficies de
review:

```bash
python3 <plugin-root>/scripts/issue-delivery <issue> review-gate
python3 <plugin-root>/scripts/issue-delivery <issue> checkpoint --phase review-convergence
```

`review-gate` consulta en vivo los `reviewThreads` inline mediante GraphQL y los comentarios
generales de la PR. Debe bloquear mientras exista un thread automatizado sin resolver o un
comentario general accionable del `blockerBot` sin `+1` de la identidad GitHub configurada; los comentarios humanos
no participan del gate automático. El checkpoint de `review-convergence` vuelve a ejecutar el
mismo gate y no puede omitirse aunque el snapshot de una ronda esté incompleto o desactualizado.
También rechaza todo `SKIP` reconocido que no figure en un resumen público. Procesar todo
resultado pendiente con `$issue-delivery-blocker-triage` antes de reintentar.

El CLI detiene procesos propios y conserva worktree, rama, runtimes y estado.

## Review humano posterior y cleanup

Ignorar review humano salvo petición explícita. Para atenderlo, reanudar el mismo run en `review-convergence`, procesar únicamente feedback autorizado y aplicar íntegramente la invariante de reparación y handoff, además de los gates de spec, validación y evidencia.

Después del merge y sólo por petición explícita:

```bash
python3 <plugin-root>/scripts/issue-delivery <issue> cleanup
```

Eliminar recursos de todos los runtimes y el perfil del navegador. Preservar worktree y branch local. Rechazar cleanup antes del merge salvo `--force` explícito del usuario.

# Contrato operativo

## Fases y checkpoints

| Fase | Entrada obligatoria | Salida |
|---|---|---|
| `grill` | Issue, repo, AGENTS, diseños | Spec y tickets aprobados/publicados |
| `implement` | Spec y tickets | Commits locales o NO_OP por ticket |
| `refactor` | Diff de implementación | Cumplimiento AGENTS y gates de arquitectura validado |
| `merge-target` | Último `origin/<target>` persistido en el run | Merge resuelto y validado |
| `manual-revision` | Runtime y stories | Evidencia por story y findings cerrados, o espera manual sin completar la fase |
| `pr-creation` | Commits y evidencias | PR no draft hacia `<target>` |
| `review-convergence` | PR, bots y Actions | PR lista para reviewer humano |

Completar una fase con:

```bash
python3 <plugin-root>/scripts/issue-delivery <issue> checkpoint --phase <fase> --artifact <clave>=<ruta>
```

Todo artifact debe estar dentro del worktree. El motor rechaza paths externos.

## Objetivos de entrega

- `full` (default): ejecuta todas las fases, mantiene el gate obligatorio de Computer Use y sólo
  termina después de entregar un runtime final fresco y saludable.
- `manual-runtime`: ejecuta Grill, Implement, Refactor e integración de la branch target; luego
  reemplaza el Local Runtime, levanta las apps necesarias y termina en
  `status=awaiting_manual_review`, `currentPhase=manual-revision`. No ejecuta Computer Use,
  evidencia, PR ni convergencia.

El objetivo se fija al crear el run mediante `--handoff manual-runtime` y se persiste. Un run
existente no puede cambiarlo durante bootstrap. Desde `awaiting_manual_review`, `resume` conserva el
objetivo para correcciones y un nuevo recibo; `resume --full-delivery` realiza una transición
explícita e irreversible al flujo completo.

Todo handoff final usa la misma secuencia. `runtime-reset` exige un worktree limpio y comprometido,
detiene todos los procesos registrados del run, ejecuta cleanup para todos sus runtimes anteriores
y crea un Local Runtime nuevo. El estado pasa a `preparing_final_runtime`; el agente levanta
nuevamente sólo las apps necesarias sobre ese runtime. Luego `runtime-handoff` lee un JSON bajo el
directorio ignorado del run con al menos un servicio declarado por nombre, obtiene cada URL del
manifiesto —no acepta URLs arbitrarias—, verifica HTTP 2xx/3xx y exige el mismo HEAD fijado por el reset. Escribe
`validation/final-runtime-handoff.json` con SHA, runtime, URLs, puertos, procesos vivos, logs
declarados y comando de cleanup. Una URL meramente asignada pero no saludable no puede publicarse.

En `manual-runtime`, el handoff cambia a `awaiting_manual_review` y declara Computer Use y PR como
no ejecutados. En `full`, completar `review-convergence` detiene los procesos usados para revisar y
cambia a `awaiting_final_runtime_reset`; el handoff fresco posterior declara que Computer Use ya
ocurrió sobre el mismo SHA y recién entonces cambia a `completed_preserved`. En ambos casos se dejan
activos sólo los procesos del runtime final fresco para la prueba del usuario.

## Límites

- Reparación por ticket: 3 ciclos.
- Revisión UI-reparación: 5 ciclos.
- Review remoto: las esperas no tienen un máximo acumulado ni consumen presupuesto. TurboShop usa
  600 segundos de quietud, 1200 segundos de espera máxima por observación y polling cada 15
  segundos. Las reparaciones remotas se autorizan en bloques de 5 `headSha` nuevos con al menos un
  `FIX`.
- Routing por defecto: toda branch nueva nace desde `development` y toda PR apunta a `test`.
  Sólo una instrucción explícita del prompt permite otro base o target; ambos se persisten en el run.

Al alcanzar el límite de reparación por ticket o UI, detener procesos propios, conservar estado y
bloquear. Al agotar un bloque remoto, solicitar decisión del usuario; una aprobación explícita
agrega otro bloque en el mismo run.

## Presupuesto de reparación remota

`wait-review`, `review-gate`, `SKIP` y observaciones repetidas sobre el mismo SHA no cuentan como
reparaciones. Después de validar y pushear uno o más `FIX`, ejecutar `record-review-repair` una vez;
el comando exige que el `HEAD` local coincida con el head remoto de la PR y deduplica por SHA. Una
reparación de Actions causada o agravada por la branch también cuenta como `FIX` remoto.

Si `remainingRepairs` es cero y el triage encuentra un `FIX` válido, crear un request JSON con la
lista de fixes y ejecutar `request-review-extension`. El run pasa a `NEEDS_USER_DECISION`, detiene
procesos propios y conserva todos sus recursos. Mostrar al usuario los fixes pendientes y el
presupuesto consumido. `resume` no puede atravesar este gate.

Sólo ante aprobación explícita ejecutar `approve-review-extension`. El comando suma
`repairBatchSize`, registra la aprobación y reanuda el mismo run. Si el usuario no aprueba, mantener
el bloqueo. No crear una issue, branch o PR de seguimiento sólo por consumir el bloque.

## Gate obligatorio de reparación

Toda petición de ajuste/corrección y todo reporte de comportamiento roto abre un ciclo de reparación, sin importar la fase actual.

El recibo de verificación debe registrar:

- Provider `cua-driver`, `codex-browser` o `playwright-chrome`, según el modo persistido.
- Texto o ID del reporte.
- Escenario `REPAIR-<n>` o historias afectadas.
- SHA exacto verificado.
- Runtime ID.
- Resultado `PASS`.
- Timestamp y paths de evidencia final.

Un cambio posterior que pueda afectar el flujo invalida el recibo. En `full`, no hacer handoff ni
pedir verificación al usuario sin un recibo UI válido para el HEAD actual y emitido por el reviewer
seleccionado. Si ese método no puede probar el escenario, el estado correcto es `blocked`, no
`completed`; no cambiar de provider silenciosamente. En `manual-runtime`, esta exigencia se
reemplaza únicamente por el recibo `final-runtime-handoff.json`: éste demuestra salud técnica del
runtime fresco, no aceptación UI, y el handoff debe declararlo sin ambigüedad.

## Decisiones de review

- `FIX`: problema válido, material, causado o agravado por la branch y compatible con el spec.
- `SKIP`: inválido, ya cubierto, heredado, insignificante, especulativo o previamente descartado.
- `NEEDS_USER_DECISION`: el cambio solicitado contradice un acuerdo aprobado. Nunca degradarlo a FIX o SKIP sin decisión.

Los SKIP son pegajosos por causa raíz. Guardarlos mediante `$issue-delivery-blocker-triage` dentro de `.local-runtime/issue-delivery-orchestrator/<run-id>/blocker-triage/`, incluyendo un motivo público breve y sin información sensible.

Después de cerrar cada comentario general de los `blockerBots` con `FIX` validado/pusheado, ejecutar
`acknowledge-blocker --decision FIX`. El comando valida autor, PR y presencia de blockers reales,
añade `+1` idempotente como la identidad GitHub configurada y persiste `reviewAcknowledgements`.

Cuando todos los blockers automatizados restantes sean `SKIP`, publicar primero un único resumen visible mediante `publish-skip-summary --input <ruta-json>`. El JSON debe contener `skips`, con `commentId`, `title` y `reason` por decisión. El comando:

1. vuelve a consultar comentarios generales y `reviewThreads`;
2. exige que los IDs coincidan exactamente con todo feedback automatizado pendiente;
3. publica o actualiza idempotentemente un comentario general de la PR;
4. persiste el recibo bajo `review/skip-summary.json`.

Sólo después se pueden resolver los threads inline con `SKIP` y ejecutar `acknowledge-blocker --decision SKIP` para comentarios generales. El reconocimiento se rechaza si ese ID no aparece en el resumen público. No usar estos comandos para `Ninguno`, sugerencias ni decisiones pendientes.

Antes de completar `review-convergence`, ejecutar `review-gate`. El gate vuelve a consultar
GitHub en vivo y exige simultáneamente:

- cero `reviewThreads` inline no resueltos que contengan comentarios de bots configurados;
- cero comentarios generales accionables de los `blockerBots` sin reacción `+1` de la identidad
  GitHub configurada;
- cero reconocimientos `SKIP` que no estén incluidos en el resumen público.

Los comentarios humanos quedan fuera del ciclo automático. El propio
`checkpoint --phase review-convergence` repite este gate, guarda el recibo en
`review/final-gate.json` y rechaza el cierre si cualquiera de las dos superficies tiene feedback
pendiente. Un snapshot de ronda, por sí solo, nunca autoriza la finalización.

## Evidencia

El manifiesto de screenshots debe ser JSON:

```json
{
  "evidenceVersion": 2,
  "verification": {
    "status": "PASS",
    "provider": "cua-driver",
    "verifiedCommit": "<sha>",
    "runtimeId": "<runtime-id>",
    "verifiedAt": "<ISO-8601>",
    "scenarioIds": ["US-1"]
  },
  "screenshots": [
    {
      "storyId": "US-1",
      "title": "Resultado observable",
      "caption": "Qué demuestra la captura",
      "path": ".local-runtime/issue-delivery-orchestrator/<run-id>/validation/ui/US-1.png",
      "callouts": [
        {
          "kind": "highlight",
          "caption": "Elemento nuevo verificado",
          "bounds": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.1}
        }
      ]
    }
  ]
}
```

Leer [evidence-annotations.md](evidence-annotations.md). Incluir sólo PNG originales finales, sin
secretos ni datos sensibles. Preparar una copia anotada determinista y conservar ambas. Rechazar
como obsoleto un manifiesto cuyo `verifiedCommit` no sea el HEAD final.

`publish-evidence` debe:

1. Subir copias anotada y original a Linear y actualizar `## UI enhancements`.
2. Subir ambas copias a `git.evidenceBranch` mediante Git Data API, sin tocar la branch de la issue.
3. Usar en el comentario idempotente sólo los paths relativos devueltos por el motor.
4. Rechazar cualquier body de PR que dependa de `uploads.linear.app`.

Las evidencias de GitHub permanecen restringidas por los permisos del repositorio. `repair-evidence-links` migra recibos antiguos usando los mismos archivos locales, sin reinterpretar su resultado UI.

## Persistencia

- Todo run nuevo exige un worktree adoptable. Un `--mode` explícito tiene prioridad. Sin él, el CLI
  detecta primero Conductor Cloud mediante `CONDUCTOR_IS_LOCAL=0`, `CONDUCTOR_API_URL` y un
  `CONDUCTOR_WORKSPACE_PATH` o `CONDUCTOR_ROOT_PATH` coincidente; luego detecta Codex o Superset
  mediante `SUPERSET_WORKSPACE_PATH`, raíces configuradas o componentes inequívocos de la ruta.
  Sin coincidencias selecciona Vanilla con
  `modeSource=vanilla-fallback`. Una detección contradictoria bloquea. El modo no cambia después de
  crear el estado.
- El CLI usa `--base development --target test` por defecto, persiste `base` y `target`, y los
  publica en `status`. El skill debe pasar ambos explícitamente después de resolver el prompt. No
  usar la default branch remota, el perfil ni la branch actual como fallback. Los runs existentes
  conservan su routing persistido; un estado legacy sin `target` conserva el target de su perfil.
- Modo `codex`: la app crea primero un worktree del chat, normalmente detached; el CLI lo adopta,
  conecta la rama local/remota de Linear o crea la rama desde `origin/<base>`, y fija
  `reviewer.method=codex-browser`. Fijar el chat y no archivarlo ni hacer Handoff a Local antes del
  merge y cleanup; el estado ignorado del run permanece en ese worktree.
- Modo `superset`: Superset crea primero el worktree en la rama de Linear; el CLI lo adopta mediante
  `--worktree` o `SUPERSET_WORKSPACE_PATH` y fija `reviewer.method=cua-driver`.
- Modo `vanilla`: el usuario o su herramienta crea/prepara el checkout o worktree y ejecuta su
  setup local antes del loop. El CLI lo adopta mediante `--worktree`, permite partir desde la rama
  base, un detached HEAD seguro o la rama de la issue, conecta la rama de Linear y fija
  `reviewer.method=cua-driver`. Si el modo fue inferido, bloquear antes de descartar cambios
  trackeados o archivos no ignorados; exigir un checkout limpio o selección explícita de Vanilla.
- Modo `conductor-cloud`: Conductor crea primero el workspace cloud y ejecuta su setup. El CLI adopta
  exactamente el path declarado por sus variables oficiales, permite partir desde la branch de la
  issue o una branch temporal cuyo HEAD esté íntegramente preservado por la branch de la issue o
  `origin/<base>`, conecta la branch de Linear y fija `reviewer.method=playwright-chrome`. Nunca crea
  un workspace o worktree adicional.
- El orquestador nunca crea worktrees ni delega el run a un thread que solicite otro. Prohibir
  `create_thread` con entorno worktree, `git worktree add` y mecanismos equivalentes. Si el actual
  no puede adoptarse, bloquear y pedir al usuario que abra manualmente otro para que la superficie
  ejecute su setup local.
- La adopción valida mismo repositorio y `.local-runtime` ignorado. Superset exige branch exacta de
  Linear o prefijo truncado con el mismo ID. Codex sólo permite detached HEAD o esa misma branch.
  Vanilla permite además partir desde la branch base declarada; Conductor Cloud admite una branch
  temporal sólo bajo el gate de historia preservada descrito arriba. Antes de iniciar un run nuevo,
  descartar cambios trackeados y archivos no trackeados no ignorados; preservar `.env`,
  dependencias, `.local-runtime` y cualquier otro archivo ignorado. Registrar el snapshot previo en
  `discardedInitialStatus` y exigir un status limpio después. No ejecutar esta limpieza al reanudar.
- Browser sólo opera dentro de un run modo Codex abierto en la app. Cua opera en modo Superset o
  Vanilla. En Conductor Cloud, Playwright headless con el Chrome del workspace es el reviewer
  principal y debe revisar visualmente sus PNG; no declara asistencia ni depende de Browser
  Preview. En los otros modos, Playwright headless puede asistir exclusivamente una story con brecha demostrada de
  `file-upload` o `hover`, sobre el mismo SHA/runtime y con recibo bajo el run; el provider continúa
  siendo el reviewer principal. No cambiar provider o modo silenciosamente. Leer
  [headless-assistance.md](headless-assistance.md) y mantener compatibilidad con
  `uploadAssistance` v1 y recibos v2 de Codex Browser.
- `adoptedHead` y `adoptedStatus` fijan el baseline limpio posterior a la adopción;
  `discardedInitialStatus` conserva la auditoría de lo eliminado.
- `python3 <plugin-root>/scripts/issue-delivery <issue>` descubre runs actuales en todos los worktrees Git
  registrados, y reanuda el más reciente preservado.
- `ensure-pr` es la única vía autorizada para crear la PR. Usa `state.target` como `gh pr create
  --base`, filtra PRs existentes por ese mismo target y rechaza cualquier head/base distinto. No
  ejecutar `gh pr create` directamente ni permitir que GitHub elija `main` por omisión.
- Un run existente nunca cambia de worktree por una actualización del orquestador.
- Después de iniciar o reanudar, anunciar inmediatamente en el chat `modeDecision.mode`,
  `modeDecision.source`, `modeDecision.reviewer` y `modeDecision.worktree`. No continuar al Grill
  sin ese anuncio. Para `vanilla-fallback`, explicar que no se detectaron señales Codex, Superset o
  Conductor Cloud.
- `--new-run` crea otro sólo si la branch no está asociada a un worktree.
- `runtime-init --fresh` sólo reemplaza el binding activo; el cierre normal debe usar
  `runtime-reset` para detener procesos, limpiar recursos de los runtimes anteriores y dejar recibo
  auditable.
- `runtime-handoff` preserva los procesos del runtime final fresco. El usuario decide cuándo
  ejecutar cleanup después de su revisión y del merge.
- Al finalizar el loop se detienen los procesos previos, se levanta una instancia fresca sobre el
  HEAD final y se dejan activas sólo sus apps declaradas.
- `cleanup` posterior al merge limpia todos los runtimes registrados y el perfil del navegador, no el worktree ni la branch.

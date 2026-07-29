# Contrato operativo

## Fases y checkpoints

| Fase | Entrada obligatoria | Salida |
|---|---|---|
| `grill` | Issue, repo, AGENTS, diseños | Spec y tickets aprobados/publicados |
| `implement` | Spec y tickets | Commits locales o NO_OP por ticket |
| `refactor` | Diff de implementación | Cumplimiento AGENTS y gates de arquitectura validado |
| `merge-target` | Último `origin/<target>` del perfil | Merge resuelto y validado |
| `manual-revision` | Runtime y stories | Evidencia por story y findings cerrados |
| `pr-creation` | Commits y evidencias | PR no draft hacia `<target>` |
| `review-convergence` | PR, bots y Actions | PR lista para reviewer humano |

Completar una fase con:

```bash
python3 <plugin-root>/scripts/issue-delivery <issue> checkpoint --phase <fase> --artifact <clave>=<ruta>
```

Todo artifact debe estar dentro del worktree. El motor rechaza paths externos.

## Límites

- Reparación por ticket: 3 ciclos.
- Revisión UI-reparación: 5 ciclos.
- Review remoto: valores del perfil activo. TurboShop usa 600 segundos de quietud, 1200 segundos
  de espera máxima por ronda y polling cada 15 segundos.
- Target de PR: siempre `git.prTarget` del perfil activo.

Al alcanzar un límite, detener procesos propios, conservar estado y bloquear.

## Gate obligatorio de reparación

Toda petición de ajuste/corrección y todo reporte de comportamiento roto abre un ciclo de reparación, sin importar la fase actual.

El recibo de verificación debe registrar:

- Provider `cua-driver` o `codex-browser`.
- Texto o ID del reporte.
- Escenario `REPAIR-<n>` o historias afectadas.
- SHA exacto verificado.
- Runtime ID.
- Resultado `PASS`.
- Timestamp y paths de evidencia final.

Un cambio posterior que pueda afectar el flujo invalida el recibo. No hacer handoff ni pedir verificación al usuario sin un recibo UI válido para el HEAD actual y emitido por el reviewer seleccionado. Si ese método no puede probar el escenario, el estado correcto es `blocked`, no `completed`; no cambiar de provider silenciosamente.

## Decisiones de review

- `FIX`: problema válido, material, causado o agravado por la branch y compatible con el spec.
- `SKIP`: inválido, ya cubierto, heredado, insignificante, especulativo o previamente descartado.
- `NEEDS_USER_DECISION`: el cambio solicitado contradice un acuerdo aprobado. Nunca degradarlo a FIX o SKIP sin decisión.

Los SKIP son pegajosos por causa raíz. Guardarlos mediante `$issue-delivery-blocker-triage` dentro de `.local-runtime/issue-delivery-orchestrator/<run-id>/blocker-triage/`, incluyendo un motivo público breve y sin información sensible.

Después de cerrar cada comentario general del `blockerBot` con `FIX` validado/pusheado, ejecutar
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
- cero comentarios generales accionables del `blockerBot` sin reacción `+1` de la identidad
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
      "path": ".local-runtime/issue-delivery-orchestrator/<run-id>/validation/ui/US-1.png"
    }
  ]
}
```

Incluir sólo PNG finales, sin secretos ni datos sensibles. Rechazar como obsoleto un manifiesto cuyo `verifiedCommit` no sea el HEAD final.

`publish-evidence` debe:

1. Subir una copia privada a Linear y actualizar `## UI enhancements`.
2. Subir una copia GitHub a `git.evidenceBranch` mediante Git Data API, sin tocar la branch de la issue.
3. Usar en el comentario idempotente sólo los paths relativos devueltos por el motor.
4. Rechazar cualquier body de PR que dependa de `uploads.linear.app`.

Las evidencias de GitHub permanecen restringidas por los permisos del repositorio. `repair-evidence-links` migra recibos antiguos usando los mismos archivos locales, sin reinterpretar su resultado UI.

## Persistencia

- Todo run nuevo exige `--worktree`. `--mode codex|superset` es un override opcional: sin él, el
  CLI detecta el modo mediante `SUPERSET_WORKSPACE_PATH`, las raíces configuradas en
  `ISSUE_DELIVERY_CODEX_WORKTREE_ROOTS`/`ISSUE_DELIVERY_SUPERSET_WORKTREE_ROOTS`, o componentes
  inequívocos de la ruta. No existe un default; una detección vacía o contradictoria bloquea. El
  modo no cambia después de crear el estado.
- Modo `codex`: la app crea primero un worktree del chat, normalmente detached; el CLI lo adopta,
  conecta la rama local/remota de Linear o crea la rama desde `origin/<base>`, y fija
  `reviewer.method=codex-browser`. Fijar el chat y no archivarlo ni hacer Handoff a Local antes del
  merge y cleanup; el estado ignorado del run permanece en ese worktree.
- Modo `superset`: Superset crea primero el worktree en la rama de Linear; el CLI lo adopta mediante
  `--worktree` o `SUPERSET_WORKSPACE_PATH` y fija `reviewer.method=cua-driver`.
- La adopción valida mismo repositorio y `.local-runtime` ignorado. Superset exige branch exacta de
  Linear o prefijo truncado con el mismo ID. Codex sólo permite detached HEAD o esa misma branch y
  no abandona commits ni mezcla cambios locales con otra base.
- Browser sólo opera dentro de un run modo Codex abierto en la app. Cua sólo opera dentro de modo
  Superset. No cambiar provider o modo silenciosamente.
- `adoptedHead` y `adoptedStatus` fijan el baseline previo al loop. Preservar y excluir del alcance todo cambio preexistente salvo adopción explícita posterior.
- `python3 <plugin-root>/scripts/issue-delivery <issue>` descubre runs actuales en todos los worktrees Git
  registrados, y reanuda el más reciente preservado.
- Un run existente nunca cambia de worktree por una actualización del orquestador.
- `--new-run` crea otro sólo si la branch no está asociada a un worktree.
- `runtime-init --fresh` permite registrar otro runtime sin limpiar los anteriores.
- Al finalizar el loop sólo se detienen procesos.
- `cleanup` posterior al merge limpia todos los runtimes registrados y el perfil del navegador, no el worktree ni la branch.

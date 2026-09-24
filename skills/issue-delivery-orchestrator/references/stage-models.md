# Modelos opcionales por etapa

El principal conserva el control del run, las aprobaciones y los comandos del motor. La selección
se guarda en `state.stageModels`; no cambia el modelo del chat ni configura modelos de bots
externos. No elegir modelos por iniciativa propia. Convertir únicamente elecciones explícitas
del usuario en flags `--stage-model STAGE=MODEL` antes del subcomando:

```bash
python3 <plugin-root>/scripts/issue-delivery <issue> --worktree <ruta> \
  --stage-model grill=<modelo> --stage-model implement=<modelo> \
  --stage-model local-review=<modelo>
```

Para modificar un run existente o volver a herencia:

```bash
python3 <plugin-root>/scripts/issue-delivery <issue> \
  --stage-model implement=<modelo> --stage-model local-review=inherit stage-models
```

Etapas válidas: `grill`, `implement`, `refactor`, `merge-target`, `local-review`,
`manual-revision`, `pr-creation`, `review-convergence`. Las omitidas conservan su selección al
reanudar; `inherit` elimina la selección. Los runs legacy sin configuración heredan del principal.
Un cambio aplica a las siguientes invocaciones, no a agentes ya activos ni a fases completadas.
No crear un nuevo run para cambiar modelos.

## Ejecución

Antes de cada etapa, usar `stageExecution` del estado o consultar una vez
`stage-plan --phase <etapa>`. En reparaciones, resolver cada trabajo por su etapa real: implementar
con `implement`, revisar arquitectura con `refactor`, revisar código con `local-review` y verificar
UI con `manual-revision`, aunque `currentPhase` sea `review-convergence`.

- `executor=principal-session`: ejecutar en esta conversación como hasta ahora.
- `executor=native-subagent`: el principal lanza directamente un subagente nativo con
  `spawnOptions`. En esta superficie corresponde a `collaboration.spawn_agent`, con
  `fork_turns="none"` y el `model` explícito cuando exista. No usar `fork_turns="all"` para un
  override. Sin modelo explícito, heredar del principal; no del último implementador. El nivel de
  razonamiento sigue el comportamiento del host; este selector no lo modifica.
- Anunciar etapa, modelo explícito o herencia y executor antes de empezar. Comprobar que el modelo
  solicitado esté disponible en la herramienta nativa; un modelo desconocido, un override ignorado
  o herramientas requeridas inaccesibles deben producir `BLOCKED`, sin fallback silencioso.
  El CLI valida sintaxis y etapas, no la disponibilidad de modelos del proveedor.
- No crear sesiones Conductor, worktrees, procesos `codex exec` ni modificar configuración global.
  No lanzar agentes de prueba para descubrir modelos. Todos los workers nacen del principal para
  mantener la herencia y la atribución de tokens.
- Un worker ejecuta sólo el trabajo asignado y devuelve resultado, SHA, validaciones, artifacts y
  bloqueos. No se vuelve a delegar a sí mismo por leer estas instrucciones, no lanza la etapa
  siguiente, no aprueba acuerdos ni ejecuta checkpoints, bootstrap, resume o handoff. El principal
  conserva esos comandos y sigue el orden y gates existentes. No hay dos agentes editando el
  worktree a la vez.

## Paquete de contexto

Entregar rutas absolutas del worktree, run y skill/referencia aplicable, issue, spec completo,
ticket o finding, criterios de aceptación, SHA inicial, base/target y artifacts relevantes.
Exigir lectura de AGENTS, CLAUDE, ADRs y documentación aplicable. Incluir decisiones aprobadas que
no estén todavía en el spec; reconciliarlas antes de implementar. No transferir el historial del
chat ni resúmenes que sustituyan el spec. Para `local-review`, respetar su paquete independiente
sin conclusiones de revisores anteriores que condicionen el dictamen.

| Etapa | Trabajo delegado cuando tiene override |
|---|---|
| Grill | Investigar y formular preguntas/spec/tickets; devolver las preguntas al principal, que las presenta al usuario y transmite las respuestas explícitas al mismo worker. Sólo el usuario aprueba; el principal publica los bloques aprobados. No abrir otro Grill interactivo. |
| Implement | Un ticket o causa raíz por encargo, con spec completo, validación y commit. Devolver al principal antes de Local Review, revisión UI o handoff. |
| Refactor | Aplicar los gates y allowlist existentes, validar cambios y devolver hallazgos/recibo. |
| Merge target | Integrar el target persistido y validar conflictos; devolver SHA y resultados. |
| Local Review | Revisar en sólo lectura con contexto nuevo, incluso sin override; devolver el informe para que el principal guarde el recibo. |
| Manual revision | Usar el reviewer fijado por el modo, sus herramientas y runtime; no editar código. Si esas herramientas no están disponibles en el worker, bloquear. |
| PR creation | Preparar título/body y artifacts; el principal ejecuta ensure-pr y publicación con las identidades y gates existentes. |
| Review convergence | Analizar el snapshot de bots/Actions según blocker-triage. Devolver FIX/SKIP/NEEDS_USER_DECISION; el principal aplica presupuesto, publicación y reparación usando los modelos de cada etapa. |

No reutilizar el worker de otra etapa para ahorrar lanzamientos: su modelo/contexto puede ser
distinto. Dentro de Grill se puede continuar el mismo worker para preguntas; en Local Review,
cada nueva revisión usa contexto nuevo. Esta configuración no autoriza a omitir validaciones,
revisión independiente o revisión UI.

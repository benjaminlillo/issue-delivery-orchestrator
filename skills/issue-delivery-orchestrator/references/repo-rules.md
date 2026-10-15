# Reglas del repositorio

Toda etapa que planifique, escriba, revise o publique aplica las reglas del repositorio del run,
leídas desde su worktree y no desde la memoria del plugin.

## Capas

Seguir la sección "Rules and memory" del `AGENTS.md` raíz. En TurboShop define estas capas, de la
más general a la más específica:

1. `AGENTS.md` raíz, siempre.
2. `CODING_STANDARDS.md`, antes de planificar o escribir código.
3. Los `docs/rules/*.md` del índice de `AGENTS.md` cuyo tema coincida con la tarea.
4. `apps/<app>/AGENTS.md` de cada app tocada. Sus reglas aplican sólo a esa app.
5. Los comentarios inline del símbolo que se usa.

Si el `AGENTS.md` raíz cambia esas capas, manda el repositorio. Si no tiene esa sección, leer todos
los `AGENTS.md` aplicables. Los `CLAUDE.md` que sólo importan `AGENTS.md` no agregan reglas.
`REVIEW.md` es el checklist de revisión que aplica `review-pr`. ADRs aceptados, `CONTEXT.md` y
context maps siguen siendo fuentes de dominio y arquitectura.

Las tarjetas de `docs/lessons/` no son reglas. Nunca aplicarlas, citarlas como fundamento ni
cargarlas como contexto. No editar archivos de reglas: si una decisión parece una regla general,
registrarla como señal de lección.

Un spec o ticket no puede contradecir en silencio una regla aplicable. Si lo hace, la etapa que lo
detecta lo trata como `NEEDS_USER_DECISION`.

## Commits y textos

- Los commits siguen `docs/rules/git.md`: Conventional Commits con resumen en inglés.
- La descripción de la PR, el spec y los comentarios de Linear, los motivos de `SKIP` y los
  mensajes al usuario siguen la sección "Writing style" del `AGENTS.md` raíz.

## Señales de lección

Durante el run no se escriben tarjetas ni commits de lecciones. Agregar una línea con evidencia a
`.local-runtime/issue-delivery-orchestrator/<run-id>/lessons/signals.md` cuando:

- el usuario corrige, rechaza o rehace algo del run, o responde un `NEEDS_USER_DECISION`;
- `review-pr` deja un hallazgo `Corregir` que luego se repara;
- la convergencia remota repara un blocker con `FIX`;
- un enfoque falla y se sabe por qué, o una suposición errónea obliga a rehacer trabajo.

Cada línea indica qué pasó, qué se hizo distinto y la evidencia (`archivo:línea`, SHA, comentario o
lo que dijo el usuario). No duplicar señales ni guardar secretos.

## Lecciones al pasar la PR a ready

El run deja la PR en draft. Cuando el usuario pida pasarla a ready, o dé por terminada la tarea en
`manual-runtime`:

1. Ejecutar la skill `lessons-learned` del repositorio en el worktree del run, entregándole
   `lessons/signals.md` junto con la conversación como fuente de señales.
2. La skill commitea sólo tarjetas de `docs/lessons/` y hace push. El motor ignora esos commits al
   comparar el código entregado, así que el handoff, `runtime-restore` y el escritorio siguen
   válidos.
3. Recién entonces ejecutar `gh pr ready`. No correr `lessons-learned` sobre una PR draft ni en
   medio del run.

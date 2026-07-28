---
name: issue-delivery-blocker-triage
description: "Analizar comentarios o blockers de code review de la PR asociada a la branch Git actual. Usar para contrastar feedback con código, spec y acuerdos, estimar impacto y complejidad, aplicar YAGNI, decidir FIX, SKIP o NEEDS_USER_DECISION cuando el reviewer contradice un acuerdo aprobado, y conservar decisiones entre rondas dentro del worktree."
---

# Blocker Triage

Evaluar feedback de review sin modificar código, responder comentarios ni resolver threads. Entregar una decisión argumentada por blocker, incluir un motivo público breve para cada `SKIP` y guardar el historial local de la PR para mantener criterios entre rondas. La publicación posterior corresponde al orquestador.

## Preparar el contexto

1. Identificar el repositorio, la branch actual y la PR correspondiente. Usar la integración de GitHub disponible o `gh` sólo para lecturas. Si no existe una PR accesible, continuar con la branch y los comentarios entregados por el usuario.
2. Tratar los comentarios entregados por el usuario como la lista de blockers a evaluar. Si no entrega comentarios, recuperar los blockers o threads pendientes de la PR.
3. Leer todos los `AGENTS.md` aplicables, el diff completo de la PR y los archivos, tests y documentación relevantes para cada comentario.
4. Buscar acuerdos explícitos en la conversación actual, descripción de la PR, issue enlazada, PRD, ADR y documentación del repositorio. No inferir un acuerdo por ausencia de discusión.
5. Delimitar el alcance `Now`: comportamientos requeridos por la PR, issue, spec o acuerdos vigentes, más regresiones y riesgos materiales introducidos o agravados por la PR. No convertir posibilidades futuras en requisitos actuales.
6. Separar un comentario en varios blockers sólo cuando contenga problemas independientes que puedan recibir decisiones distintas. Deduplicar comentarios que describan la misma causa raíz.

No asumir que el reviewer tiene razón. Reproducir o demostrar el problema desde el código cuando sea razonable. No ampliar el alcance hacia problemas preexistentes no causados por la PR, salvo que el cambio los agrave o que exista riesgo material de seguridad, pérdida de datos o corrupción.

## Cargar el historial de decisiones

Antes de evaluar, obtener el worktree actual con `git rev-parse --show-toplevel`. Guardar el ledger local en:

```text
<worktree>/.local-runtime/issue-delivery-orchestrator/<run-id>/blocker-triage/pr-<numero-pr>.md
```

Si no existe número de PR, usar `branch-<branch-normalizada>.md`, reemplazando `/` y caracteres no alfanuméricos por `-`. Crear el directorio y el archivo cuando sean necesarios. Mantenerlos en el estado ignorado del worktree; nunca agregarlos al commit ni publicarlos en la PR.

Registrar para cada decisión:

- URL o ID del thread/comentario, cuando exista.
- Descripción semántica breve de la causa raíz.
- Paths y símbolos afectados.
- Decisión `FIX` o `SKIP`, impacto, complejidad y fundamento.
- Para `SKIP`, un motivo público autocontenido, respetuoso y sin información sensible.
- Evidencia de acuerdos previos y ronda/reviewer, cuando estén disponibles.

Al comenzar una ronda, leer el ledger completo. Considerar que un blocker es el mismo si coincide su thread/ID o si plantea la misma causa raíz y el mismo cambio esperado sobre el mismo flujo, aunque esté reformulado o movido a otra línea.

Una decisión previa `SKIP` es pegajosa: volver a marcar `SKIP` y citar la decisión anterior. No reabrirla por insistencia, reformulación o nueva ronda del reviewer. Reconsiderarla únicamente si el usuario lo pide explícitamente. Tratar como blocker nuevo una observación con una causa raíz o efecto material realmente distinto.

Una decisión previa del usuario ante `NEEDS_USER_DECISION` también es pegajosa. Si mantiene el spec, registrar `SKIP` con esa decisión. Si acepta el cambio del reviewer, exigir que el spec y los tickets canónicos se reconcilien antes de convertirlo en `FIX`.

## Evaluar cada blocker

Determinar, con evidencia, estas dimensiones:

- **Validez:** confirmar si el comportamiento descrito ocurre y si lo introduce o agrava la PR.
- **Efecto práctico:** describir quién o qué resulta afectado, en qué escenario, con qué frecuencia probable y qué resultado observable produce. Evitar impactos puramente abstractos.
- **Tamaño del problema:** clasificarlo como crítico, alto, medio o bajo considerando corrección, seguridad, datos, confiabilidad, rendimiento, UX y mantenibilidad real.
- **Complejidad de solución:** clasificarla como baja, media o alta a partir del cambio mínimo viable, tests requeridos, riesgo de regresión y superficie afectada.
- **Alcance y acuerdos:** indicar si el comportamiento fue requerido, aceptado o descartado explícitamente. Citar la fuente concreta; no inventar intención.
- **YAGNI:** determinar si el cambio solicitado es necesario para el alcance `Now` o si añade capacidad, generalización, abstracción, compatibilidad o protección para un escenario futuro sin evidencia actual. Exigir un requisito vigente o un efecto práctico material para justificar superficie adicional.

Estimar la solución mínima sólo hasta el detalle necesario para valorar complejidad. No implementarla durante el triage.

Decidir `FIX` cuando el problema sea válido, alcanzable y material para el alcance `Now`; cuando viole un requisito o acuerdo explícito; o cuando una corrección pequeña y segura evite un impacto relevante. Priorizar siempre seguridad, pérdida/corrupción de datos y regresiones provocadas por la PR. No ampliar la solución más allá del cambio mínimo necesario.

Decidir `SKIP` cuando el problema sea inexistente, ya esté cubierto, no sea causado ni agravado por la PR, tenga efecto práctico insignificante frente al costo o riesgo de solucionarlo, contradiga un acuerdo explícito vigente, solicite capacidad especulativa fuera del alcance `Now` sin evidencia material, o ya tenga un `SKIP` en el ledger. No usar YAGNI ni “fuera de alcance” para ocultar una regresión material de la PR, un requisito vigente o un riesgo real de seguridad o datos.

Decidir `NEEDS_USER_DECISION` en vez de `SKIP` cuando el reviewer automatizado solicite un cambio que contradiga explícitamente un spec, ticket o decisión de Grill vigente y todavía no exista una decisión del usuario para ese conflicto. Citar ambos lados y formular la elección mínima necesaria. No editar ni sugerir que el loop continúe hasta resolverla.

Si después de una inspección razonable no es posible sustentar el riesgo, decidir `SKIP` con la incertidumbre declarada.

## Entregar el resultado

Comenzar con un resumen de cantidades `FIX`, `SKIP` y `NEEDS_USER_DECISION`. Para cada blocker, usar esta estructura:

```markdown
### Blocker N — <título breve>

- Comentario: <referencia o paráfrasis fiel>
- Qué sucede: <mecanismo concreto en el código>
- Efectos prácticos: <escenarios y consecuencias observables>
- Evaluación: validez; tamaño del problema; complejidad de solución; alcance/acuerdos; YAGNI
- Decisión: FIX | SKIP | NEEDS_USER_DECISION
- Fundamento: <por qué el balance conduce a esa decisión>
- Motivo público: <una frase breve para publicar en la PR; obligatorio sólo para SKIP>
- Evidencia: <archivos, tests, PRD/ADR/issue o decisión previa>
```

En una nueva ronda, indicar explícitamente cuáles `SKIP` provienen de decisiones anteriores. Para los `FIX`, ordenar al final por prioridad cuando haya más de uno. Para `NEEDS_USER_DECISION`, terminar con una única pregunta concreta al usuario. Ser concreto y permitir que el lector entienda la decisión sin abrir el código, manteniendo referencias verificables.

Después de completar el análisis y antes de responder, actualizar el ledger con los blockers nuevos o la nueva aparición de blockers existentes. Conservar el razonamiento histórico; no borrar entradas anteriores ni cambiar un `SKIP` sin instrucción explícita del usuario.

Cuando todos los blockers restantes de una ronda sean `SKIP`, entregar además los IDs, títulos y motivos públicos en una lista apta para el input de `publish-skip-summary`. No publicar directamente: el orquestador debe comprobar que no quede feedback automatizado con otra decisión antes de comentar.

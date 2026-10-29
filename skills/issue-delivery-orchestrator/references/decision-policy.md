# Política de decisiones

Un run pierde su propósito si se detiene por preguntas que el grill pudo resolver o que el agente
puede deducir. Esta política aplica a todas las etapas posteriores al grill: Implement, Refactor,
`review-pr`, revisión UI, triage de blockers y reparaciones. Los workers la reciben en su paquete.

## Antes de preguntar, deducir

Ante una duda, buscar la respuesta en este orden y decidir con la primera fuente que la determine:

1. El spec aprobado, incluida su tabla `Pre-resolved questions`, los tickets y las decisiones del
   grill.
2. Lo que la issue pide de forma literal, con el menor alcance posible (YAGNI). Lo no
   imprescindible va a `Deferred`.
3. Las reglas del repositorio ([repo-rules.md](repo-rules.md)) y los patrones existentes de la app.
   Una regla del repositorio gana sobre el spec: corregir el spec antes de implementar.
4. Lo más consistente para el usuario final: que el cambio se comporte como los flujos parecidos
   que ya usa en la app. Mismos pasos, textos, estados vacíos, mensajes de error, confirmaciones,
   ubicación de acciones y navegación. Si dos opciones cumplen la issue, elegir la que el usuario
   ya conoce de otra pantalla y nombrarla en el fundamento.
5. El comportamiento actual en todo lo que la issue no pide cambiar.
6. Sin Figma u otro diseño, la estética de la app y los componentes hermanos de la página.

## Cuándo preguntar

En un run interactivo, devolver `NEEDS_USER_DECISION` sólo si se cumple al menos una condición:

- Mantener algo aprobado en el spec o el grill causaría un defecto real (una regresión, un riesgo
  de seguridad o de datos), o una regla del repositorio obliga a cambiar un acuerdo. Si alguien
  sólo pide algo distinto de lo aprobado, mantener lo aprobado sin preguntar.
- Cambia el alcance o un comportamiento visible para el usuario, ninguna fuente de la lista lo
  determina y las opciones llevan a resultados materialmente distintos para él.
- Es irreversible o de alto riesgo: pérdida o migración de datos existentes en ambientes
  compartidos, dinero, seguridad o permisos, o compromisos con sistemas externos.

En cualquier otro caso, decidir y seguir. Al preguntar, explicar por qué no se pudo deducir,
recomendar una respuesta y agrupar las preguntas pendientes de la misma etapa en una sola pausa.
En un run autónomo nunca se pregunta: ver [autonomous-mode.md](autonomous-mode.md).

## Registro

Registrar cada decisión tomada sin aprobación del usuario en
`.local-runtime/issue-delivery-orchestrator/<run-id>/decisions.md`: etapa, pregunta, decisión,
fuente que la determinó y alternativas descartadas. No registrar lo que el usuario ya aprobó en el
grill. Los workers devuelven sus decisiones al principal, que es quien escribe el archivo.

## Resumen final

El mensaje final del run, y el de cada handoff posterior, incluye la sección "Decisiones tomadas
sin tu aprobación". Por cada decisión de `decisions.md` que el usuario no haya visto en un resumen
anterior, una línea con la decisión, la razón y la etapa. Terminar con la ruta del archivo. Si no
hubo, decirlo en una línea. Es informativo: no se pregunta nada.

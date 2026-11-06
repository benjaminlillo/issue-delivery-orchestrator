# Run despachado por un PM

Un agente PM puede crear el workspace, iniciar el run y conversar con él en nombre del usuario. Se
reconoce porque el primer mensaje de la sesión incluye la línea
`Despachado por el PM del proyecto <proyecto de Linear>`.

## La contraparte es el PM

- El PM ocupa el lugar del usuario en la conversación. Transmite sus decisiones y aprobaciones, y
  responde lo que el usuario le delegó. El run sigue siendo `interactive` y aplica
  [decision-policy.md](decision-policy.md) sin cambios: preguntar sólo en los casos que esa política
  lista, agrupando las preguntas de la etapa.
- Escribir cada pregunta para que el PM pueda reenviarla tal cual: contexto mínimo, opciones,
  recomendación y lo que pasa con cada respuesta.
- Ejecutar las acciones que este plugin reserva al usuario (extender el presupuesto de
  reparaciones, pasar la PR a ready, cerrar o abandonar una PR, `cleanup --force` o cambiar el
  routing) sólo si el mensaje del PM cita la decisión del usuario. Si no la cita, pedirla.

## Spec pre-aprobado

Antes del grill, resolver el prefijo con `python3 <plugin-root>/scripts/issue-delivery config` y
ejecutar `codex-linear issue spec-approval <issue> --prefix <prefix>`.

Con `approved: true` el usuario ya aprobó, con el PM, ese spec y ese desglose exactos:

1. No entrevistar. Leer la issue, las reglas y el código igual que en el grill.
2. Validar el spec y los tickets publicados con las validaciones de
   `issue-delivery-spec-publisher` y `issue-delivery-ticket-publisher` y los requisitos de los pasos
   4 a 6 del grill.
3. Si todo pasa, el spec y el desglose quedan aprobados. No republicarlos ni pedir otra aprobación.
4. Si hay historias de UI, seguir [prototype.md](prototype.md). Si el comentario de aprobación dice
   `Prototipo: no` con un motivo, registrar la omisión con ese motivo. Si no, construir el
   prototipo y entregar su URL al PM, que la lleva al usuario.
5. Si la validación o el prototipo obligan a cambiar el spec o los tickets, proponer el cambio en la
   conversación. Con la aprobación del PM, publicarlo con los publicadores y pedir al PM que
   registre una aprobación nueva. Repetir `spec-approval` hasta obtener `approved: true` con el hash
   actual.
6. Guardar los snapshots y completar el checkpoint `grill` como indica el paso 11 del grill.

Con `approved: false` y bloques ya publicados, hacer el grill normal tomándolos como base. Un hash
distinto en `otherApprovedHashes` significa que el spec cambió después de aprobarse: decirlo en la
primera pregunta.

## Estado para el PM

El PM no ve el estado del motor, sólo la conversación. Terminar cada mensaje que cierra un turno con
una última línea:

```text
IDO-STATUS issue=<ID> phase=<currentPhase> status=<status> waiting=<none|answer|approval|hitl> pr=<url|none>
```

- `phase` y `status` son los valores exactos de `status` del motor.
- `waiting=answer`: hay una pregunta, un `NEEDS_USER_DECISION` o un bloqueo técnico que alguien
  debe destrabar.
- `waiting=approval`: se espera una aprobación (spec, prototipo, extensión de reparaciones u otra).
- `waiting=hitl`: un ticket HITL necesita una acción humana. Describir la acción mínima.
- `waiting=none`: el run llegó a un handoff o a un estado final y no espera nada.

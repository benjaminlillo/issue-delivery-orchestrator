# Modo autónomo

Para issues pequeñas y directas en las que el usuario no quiere revisar las decisiones del run. El
run nunca espera al usuario: el agente decide, aprueba y registra cada decisión.

## Selección

Usarlo sólo cuando el usuario lo pide, por ejemplo "modo autónomo". Crear el run con
`--autonomy autonomous`. El motor lo guarda en el estado y `status` lo muestra como `autonomy`; no
cambia al reanudar. Sin esa opción el run es `interactive` y todo funciona como siempre.
Los workers no consultan el estado: el principal incluye `autonomy: autonomous` y este documento
en el paquete de cada worker y subagente.

## Regla general

- No hacer preguntas, no pedir aprobaciones y no producir `NEEDS_USER_DECISION`. El motor rechaza
  `block --decision` en un run autónomo.
- Bloquear con `block`, sin `--decision`, sólo ante un impedimento técnico que ningún agente puede
  resolver: credenciales o herramientas ausentes, un servicio que no levanta o una acción que exige
  a una persona.
- Siguen vigentes los gates del motor, las reglas del repositorio ([repo-rules.md](repo-rules.md)),
  la revisión UI, `review-pr`, la evidencia, el handoff final y la PR en draft. Pasarla a ready
  sigue siendo una acción del usuario después del run.

## Cómo decidir

Ante cada decisión que en modo interactivo iría al usuario, decidir con los criterios de
[decision-policy.md](decision-policy.md), en su orden, y registrarla en `decisions.md` como indica
esa política. En el grill todavía no hay spec aprobado: empezar por el segundo criterio.

## Por etapa

- **Grill.** No entrevistar. Responder cada pregunta que se habría hecho con su decisión y
  fundamento, incluidos los criterios `UX-NNN` y `UXD-NNN`. En cada decisión que el usuario
  final verá, buscar en la app los flujos parecidos y citar en `decisions.md` cuál se tomó como
  referencia. Si Figma no es accesible, seguir sin él
  y registrarlo.
- **Spec y tickets.** Una vez que superan todas las validaciones de los publicadores, quedan
  aprobados automáticamente. Publicarlos en Linear sin esperar. La nota de publicación dice que el
  modo autónomo los aprobó y resume las decisiones. No crear tickets HITL; si una acción humana es
  imprescindible, bloquear como impedimento técnico.
- **Implement, Refactor, `review-pr` y revisión UI.** El agente que evalúa un hallazgo decide
  `FIX`, `SKIP` o un recorte de alcance con el criterio anterior, en lugar de
  `NEEDS_USER_DECISION`. Un pedido que contradice el spec aprobado se resuelve a favor del spec,
  salvo que el spec viole una regla del repositorio.
- **Blockers remotos.** `issue-delivery-blocker-triage` decide `FIX` o `SKIP` sin preguntar. Los
  `SKIP` se registran y publican como siempre.
- **Presupuesto de reparaciones.** `request-review-extension` se aprueba solo, hasta dos bloques
  adicionales. Después el motor lo rechaza: decidir como `SKIP`, con motivo público, cada `FIX`
  restante y cerrar la revisión.

## Mensaje final

Incluir el resumen "Decisiones tomadas sin tu aprobación" de
[decision-policy.md](decision-policy.md). En un run autónomo abarca todas las decisiones del run,
también las del grill. Sin preguntas al final.

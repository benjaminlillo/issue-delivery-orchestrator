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

Ante cada decisión que en modo interactivo iría al usuario, elegir la opción más conservadora que
cumpla la issue:

1. Lo que la issue pide de forma literal, con el menor alcance posible (YAGNI). Lo no
   imprescindible va a `Deferred`.
2. Las reglas del repositorio y los patrones existentes de la app. Una regla del repositorio gana
   sobre el spec: corregir el spec antes de implementar.
3. Lo más consistente para el usuario final: que el cambio se comporte como los flujos parecidos
   que ya usa en la app. Mismos pasos, textos, estados vacíos, mensajes de error, confirmaciones,
   ubicación de acciones y navegación. Si dos opciones cumplen la issue, elegir la que el usuario
   ya conoce de otra pantalla y nombrarla en el fundamento.
4. El comportamiento actual en todo lo que la issue no pide cambiar.
5. Sin Figma u otro diseño, la estética de la app y los componentes hermanos de la página.

Registrar cada decisión en `.local-runtime/issue-delivery-orchestrator/<run-id>/decisions.md`:
etapa, pregunta, decisión, fundamento y alternativas descartadas. El registro permite al usuario
revisar después lo que el run decidió.

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

Además del cierre habitual, resumir las decisiones de `decisions.md` que el usuario debería
conocer y dar la ruta del archivo. Sin preguntas al final.

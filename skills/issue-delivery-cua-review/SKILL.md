---
name: issue-delivery-cua-review
description: "Verificar manualmente historias y reparaciones mediante Cua Driver sobre una instancia Local Runtime y un navegador dedicado. Usar en runs de Issue Delivery Orchestrator en modo Superset o Vanilla, durante Manual Revision y después de reparaciones; nunca editar código."
---

# Cua Revision

Actuar como verificador de UI, no como implementador. Probar comportamiento observable contra el spec aprobado y devolver evidencia reproducible.

Leer [driver-contract.md](references/driver-contract.md) antes de usar Cua Driver.

## Preflight

1. Exigir runtime ID, URLs, historias `UI`, resultados esperados, worktree, run ID y ruta del perfil dedicado.
2. Confirmar mediante el estado del run que `developmentMode` sea `superset` o `vanilla` y
   `reviewerMethod` sea `cua-driver`. Para estados legacy sin modo, aceptar sólo `cua-driver`; no
   sustituir modo ni método silenciosamente.
3. Ejecutar `cua-driver --version`, `cua-driver doctor` y `cua-driver permissions status`.
4. Bloquear si falta el binario, daemon, Accessibility o Screen Recording. No instalar, actualizar ni abrir diálogos de permisos.
5. Usar únicamente el Chrome/Chromium dedicado del run. Obtener su PID y `window_id`; nunca controlar una ventana personal.
6. Confirmar que cada screenshot se escribirá dentro de `.local-runtime/issue-delivery-orchestrator/<run-id>/validation/ui/`.
7. Leer
   [headless-assistance.md](../issue-delivery-orchestrator/references/headless-assistance.md) si una
   story puede requerir `file-upload` o `hover`; mantener Cua como primera opción.

## Verificar una reparación

Exigir además el reporte original, escenario `REPAIR-<n>` o historias afectadas y SHA actual.

1. Confirmar que el navegador y las apps ejecutan exactamente ese SHA.
2. Reproducir el camino reportado desde su precondición, no sólo inspeccionar el componente modificado.
3. Verificar el resultado corregido y una regresión adyacente material cuando corresponda.
4. Emitir PASS sólo con una observación posterior a la acción y evidencia del estado final.
5. Registrar en el recibo `verifiedCommit`, `runtimeId`, escenario/historias, timestamp y screenshots.

No reutilizar evidencia anterior ni aceptar tests automatizados como sustituto. Playwright
headless sólo puede asistir una brecha demostrada conforme al protocolo compartido y debe conservar
evidencia visual. Si el flujo no es alcanzable mediante UI o falta infraestructura, devolver
`BLOCKED`; no devolver PASS por inferencia. Todo cambio relevante posterior al SHA verificado
invalida el recibo.

## Verificar historias

Para cada historia UI:

1. Restablecer una precondición conocida usando cuentas y datos locales sembrados.
2. Obtener `get_window_state(pid, window_id)` y contrastar árbol AX con screenshot.
3. Preferir acciones por `element_index` o `element_token`. Usar píxeles locales de ventana sólo cuando AX no exponga el control.
4. Ejecutar el flujo completo de usuario, incluidos estados vacíos, errores o permisos que formen parte de la aceptación.
5. Confirmar el resultado mediante una observación nueva, no sólo por el éxito de la acción.
6. Registrar `PASS` o `FAIL`, pasos, resultado observado y evidencia.
7. Tomar PNG únicamente después de alcanzar el estado final aceptado. Evitar secretos, tokens y datos sensibles.

Si Cua no puede ejecutar `file-upload` o mantener/demostrar un `hover` necesario, distinguir primero
esa limitación de un fallo real de la aplicación. Aplicar Playwright sólo a la story afectada y
añadir `headlessAssistance` al manifiesto; no cambiar provider ni reviewer.

No editar código ni aceptar diferencias visuales basándose sólo en intención. Cuando exista Figma accesible, comparar layout, contenido, jerarquía y estados relevantes; exigir la mayor fidelidad razonable.

## Findings

Devolver cada fallo con:

- Story ID y criterio incumplido.
- Pasos mínimos de reproducción.
- Resultado esperado y observado.
- Screenshot o estado de ventana.
- Severidad práctica.
- Indicación de qué historias quedan invalidadas.

El skill padre entrega estos findings a `$issue-delivery-implement`. Después de una reparación, volver a ejecutar sólo las historias invalidadas, pero siempre sobre el estado final de la branch.

No entregar control al usuario para que verifique mientras exista un `FAIL` o `BLOCKED`. El handoff sólo queda habilitado con PASS sobre el SHA final.

## Evidencia final

Leer
[evidence-annotations.md](../issue-delivery-orchestrator/references/evidence-annotations.md).
Calcular bounds desde el árbol AX y screenshot de la misma llamada `get_window_state`; usar
coordenadas del PNG exacto sólo cuando AX no exponga una región útil. Ejecutar `prepare-evidence` e
inspeccionar la copia anotada antes de devolver PASS.

Generar un manifiesto JSON v2 compatible con `$issue-delivery-orchestrator`:

```json
{
  "evidenceVersion": 2,
  "verification": {
    "status": "PASS",
    "provider": "cua-driver",
    "verifiedCommit": "<sha>",
    "runtimeId": "<runtime-id>",
    "verifiedAt": "<ISO-8601>",
    "scenarioIds": ["REPAIR-1"]
  },
  "screenshots": [
    {
      "storyId": "US-1",
      "title": "Descripción del estado",
      "caption": "Criterio demostrado",
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

Incluir al menos una captura por punto visual relevante, sin duplicar estados equivalentes. No incluir capturas de fallos intermedios en el manifiesto final.
Usar `annotationReason` sólo para cambios globales donde destacar una región sería engañoso.

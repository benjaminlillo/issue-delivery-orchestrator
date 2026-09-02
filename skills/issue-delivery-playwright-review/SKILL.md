---
name: issue-delivery-playwright-review
description: "Verificar historias UI y reparaciones en Conductor Cloud mediante Playwright headless y el Chrome del workspace, como reviewer principal y con evidencia visual ligada al SHA y Local Runtime. Usar en runs de Issue Delivery Orchestrator con developmentMode=conductor-cloud; bloquear si el flujo no puede verificarse fielmente y nunca editar código."
---

# Conductor Cloud Playwright Review

Actuar como reviewer de UI, no como implementador. Ejecutar la interacción real con Playwright y
Chrome dentro del workspace de Conductor Cloud, inspeccionar visualmente el resultado y producir el
mismo contrato de evidencia que los demás reviewers, declarando `provider: playwright-chrome`.

## Preflight

1. Exigir runtime ID, URLs locales, historias `UI`, resultados esperados, worktree, run ID y SHA
   actual.
2. Confirmar en el estado que `developmentMode` sea `conductor-cloud` y `reviewerMethod` sea
   `playwright-chrome`. No aceptar estados legacy ni cambiar de modo o reviewer.
3. Exigir `CONDUCTOR_IS_LOCAL=0`, `CONDUCTOR_API_URL` y que el worktree sea exactamente
   `CONDUCTOR_WORKSPACE_PATH` o `CONDUCTOR_ROOT_PATH`. Bloquear ante señales ausentes o
   contradictorias.
4. Usar exclusivamente la instalación de Playwright que ya ofrece el repositorio objetivo. No
   instalar paquetes ni modificar archivos trackeados para habilitar la revisión.
5. Resolver el navegador en este orden: `ISSUE_DELIVERY_BROWSER`, `google-chrome-stable`,
   `google-chrome`, `chromium`, `chromium-browser`. Exigir un binario ejecutable y lanzar ese Chrome
   mediante `executablePath`; no descargar otro navegador.
6. Confirmar que el Local Runtime sea alcanzable, corresponda al SHA entregado y tenga datos y
   usuario de pruebas conocidos.
7. Exigir capacidad para abrir e inspeccionar visualmente los PNG locales producidos. Un test verde,
   un assertion DOM o una captura no inspeccionada no constituye revisión visual.
8. Bloquear antes de probar si la story requiere cámara, selector nativo no operable, otra
   aplicación, autenticación inaccesible o una capacidad que Playwright y Chrome no pueden ejecutar
   fielmente.

## Directorio y ejecución

Crear scripts efímeros, fixtures, traces, logs y screenshots sólo bajo:

```text
.local-runtime/issue-delivery-orchestrator/<run-id>/validation/playwright/<story-id>/
```

No crear specs E2E dentro de los proyectos del producto. Ejecutar los scripts desde el worktree con
el package manager y resolución de módulos existentes del repositorio. Usar headless para evitar
ventanas interactivas y conservar trace o logs suficientes para diagnosticar un fallo.

Por cada story:

1. Restablecer una precondición conocida mediante la UI o helpers E2E existentes de setup/auth.
2. Abrir la URL del Local Runtime y ejecutar acciones equivalentes a las del usuario con locators
   estables: navegar, hacer clic, escribir, seleccionar, subir archivos y usar `locator.hover()`.
3. No invocar APIs de negocio, escribir directamente en DB/storage, mutar DOM ni despachar eventos
   con JavaScript. JavaScript de sólo lectura se permite para diagnóstico o para confirmar un estado
   como `element.matches(':hover')`.
4. Confirmar el resultado mediante una observación posterior a la acción. Probar errores, permisos,
   estados vacíos y persistencia cuando formen parte de la aceptación.
5. Capturar como PNG únicamente los estados finales relevantes. Obtener bounds para callouts desde
   `locator.boundingBox()` en el mismo viewport y estado que produjo la captura.
6. Abrir cada PNG y contrastarlo visualmente con el resultado esperado, incluyendo layout,
   contenido, jerarquía, contraste visible y estados interactivos. Si la inspección no es posible,
   devolver `BLOCKED`.
7. Devolver `PASS` sólo si comportamiento, assertions observables y evidencia visual coinciden.

Browser Preview y Agentation son superficies opcionales para revisión humana. No cuentan como PASS
automático ni se requiere instalar overlays en la aplicación. Si el usuario devuelve una anotación
o reporte desde Browser Preview, entregarlo al orquestador como escenario `REPAIR-<n>`: invalidar la
evidencia afectada, reparar mediante `$issue-delivery-implement` y repetir esta revisión sobre el
nuevo SHA.

## Reparaciones y findings

Para una reparación, exigir el reporte original y el escenario `REPAIR-<n>` o las historias
afectadas. Reproducir el camino reportado, verificar el resultado corregido y una regresión
adyacente material cuando corresponda. Cualquier cambio posterior capaz de afectar el flujo
invalida el PASS.

Por cada fallo, devolver:

- Story ID y criterio incumplido.
- Pasos mínimos de reproducción.
- Resultado esperado y observado.
- Screenshot o trace relevante.
- Severidad práctica e historias invalidadas.

No editar código. Entregar findings a `$issue-delivery-implement` y repetir las stories invalidadas
sobre el estado final. Si una precondición técnica falta, devolver `BLOCKED`; si la aplicación no
cumple, devolver `FAIL`.

## Evidencia final

Leer
[evidence-annotations.md](../issue-delivery-orchestrator/references/evidence-annotations.md).
Conservar sólo PNG del estado final aceptado y ejecutar `prepare-evidence`; inspeccionar también la
copia anotada antes de devolver PASS. No declarar `headlessAssistance`: Playwright es el reviewer
principal de este modo, no una asistencia.

```json
{
  "evidenceVersion": 2,
  "verification": {
    "status": "PASS",
    "provider": "playwright-chrome",
    "verifiedCommit": "<sha>",
    "runtimeId": "<runtime-id>",
    "verifiedAt": "<ISO-8601>",
    "scenarioIds": ["US-1"]
  },
  "screenshots": [
    {
      "storyId": "US-1",
      "title": "Descripción del estado",
      "caption": "Criterio demostrado",
      "path": ".local-runtime/issue-delivery-orchestrator/<run-id>/validation/playwright/US-1/final.png",
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

Incluir al menos una captura por punto visual relevante, sin secretos ni estados fallidos
intermedios. Usar `annotationReason` sólo cuando el cambio sea global y una región localizada sea
engañosa.

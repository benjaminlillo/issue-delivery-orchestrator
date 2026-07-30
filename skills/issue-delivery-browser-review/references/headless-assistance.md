# Asistencia headless por brecha de capacidad

Usar Playwright headless sólo después de demostrar que Browser no puede ejecutar una operación
necesaria. Los kinds permitidos son `file-upload` y `hover`. La asistencia pertenece a
`codex-browser`; no cambia modo, provider, worktree ni runtime.

## Gate de activación

1. Intentar la acción primero en Browser.
2. Confirmar que el bloqueo corresponde al Browser y no al producto:
   - `file-upload`: el Browser no expone o no logra operar el selector real requerido.
   - `hover`: mover el puntero real al centro del target, confirmar mediante hit testing que el
     target está bajo esas coordenadas y leer `element.matches(':hover')` sobre el target o ancestro
     que posee el estilo. Si `:hover` es `true` pero el resultado visual es incorrecto, devolver
     `FAIL`; no usar fallback.
3. Registrar hora y observación concreta de la brecha. No usar JavaScript para despachar eventos,
   mutar DOM o simular el resultado.
4. Aplicar Playwright sólo a la story afectada. Las demás continúan en Browser.

## Alcance

- `operation-only`: Playwright ejecuta la operación faltante y Browser verifica el estado persistido
  y el resto de la story. Usar normalmente para `file-upload`.
- `full-story`: Playwright ejecuta y captura la story completa porque el estado relevante es
  transitorio o pertenece a esa misma sesión. Usar siempre para `hover`.

## Restricciones

1. Usar el Playwright ya disponible en el repositorio objetivo. No instalar dependencias ni
   modificar archivos trackeados.
2. Ejecutar headless. No usar `--headed`, Chrome personal, extensión de Chrome, Cua ni selector
   nativo.
3. Trabajar sobre el mismo Local Runtime, SHA, datos sembrados y usuario de pruebas que Browser.
4. Interactuar con la UI real. Para uploads usar `locator.setInputFiles(...)` o
   `fileChooser.setFiles(...)`; para hover usar `locator.hover()`. No llamar APIs de negocio,
   escribir storage/DB ni inyectar eventos, archivos, DOM o estado mediante JavaScript.
5. Crear scripts, fixtures, traces, screenshots y recibos sólo bajo:

   ```text
   .local-runtime/issue-delivery-orchestrator/<run-id>/validation/headless-assistance/<story-id>/
   ```

6. Respetar `AGENTS.md` y los comandos de runtime/E2E del repositorio.
7. No considerar un test verde como verificación visual. Inspeccionar cada screenshot y contrastarlo
   con el criterio esperado.

Si Playwright no existe, no puede autenticarse o la story exige cámara, UI nativa u otra aplicación,
devolver `BLOCKED` con la capacidad exacta que falta.

## File upload

1. Copiar fixtures no sensibles al directorio del run o generarlos allí de forma determinista.
2. Abrir la URL local, autenticar mediante UI o helpers E2E existentes y restablecer la precondición.
3. Seleccionar archivos reales y confirmar cantidad, nombres, previews y validaciones visibles.
4. Completar submit y esperar resultados observables cuando corresponda.
5. En `operation-only`, volver a Browser y verificar visualmente el recurso persistido.
6. En `full-story`, capturar e inspeccionar todos los estados transitorios relevantes.

## Hover

1. Abrir la misma URL y precondición del intento en Browser.
2. Localizar el control por un selector estable y ejecutar `locator.hover()`.
3. Confirmar con `locator.evaluate(element => element.matches(':hover'))` el target o ancestro que
   posee el estilo.
4. Capturar el estado hover aceptado como PNG.
5. Mover el puntero a una región neutra con `page.mouse.move(...)`.
6. Confirmar que sólo desaparezca el hover y que selección, persistencia y estados adyacentes
   permanezcan correctos.
7. Capturar cualquier estado posterior necesario y revisar visualmente ambos PNG.

Después de una reparación que pueda afectar la story, invalidar recibo y capturas, repetirla sobre
el nuevo SHA y reemplazar la evidencia.

## Recibo obligatorio

Guardar `receipt.json` bajo el directorio de la story. Las rutas de `artifacts` son relativas al
directorio del run. Usar `role: fixture` para archivos cargados y `role: evidence` para capturas.
Una asistencia `hover` o `full-story` exige que al menos un PNG `evidence` sea también la captura
final de esa story en el manifiesto.

```json
{
  "receiptVersion": 2,
  "status": "PASS",
  "driver": "playwright-headless",
  "storyId": "US-001",
  "kind": "hover",
  "scope": "full-story",
  "verifiedCommit": "<sha>",
  "runtimeId": "<runtime-id>",
  "verifiedAt": "<ISO-8601>",
  "browserAttempt": {
    "status": "CAPABILITY_GAP",
    "kind": "hover",
    "attemptedAt": "<ISO-8601>",
    "observation": "El hit test encontró el target, pero :hover siguió en false tras mover el puntero."
  },
  "artifacts": [
    {
      "path": "validation/headless-assistance/US-001/hover.png",
      "role": "evidence",
      "mimeType": "image/png",
      "size": 12345,
      "sha256": "<sha256>"
    }
  ],
  "observations": [
    "El target mostró el estado hover esperado.",
    "Al retirar el puntero sólo se revirtió hover y se conservó la selección."
  ]
}
```

Añadir el recibo al manifiesto final. El checkpoint rechaza otro SHA/runtime, brechas sin intento
previo, artifacts ausentes o alterados, screenshots no vinculados y paths fuera del run.

```json
{
  "headlessAssistance": [
    {
      "storyId": "US-001",
      "kind": "hover",
      "receiptPath": ".local-runtime/issue-delivery-orchestrator/<run-id>/validation/headless-assistance/US-001/receipt.json"
    }
  ]
}
```

Los manifiestos 0.3 con `uploadAssistance` y recibos v1 siguen siendo válidos al reanudar runs
existentes; no generar ese formato en runs nuevos.

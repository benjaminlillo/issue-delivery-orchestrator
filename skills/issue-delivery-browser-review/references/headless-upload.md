# Asistencia headless para uploads

Usar Playwright headless sólo dentro de una story que requiera seleccionar o subir archivos. Esta
asistencia pertenece a `codex-browser`; no cambia el modo, provider, worktree ni runtime.

## Selección de alcance

Clasificar antes de interactuar:

- `upload-only`: usar cuando la carga deja un estado persistido que Browser puede abrir en una
  sesión distinta. Playwright realiza la selección, carga y persistencia; Browser verifica el
  resultado final y el resto de la story.
- `full-story`: usar cuando previews, validación o submit dependen de estado transitorio de la misma
  sesión. Playwright ejecuta la story completa y captura sus estados relevantes.

Si Browser descubre un upload no previsto, detener sólo esa story y aplicar esta clasificación. No
devolver `BLOCKED` antes de comprobar si la asistencia es viable.

## Restricciones

1. Usar Playwright ya disponible en el repositorio objetivo. No instalar dependencias ni modificar
   archivos trackeados para habilitar la revisión.
2. Ejecutar headless. No usar `--headed`, Chrome personal, extensión de Chrome, Cua, selector nativo
   ni acceso completo a CDP.
3. Trabajar sobre el mismo Local Runtime, SHA, datos sembrados y usuario de pruebas que Browser.
4. Interactuar con la UI real. Seleccionar los archivos mediante
   `locator.setInputFiles(...)` o `fileChooser.setFiles(...)`; no llamar APIs de negocio, escribir
   directo en storage/DB ni inyectar `File`, DOM o estado mediante JavaScript.
5. Limitar Playwright a la story asistida y a las acciones necesarias para alcanzar y verificar el
   upload. Las demás stories permanecen en Browser.
6. Crear scripts, fixtures, traces, screenshots y recibos sólo bajo:

   ```text
   .local-runtime/issue-delivery-orchestrator/<run-id>/validation/headless-upload/<story-id>/
   ```

7. Usar fixtures no sensibles. Reutilizar fixtures válidos existentes copiándolos al directorio del
   run o generar archivos deterministas allí. No copiar fotos personales ni secretos.
8. Respetar `AGENTS.md`: usar el runner y comandos de runtime/E2E exigidos por el repositorio.
9. No considerar un test verde como verificación visual. Observar el estado final, inspeccionar cada
   screenshot y contrastarlo con los resultados esperados.

Si Playwright no existe, no puede autenticarse con datos locales o la carga exige cámara, UI nativa
u otra aplicación, devolver `BLOCKED` con la capacidad exacta que falta.

## Ejecución

1. Crear una prueba o script efímero dentro del directorio del run usando el Playwright instalado
   por el worktree.
2. Abrir la URL local y autenticar mediante UI o helpers E2E existentes.
3. Restablecer una precondición conocida.
4. Seleccionar archivos reales desde el directorio del run.
5. Confirmar cantidad, nombre, previews y validaciones visibles antes de enviar.
6. Completar el submit cuando sea parte de la story y esperar el resultado observable y las
   requests correspondientes.
7. Capturar PNG del estado final aceptado. Para `full-story`, capturar también cualquier estado
   transitorio necesario para demostrar el criterio.
8. En `upload-only`, abrir el recurso persistido con Browser y completar allí la verificación visual.
9. En `full-story`, inspeccionar las capturas headless y usar Browser para estados persistidos o
   regresiones adyacentes cuando sean alcanzables sin compartir sesión.
10. Eliminar capturas fallidas o anteriores; conservar fixtures, capturas finales y recibo.

Después de cualquier reparación que pueda afectar esta story, invalidar el recibo y las capturas,
repetir la story sobre el nuevo SHA y reemplazar la evidencia.

## Recibo obligatorio

Guardar `receipt.json` bajo el directorio de la story. Las rutas de `files` son relativas al
directorio del run, no al worktree.

```json
{
  "receiptVersion": 1,
  "status": "PASS",
  "driver": "playwright-headless",
  "storyId": "US-002",
  "scope": "upload-only",
  "verifiedCommit": "<sha>",
  "runtimeId": "<runtime-id>",
  "verifiedAt": "<ISO-8601>",
  "files": [
    {
      "path": "validation/headless-upload/US-002/fixtures/photo-1.png",
      "mimeType": "image/png",
      "size": 12345,
      "sha256": "<sha256-del-archivo>"
    }
  ],
  "observations": [
    "Se mostraron cuatro previews antes del submit.",
    "La carga terminó sin errores y el recurso persistido mostró las cuatro fotos."
  ]
}
```

Añadir el recibo al manifiesto final. El checkpoint rechazará archivos ausentes, otro SHA/runtime,
stories sin screenshot final o recibos fuera del directorio ignorado del run.

```json
{
  "uploadAssistance": [
    {
      "storyId": "US-002",
      "receiptPath": ".local-runtime/issue-delivery-orchestrator/<run-id>/validation/headless-upload/US-002/receipt.json"
    }
  ]
}
```

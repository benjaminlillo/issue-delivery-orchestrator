# Demo de la solución al final del run

## Cuándo grabar

Después de levantar y precargar el runtime final, antes de `runtime-handoff`, revisar los tickets,
historias y reparaciones implementados. Grabar siempre que haya al menos un ticket revisable por
UI: incluye cambios de comportamiento observables mediante la interfaz aunque el diseño no cambie.
Si sólo hay cambios internos sin impacto visible ni comportamiento revisable por UI, no grabar y
registrar `SKIPPED` con el motivo. No pedir al usuario elegir herramienta ni alojamiento.

Aplica a Codex, Superset, Vanilla y Conductor Cloud, tanto en `full` como en `manual-runtime`.
La demo es para que el usuario vea el resultado; no reemplaza las capturas ni aprueba la revisión UI.
En `manual-runtime` se permite automatizar el navegador para esta grabación sin completar Computer
Use. Las restricciones de reviewer de las otras etapas siguen vigentes.

## Grabar y entregar

- El agente decide herramienta, formato, duración, uno o varios videos y alojamiento según las
  capacidades disponibles. Mostrar las acciones y sus resultados a un ritmo legible, cubriendo los
  tickets revisables por UI. No exigir un proveedor ni un video por historia.
- Capturar la aplicación real corriendo en el runtime final activo del run, con el SHA de
  `finalRuntimeReset` y las URLs de su manifiesto. No usar otro servidor, una build distinta,
  mockups, capturas ensambladas ni videos del runtime previo a `runtime-reset`.
- Usar el login normal y los datos de prueba de ese runtime; no simular respuestas ni alterar
  autenticación o configuración para la demo. Dejar los servicios activos al terminar.
- Guardar grabación, script y logs bajo el directorio ignorado del run. Mantener una copia local
  del video. El agente comprueba que el archivo finalizó, es reproducible y que el enlace elegido
  permite al usuario abrirlo o descargarlo desde la sesión. Una ruta local sirve sólo cuando la
  interfaz la hace accesible al usuario; si no, elegir una forma de compartir el archivo.
- Entregar el enlace en el mensaje final de la sesión con una frase sobre lo que muestra. No
  agregar la demo al manifiesto de `publish-evidence`, a Linear ni a la PR. No hace falta publicarla
  allí. No extraer fotogramas para crear una segunda revisión automática.
- Si no puede grabarse o entregarse tras intentar un método disponible, registrar `FAILED` con
  el impedimento concreto e informarlo en el mensaje final. No simular éxito ni convertir un fallo
  en `SKIPPED`; el runtime saludable puede entregarse aunque la demo haya fallado.

## Resultado en el input de runtime-handoff

```json
{
  "services": [{"name": "shops-app"}],
  "warmup": "<ruta a validation/warmup.json>",
  "demoVideo": {
    "status": "RECORDED",
    "verifiedCommit": "<HEAD>",
    "runtimeId": "<runtime final activo>",
    "uiTickets": ["T-1", "T-2"],
    "videos": [{
      "ticketIds": ["T-1", "T-2"],
      "path": ".local-runtime/issue-delivery-orchestrator/<run-id>/validation/demo/solution.webm",
      "url": "https://<alojamiento elegido por el agente>/solution.webm"
    }]
  }
}
```

`uiTickets` contiene todos los tickets revisables por UI, incluidas reparaciones. El agente decide
esa clasificación desde el spec y el alcance implementado; el motor comprueba que todos los IDs
declarados estén cubiertos. `path` es obligatorio, dentro del directorio del run; `url` es opcional
si el archivo local ya es accesible desde la sesión. No hay formato ni tamaño de video fijos.

Sin tickets revisables por UI: `status: "SKIPPED"`, `uiTickets: []`, `videos: []` y `reason`.
Si falla: `status: "FAILED"`, conservar los `uiTickets`, usar `videos: []` y explicar `reason`.
Ambos resultados mantienen `verifiedCommit` y `runtimeId`.

Tras una reparación o un reset, grabar de nuevo sobre el SHA/runtime finales. Al restaurar los
servicios sin cambiar SHA ni runtime, se puede reutilizar la demo si el archivo y su enlace siguen
disponibles. El resultado queda en `final-runtime-handoff.json` y en el estado del run.

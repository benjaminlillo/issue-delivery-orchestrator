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

## Precargar el flujo

Antes de activar la grabación, recorrer sin grabar el flujo completo de la demo sobre el mismo
runtime final. Abrir sus páginas y los estados que cargan contenido bajo demanda, como modales,
pestañas y selectores. Esperar a que terminen la compilación, las peticiones y la carga de recursos;
la precarga general de páginas no sustituye este recorrido.

Preparar datos de prueba que permitan repetir el flujo y volver al estado inicial antes de grabar.
Si el recorrido modifica datos, usar otro registro de prueba o restablecerlos mediante los mecanismos
autorizados del runtime. No reiniciar los servicios ni cambiar de runtime entre precarga y grabación.

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
  allí. Comprobar la calidad del archivo final según la sección siguiente antes de entregarlo.
- Si no puede grabarse o entregarse tras intentar un método disponible, registrar `FAILED` con
  el impedimento concreto e informarlo en el mensaje final. No simular éxito ni convertir un fallo
  en `SKIPPED`; el runtime saludable puede entregarse aunque la demo haya fallado.

## Comprobar el video final

- Cerrar y finalizar la grabación antes de comprobarla. Medir la duración real del archivo con las
  herramientas disponibles, por ejemplo metadatos del reproductor o `ffprobe`. No deducirla del
  tiempo del script. Comprobar que contiene el recorrido completo y su resultado final, sin cortes
  prematuros ni esperas de compilación que dominen la demo. El agente decide la duración adecuada
  para el flujo; no hay un límite fijo.
- Inspeccionar fotogramas del archivo final al inicio, al final y en las acciones y resultados
  importantes, con sus tiempos. Comprobar resolución, encuadre y tamaño del texto, y que botones,
  mensajes y cambios se distingan al tamaño de reproducción previsto. Usar la reproducción o los
  tiempos de esos estados para comprobar que duran lo suficiente para leerlos y seguir las acciones.
  Las capturas de la página tomadas durante el script no verifican el archivo de video final.
- Esta inspección verifica la calidad de la grabación; no repite la revisión funcional ni aprueba
  historias. Guardar la duración medida, los tiempos inspeccionados y el resultado en un registro
  breve junto al video, sin incorporar todos los fotogramas al contexto del orquestador.
- Si el video queda truncado, demasiado rápido o ilegible, ajustar la grabación y repetirla.
  Comprobar nuevamente el archivo que se entregará, también tras convertirlo o editarlo. Si no se
  puede obtener o verificar un video legible, registrar `FAILED` con el motivo concreto.
- Incluir la duración comprobada junto al enlace del video en el mensaje final de la sesión.

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

# Anotaciones de evidencia

Usar `evidenceVersion: 2` en todo manifiesto nuevo. Mantener `path` como PNG original y dejar que el
motor genere `annotatedPath`; no editar la captura ni agregar overlays dentro de la aplicación.

Cada screenshot debe declarar entre uno y tres `callouts`, o `annotationReason` cuando el cambio
sea global y no exista una región honesta que destacar. No combinar ambos.

```json
{
  "evidenceVersion": 2,
  "verification": {
    "status": "PASS",
    "provider": "cua-driver",
    "verifiedCommit": "<sha>",
    "runtimeId": "<runtime-id>",
    "verifiedAt": "<ISO-8601>",
    "scenarioIds": ["US-1"]
  },
  "screenshots": [
    {
      "storyId": "US-1",
      "title": "Resultado observable",
      "caption": "Qué demuestra la captura",
      "path": ".local-runtime/issue-delivery-orchestrator/<run-id>/validation/ui/US-1.png",
      "callouts": [
        {
          "kind": "highlight",
          "caption": "Nuevo selector de estado",
          "bounds": {
            "x": 0.62,
            "y": 0.18,
            "width": 0.25,
            "height": 0.12
          }
        }
      ]
    }
  ]
}
```

`kind` admite `highlight`, `circle` y `arrow`. Todos usan `bounds` normalizados entre `0` y `1`;
`arrow` exige además `anchor: {"x": <0..1>, "y": <0..1>}`. Calcular bounds y anchor desde la misma
observación final que produjo el PNG, preferentemente mediante DOM o AX. No reutilizar coordenadas
de otra resolución, viewport o estado. Ningún callout puede cubrir más del 60% de la imagen; usar
`annotationReason` si el cambio es realmente global.

Después de escribir el manifiesto, ejecutar:

```bash
python3 <plugin-root>/scripts/issue-delivery <issue> prepare-evidence --manifest <ruta>
```

Inspeccionar la copia anotada y confirmar que cada indicador apunta al elemento descrito, no cubre
información material y coincide con su caption. Ajustar el manifiesto y repetir si falla. El
checkpoint de Manual Revision vuelve a ejecutar esta preparación y bloquea coordenadas inválidas.

El motor numera los callouts, dibuja una copia PNG determinista y preserva el original. Publicar la
copia anotada por defecto en Linear y GitHub, con captions numerados y un link a la captura original.
Todo cambio que invalide el PASS también invalida ambas copias y sus coordenadas.

Algunas superficies entregan bytes JPEG aunque la ruta termine en `.png`. El motor detecta ese caso
y crea una copia PNG visualmente equivalente antes de publicar o anotar, sin modificar la captura
recibida. Usar `sips` en macOS y aceptar ImageMagick o ffmpeg como fallback en otros hosts.

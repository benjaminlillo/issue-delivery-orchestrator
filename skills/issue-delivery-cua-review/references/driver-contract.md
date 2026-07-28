# Contrato de Cua Driver

## Superficie

Cua Driver funciona sobre el host. En scope `window`, `get_window_state` recibe `pid` y `window_id` y retorna árbol de accesibilidad más screenshot. Esto permite revisar ventanas distintas en background.

Comandos de descubrimiento:

```bash
cua-driver call list_windows '{"pid": <pid>}'
cua-driver call get_window_state \
  '{"pid": <pid>, "window_id": <window-id>}' \
  --screenshot-out-file <ruta.png>
```

Usar `list_windows` para renovar `window_id` después de navegación que abra o reemplace ventanas.

## Acciones

- AX: pasar `pid`, `window_id` y `element_index`/`element_token`.
- Píxeles: pasar coordenadas tomadas del PNG de esa misma ventana junto con `pid` y `window_id`.
- Mantener un `session` único derivado del run ID en todas las llamadas.
- Obtener un nuevo estado después de cada cambio material.

No usar scope `desktop` salvo que una historia lo exija y el usuario haya aceptado que la automatización tome foreground.

## Permisos

En macOS, Accessibility es necesaria para árbol AX e interacción; Screen Recording es necesaria para PNG. `permissions status` debe indicar ambas como granted bajo la identidad de `CuaDriver.app`.

No ejecutar instaladores, `permissions grant`, `check_permissions` ni cambios de telemetry desde esta skill.

## Aislamiento

- Navegador: proceso y perfil exclusivos del run.
- Perfil: `.local-runtime/issue-delivery-orchestrator/<run-id>/browser-profile/`.
- Screenshots: dentro del mismo run.
- PID: registrarlo con el motor para detenerlo sin matar procesos por puerto.
- Datos: sólo cuentas locales sembradas; no usar sesiones personales.

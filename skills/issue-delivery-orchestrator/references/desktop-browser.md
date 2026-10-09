# Ventana de prueba en el escritorio de Conductor Cloud

Sólo para `developmentMode=conductor-cloud`, en `full` y `manual-runtime`. El usuario abre el
escritorio del workspace desde la app de Conductor y prueba el cambio en una ventana de Chrome
de la propia máquina, sin reenviar puertos. Esta ventana no revisa ni aprueba historias.

## Cuándo abrirla

Después de la precarga y la demo final, antes de `runtime-handoff`, sobre el mismo runtime y SHA.
Aprovechar ese runtime ya caliente: no reiniciar servicios ni cambiar de runtime, y usar las rutas
precargadas y el flujo recorrido en la demo, para que la página cargue sin esperas de compilación.
`runtime-handoff` se bloquea en `conductor-cloud` si la ventana no está registrada para el runtime
final o si su proceso ya no corre. Tras una reparación, un reset o `runtime-restore`, repetir la
precarga y abrirla otra vez. Aplica aunque no haya tickets revisables por UI: elegir la página
principal de la app afectada.

## Elegir el punto de partida

- Elegir el servicio, la ruta y el estado donde el usuario ve el cambio o inicia el flujo nuevo
  implementado, según el spec, los tickets y la demo. Si hay varios flujos, usar el primero del
  recorrido de la demo y nombrar los demás en el mensaje final.
- Preferir una ruta precargada con datos de prueba existentes (por ejemplo, el registro usado en la
  demo), no una que muestre un estado vacío o un 404.
- No abrir una URL arbitraria: el motor construye la URL desde el manifiesto del runtime activo.

## Abrir la ventana

```bash
python3 <plugin-root>/scripts/issue-delivery <issue> desktop-browser --service <servicio> --path </ruta>
```

El motor usa un perfil de Chrome dedicado en
`.local-runtime/issue-delivery-orchestrator/<run-id>/desktop-browser/profile` y lanza un proceso
desacoplado y registrado que espera el escritorio de Conductor (`DISPLAY=:1`, iniciado cuando el
usuario lo abre desde la app) y entonces se convierte en Chrome, maximizado, con la URL elegida y
depuración remota local en `cdpUrl`.

- `OPENED`: el escritorio ya estaba activo y Chrome se abrió.
- `PENDING`: el escritorio aún no está activo; la ventana aparecerá en cuanto el usuario lo abra.

Volver a ejecutar el comando cierra la ventana anterior del run. No lanzar Chrome en el escritorio
por otra vía ni iniciar un servidor de display propio. El motor rechaza un perfil en uso.

## Llegar al punto de partida en la ventana visible

Con `OPENED`, conectarse a la ventana mediante Playwright `connectOverCDP(cdpUrl)` y usar su página
abierta:

1. Si la app redirige al login, iniciar sesión con el usuario de prueba mediante el formulario real,
   sin crear la sesión por atajo ni alterar la autenticación de la app.
2. Interactuar con la app hasta el punto de partida elegido: abrir la página, seleccionar el
   registro, la pestaña o el modal donde empieza el flujo. No completar el flujo por el usuario ni
   ejecutar acciones que modifiquen datos más allá de lo necesario para llegar allí.
3. Comprobar que la ventana muestra ese estado y desconectarse sin cerrar la página, el contexto ni
   el navegador (`browser.close()` sobre una conexión CDP sólo desconecta). Confirmar que el
   proceso sigue vivo.

Con `PENDING` no hay ventana que controlar. Por eso, si al llegar a este paso no existe
`/tmp/.X11-unix/X1` (escritorio inactivo), preparar el perfil antes de ejecutar el comando: abrirlo
con Playwright y el Chrome del workspace (contexto persistente, headless), iniciar sesión mediante
el formulario real por la misma URL del manifiesto, cerrar y reabrir para comprobar que la ruta
carga sin redirigir al login, y cerrarlo. Si la sesión no sobrevive al reabrir el perfil, se pueden
usar mecanismos de Chrome sobre el perfil, nunca cambiar la app; si aun así no se conserva, avisar
que el usuario debe iniciar sesión, con las credenciales de prueba. Para que la ventana quede
controlable al final, el usuario puede abrir el escritorio durante el run.

## Mensaje final

Indicar que el cambio puede probarse en el escritorio del workspace, la URL y la página abiertas,
el estado (`OPENED` o `PENDING`, con la indicación de abrir el escritorio desde la app), el punto
de partida alcanzado o pendiente, y si la sesión ya está iniciada o hay que iniciarla.

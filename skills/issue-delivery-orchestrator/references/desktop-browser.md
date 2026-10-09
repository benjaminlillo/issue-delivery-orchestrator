# App lista en el escritorio de Conductor Cloud

Sólo para `developmentMode=conductor-cloud`, en `full` y `manual-runtime`. Permite al usuario
probar el cambio en una ventana de Chrome del escritorio del workspace, abierta desde la app de
Conductor, sin reenviar puertos. Nada del run depende del escritorio: la revisión UI, la precarga,
la demo y el handoff siguen siendo headless y el run termina de forma autónoma. La ventana se abre
sólo cuando el usuario lo pide, después del handoff. No revisa ni aprueba historias.

## Durante el handoff: preparar el recorrido

Después de la precarga y la demo, antes de `runtime-handoff`, sobre el mismo runtime caliente:

1. Elegir el servicio, la ruta y el estado donde el usuario ve el cambio o inicia el flujo nuevo,
   según el spec, los tickets y la demo. Preferir rutas precargadas con los datos de prueba usados
   en la demo, no estados vacíos ni 404. Si hay varios flujos, usar el primero de la demo y
   nombrar los demás en el mensaje final. Sin tickets revisables por UI, usar la página principal
   de la app afectada.
2. Escribir bajo `.local-runtime/issue-delivery-orchestrator/<run-id>/desktop-browser/` un script
   Node con Playwright del repositorio (`require('playwright')`), ejecutado como
   `node <script> <cdpUrl> <url>`. Debe conectarse con `chromium.connectOverCDP(cdpUrl)`, usar la
   página abierta del primer contexto, navegar a `url` y:
   - iniciar sesión con el usuario de prueba mediante el formulario real sólo si la app redirige
     al login (el perfil puede conservar una sesión anterior), sin atajos ni cambios de
     autenticación;
   - interactuar hasta el punto de partida (registro, pestaña o modal donde empieza el flujo), sin
     completar el flujo ni modificar datos más allá de lo necesario; debe poder repetirse;
   - esperar a que ese estado sea visible, terminar con `browser.close()` (sobre CDP sólo
     desconecta, la ventana sigue abierta) y salir con código distinto de cero si no lo alcanza.
3. Ejecutar:

   ```bash
   python3 <plugin-root>/scripts/issue-delivery <issue> desktop-prepare --service <servicio> --path </ruta> --replay <script>
   ```

   El motor ensaya el script en Chrome headless con un perfil temporal, del tamaño del escritorio
   de Conductor, y lo registra para el SHA y runtime finales. Si el ensayo falla, corregir el
   script y repetir. Si no se logra, informarlo en el mensaje final sin bloquear el handoff.

Tras una reparación o un reset, prepararlo de nuevo. `runtime-restore` conserva SHA y runtime, así
que el recorrido preparado sigue siendo válido.

## Mensaje final del run

Agregar una línea informativa, sin preguntar ni esperar respuesta: el punto de partida preparado y
que, para probarlo en el escritorio, el usuario puede abrirlo desde la app de Conductor y pedir que
se prepare la app allí. Si la preparación falló, decirlo.

## A pedido del usuario: abrir la ventana

Cuando el usuario lo pida tras el handoff (estado `awaiting_manual_review` o `completed_preserved`):

1. Si los servicios del runtime no responden porque el workspace se suspendió, restaurarlo primero
   según la sección de restauración y repetir precarga y handoff.
2. Ejecutar:

   ```bash
   python3 <plugin-root>/scripts/issue-delivery <issue> desktop-open
   ```

   El motor exige el escritorio activo (`DISPLAY=:1`), cierra la ventana anterior del run, abre
   Chrome maximizado con un perfil dedicado del run y ejecuta el recorrido preparado en esa ventana.
   - `REACHED`: la ventana quedó en el punto de partida.
   - `OPENED_WITHOUT_STARTING_POINT`: la ventana quedó abierta pero el recorrido falló; revisar el
     log, corregir el script, ensayarlo otra vez con `desktop-prepare` y repetir `desktop-open`.
   - Si el escritorio no está activo, el comando se bloquea: pedir al usuario que lo abra desde la
     app y volver a intentarlo cuando avise.
3. Responder con la URL, el punto de partida alcanzado y si la sesión quedó iniciada.

No lanzar Chrome en el escritorio por otra vía ni iniciar un servidor de display propio.

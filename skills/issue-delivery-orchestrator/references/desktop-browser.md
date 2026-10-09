# Ventana de prueba en el escritorio de Conductor Cloud

Sólo para `developmentMode=conductor-cloud`, en `full` y `manual-runtime`. El usuario abre el
escritorio del workspace desde la app de Conductor y prueba el cambio en una ventana de Chrome
de la propia máquina, sin reenviar puertos. Esta ventana no revisa ni aprueba historias.

## Cuándo abrirla

Después de la precarga y la demo final, antes de `runtime-handoff`, sobre el mismo runtime y SHA.
`runtime-handoff` se bloquea en `conductor-cloud` si la ventana no está registrada para el runtime
final o si su proceso ya no corre. Tras una reparación, un reset o `runtime-restore`, abrirla otra
vez. Aplica aunque no haya tickets revisables por UI: elegir la página principal de la app afectada.

## Elegir la página

- Elegir el servicio y la ruta donde el usuario ve el cambio o inicia el flujo nuevo implementado,
  según el spec, los tickets y la demo. Si hay varios flujos, usar el primero del recorrido de la
  demo y nombrar los demás en el mensaje final.
- Usar una ruta con datos de prueba existentes en el runtime final (por ejemplo, el registro usado
  en la demo), no una que muestre un estado vacío o un 404.
- No abrir una URL arbitraria: el motor construye la URL desde el manifiesto del runtime activo.

## Preparar la sesión

El motor usa un perfil de Chrome dedicado en
`.local-runtime/issue-delivery-orchestrator/<run-id>/desktop-browser/profile`. Si la página
requiere login:

1. Abrir ese perfil con Playwright y el Chrome del workspace (contexto persistente, headless).
2. Iniciar sesión con el usuario de prueba mediante el formulario real de login, por la misma URL
   del manifiesto, y navegar a la página elegida. No crear la sesión por atajo ni alterar la
   autenticación de la app.
3. Cerrar el navegador y comprobar, reabriendo el perfil, que la página carga sin redirigir al
   login. Cerrarlo nuevamente: el motor rechaza un perfil en uso.

Si la sesión no sobrevive al reabrir el perfil, se pueden usar mecanismos de Chrome sobre el
perfil, pero nunca cambiar la app. Si aun así no se conserva, abrir la ventana igualmente y avisar
en el mensaje final que el usuario debe iniciar sesión, con las credenciales de prueba.

## Abrir la ventana

```bash
python3 <plugin-root>/scripts/issue-delivery <issue> desktop-browser --service <servicio> --path </ruta>
```

El motor lanza un proceso desacoplado y registrado que espera el escritorio de Conductor
(`DISPLAY=:1`, iniciado cuando el usuario lo abre desde la app) y entonces se convierte en Chrome,
maximizado y con la URL elegida.

- `OPENED`: el escritorio ya estaba activo y Chrome se abrió.
- `PENDING`: el escritorio aún no está activo; la ventana aparecerá en cuanto el usuario lo abra.

Ambos estados son válidos. Volver a ejecutar el comando cierra la ventana anterior del run. No
lanzar Chrome en el escritorio por otra vía ni iniciar un servidor de display propio.

## Mensaje final

Indicar que el cambio puede probarse en el escritorio del workspace, la URL y la página abiertas,
el estado (`OPENED` o `PENDING`, con la indicación de abrir el escritorio desde la app) y si la
sesión ya está iniciada o hay que iniciarla.

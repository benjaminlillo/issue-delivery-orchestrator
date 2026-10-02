# Precarga de páginas del handoff final

Las apps corren en modo desarrollo y compilan cada página la primera vez que se pide. Precargar
las páginas relevantes deja esa compilación hecha antes de entregar el runtime al usuario. La
precarga no es una revisión UI: no produce evidencia, no aprueba historias ni juzga el diseño.

## Cuándo

En todo handoff final (`manual-runtime` y `full`): después de `runtime-reset`, de levantar las
apps y de verificar que respondan, y antes de `runtime-handoff`. Un reset o reinicio posterior
pierde la compilación: repetir la precarga sobre el runtime nuevo.

## Elegir las páginas

1. Tomar primero las pantallas de las historias `UI` y criterios de aceptación del spec, y de los
   escenarios `REPAIR-<n>` del run.
2. Completar con las rutas modificadas por el run: listar
   `git diff --name-only origin/<target>...HEAD` y convertir cada `apps/<app>/src/app/**/page.tsx`
   en su ruta, quitando grupos `(grupo)` y slots `@slot`. Para un `layout.tsx` modificado, elegir
   una página representativa bajo él.
3. Reemplazar cada segmento dinámico (`[id]`, `[...slug]`) por un valor real de los datos de
   prueba del runtime. Sin un valor concreto la página no se compila; omitirla y anotarlo.
4. Asociar cada página al servicio del manifiesto del runtime que la sirve. Limitar a unas 10
   páginas, priorizando las de las historias.

Si el cambio no tiene páginas (por ejemplo, sólo backend), no precargar y registrar `skipReason`.

## Ejecutar

- Usar Playwright headless con la instalación que ya ofrece el repositorio y el Chrome del
  workspace, resuelto en este orden: `ISSUE_DELIVERY_BROWSER`, `google-chrome-stable`,
  `google-chrome`, `chromium`, `chromium-browser`. No instalar paquetes ni editar archivos del
  producto. Si Playwright o Chrome no están disponibles, registrar `pages: []` con `skipReason`.
- Crear el script efímero y su log bajo
  `.local-runtime/issue-delivery-orchestrator/<run-id>/validation/warmup/`.
- Iniciar sesión una vez por app con el usuario de prueba mediante el formulario real de login, en
  un contexto de navegador nuevo y por la URL `localhost` del manifiesto, como lo hará el usuario
  con sus puertos reenviados. No usar helpers que creen la sesión por atajo ni inyectar cabeceras
  HTTP (por ejemplo, `x-real-ip`). Sin sesión, el middleware redirige a `/signin` y la página no se
  compila.
- Registrar el resultado del login de cada app en `logins` (`PASS` o `FAILED` con `error`). Un login
  fallido bloquea el handoff: el runtime no es usable. Diagnosticar cómo se levantó la app; no
  debilitar la autenticación ni el código de producción.
- Procesar las apps en paralelo y, dentro de cada app, las páginas una a una: `page.goto` con un
  timeout amplio (compilar puede tardar minutos) y luego esperar un tiempo acotado a que la red
  quede inactiva, para compilar también el JavaScript del cliente y las llamadas que dispara.
- Marcar `FAILED` con `error` si la navegación falla, responde 5xx, termina en `/signin` o muestra
  el overlay de error de desarrollo. No reintentar indefinidamente ni reparar código: informar.
- Dirigir la salida al log y leer sólo el resumen.

## Recibo

Escribir `validation/warmup.json` dentro del directorio del run y pasarlo como `warmup` en el
input de `runtime-handoff`:

```json
{
  "receiptVersion": 1,
  "verifiedCommit": "<HEAD>",
  "runtimeId": "<runtime final>",
  "pages": [
    {"service": "shops-app", "path": "/workers/7", "status": "WARMED", "httpStatus": 200, "durationMs": 8200},
    {"service": "shops-app", "path": "/menu", "status": "FAILED", "httpStatus": 500, "error": "HTTP 500"}
  ],
  "logins": [
    {"service": "shops-app", "status": "PASS"}
  ]
}
```

`service` debe existir en el manifiesto del runtime. Sin páginas, incluir `"pages": []` y
`skipReason`. El motor rechaza recibos de otro SHA o runtime y exige un login `PASS` por cada app con
páginas precargadas; una página `FAILED` no bloquea el handoff.

En el mensaje final, listar cada URL precargada con su tiempo y marcar explícitamente las fallidas
y las omitidas, para que el usuario sepa cuáles todavía compilarán o fallarán al abrirlas.

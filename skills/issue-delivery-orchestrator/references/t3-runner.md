# Modo t3-runner

Aplica cuando el run se ejecuta en un runner remoto de T3 Code: un contenedor Linux sin escritorio
que T3 Code usa como entorno a través de T3 Connect. La imagen del runner exporta `T3_RUNNER=1` a
todos los agentes; esa es la única señal de detección.

## Workspace

- T3 Code crea el worktree del thread (`~/.t3/worktrees/<repo>/t3-<id>`, rama `t3/<id>`) y ejecuta
  el setup del proyecto antes de que empiece la sesión. El loop adopta ese worktree, cambia a la
  rama de Linear desde `origin/<base>` y nunca crea otro.
- Como la detección es automática, el motor exige un checkout sin cambios antes de limpiar. Si
  bloquea por cambios locales, anunciar la decisión, pedir que se preserven o limpien, o que el
  usuario elija explícitamente `modo t3-runner` para autorizar la limpieza normal.

## Reviewer

`issue-delivery-playwright-review` con Playwright headless del repositorio objetivo y el Chrome del
sistema (`google-chrome`). Es el reviewer principal y no genera `headlessAssistance`. No exportar
`DISPLAY`, no lanzar Xvfb ni navegadores con interfaz, y no usar
`desktop-prepare` ni `desktop-open`: el runner no tiene escritorio. Las apps se prueban por sus
URLs `http://127.0.0.1:<puerto>` del manifiesto del Local Runtime.

## Acceso del usuario al runtime

El usuario no puede abrir `127.0.0.1` del runner. El runner expone un único dominio público que
pasa por un gate autenticado; el gate lista los runtimes y prototipos activos y redirige al que el
usuario elija:

1. Al terminar un handoff (`manual-runtime` o `full`), ejecutar
   `preview-link --runtime <runtime-id> --app <app-principal>`. Imprime un link de login de un solo
   uso que vence en 10 minutos y que abre directamente esa app tras el login.
2. Entregar el link junto con el runtime ID y las apps levantadas, e indicar: abrir el link (sirve
   también desde el celular) y entrar con el usuario de pruebas del runtime. Para otra app del
   runtime, volver a `/__gate` y elegirla. La sesión del gate dura 7 días.
3. Si el link venció, generar otro cuando el usuario lo pida; no reutilizarlo. Con la sesión del
   gate vigente, el usuario también puede entrar directo a `/__gate`.

El login de las apps Next funciona por el dominio público porque el runner fija
`LOCAL_RUNTIME_AUTH_TRUST_HOST=1` y la app deduce su auth URL del request. Si el worktree no
contiene ese soporte, el login falla con `Untrusted auth host`: informarlo como limitación de la
base, no como fallo del cambio.

Mencionar en el handoff que el link no reemplaza la revisión del reviewer: es la superficie para la
revisión humana.

## Prototipos

`prototype-open` sirve la carpeta del prototipo en un puerto de `T3_PREVIEW_PORTS`, la registra en
`T3_PREVIEW_REGISTRY` como `<issue>-prototype` y devuelve en `url` un link de `preview-link` que
abre el prototipo directamente. Entregar ese link; el prototipo también aparece en `/__gate` bajo
"Prototipos" mientras su servidor siga activo. Cada `prototype-open` reutiliza el servidor y emite
un link nuevo. `--desktop` no existe en este modo. Si el motor bloquea porque faltan las variables
del registro, la imagen del runner está desactualizada: informarlo y no improvisar otro servidor.

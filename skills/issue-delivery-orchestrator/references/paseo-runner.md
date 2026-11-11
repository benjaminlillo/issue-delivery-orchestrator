# Modo paseo-runner

Aplica cuando el run se ejecuta en un runner remoto de Paseo: un contenedor Linux sin escritorio
donde corre el daemon de Paseo, que la app de Paseo usa como host a través de su relay. La imagen del
runner exporta `PASEO_RUNNER=1` a todos los agentes; esa es la única señal de detección.

Sigue el mismo contrato que [t3-runner.md](t3-runner.md) para reviewer, acceso del usuario al
runtime mediante `preview-link` y el gate del runner, login de las apps Next y prototipos. Cambian
sólo estos puntos:

- Paseo crea el workspace (`~/.paseo/worktrees/...` o el checkout local del proyecto) con una rama
  elegida por Paseo y ejecuta su setup antes de que empiece la sesión. Pasar ese path con
  `--worktree`. El loop cambia a la rama de Linear desde `origin/<base>` y nunca crea otro.
- Como la detección es automática, el motor exige un checkout sin cambios antes de limpiar. Si
  bloquea por cambios locales, anunciar la decisión, pedir que se preserven o limpien, o que el
  usuario elija explícitamente `modo paseo-runner` para autorizar la limpieza normal.
- `prototype-open` registra el prototipo en `PASEO_PREVIEW_REGISTRY` con un puerto de
  `PASEO_PREVIEW_PORTS`. Si faltan esas variables, la imagen del runner está desactualizada.

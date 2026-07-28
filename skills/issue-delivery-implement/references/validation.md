# Validación enfocada

## Delta del ticket

Guardar el SHA antes de editar y calcular:

```bash
git diff --name-only --diff-filter=ACDMRT <sha-inicial>...HEAD
git status --short
```

Incluir también archivos todavía no comprometidos. No usar el diff acumulado de tickets anteriores como entrada del ticket actual.

## Proyectos afectados en Nx

Usar los paths explícitos del delta:

```bash
pnpm exec nx show projects --affected --files=<path1,path2,...>
```

Nx incorpora dependientes a través del project graph. Para cada proyecto, inspeccionar sus targets:

```bash
pnpm exec nx show project <proyecto> --json
```

Ejecutar los targets existentes en lotes pequeños:

```bash
pnpm exec nx run-many --target=typecheck --projects=<lista>
pnpm exec nx run-many --target=test --projects=<lista>
```

Si un target requiere flags focalizados ya usados por el repositorio, conservar ese patrón.

## Atribución a la branch target

Ante una falla remota o dudosa, leer la branch target desde el perfil y reproducir el mismo comando
sobre su SHA exacto integrado en un checkout desechable dentro del directorio del run. Clasificar:

- `branch-caused`: sólo falla con la branch, o la branch lo agrava.
- `base-failure`: mismo fallo y firma en el target integrado.
- `unclear`: no editar a prueba y error; recopilar evidencia y bloquear si impide decidir.

No ejecutar suites globales para conseguir atribución.

# Spec y prototipo aprobados antes del run

El usuario puede aprobar el spec, los tickets y, si hay UI, el prototipo antes de iniciar el run,
por ejemplo con un agente PM. En ese caso el run no repite el grill: valida y empieza a implementar
sin esperar al usuario.

## Detectar la aprobación

Al empezar el grill de cualquier run, resolver el prefijo con
`python3 <plugin-root>/scripts/issue-delivery config` y ejecutar
`codex-linear issue spec-approval <issue> --prefix <prefix>`.

Con `approved: true`, el comentario de `approval.body` registra que el usuario aprobó ese spec y ese
desglose exactos. Su línea `Prototipo:` dice qué pasa con el prototipo:

- `Prototipo: aprobado`: las capturas aprobadas están en la sección `## Prototipo aprobado` de la
  issue.
- `Prototipo: no (<motivo>)`: el usuario decidió no prototipar.
- Cualquier otro valor, como `Prototipo: en el run` de aprobaciones anteriores: el prototipo está
  pendiente.

Con `approved: false` y bloques ya publicados, hacer el grill normal tomándolos como base. Un hash
en `otherApprovedHashes` significa que el spec cambió después de aprobarse: decirlo en la primera
pregunta.

## Con el spec aprobado

1. No entrevistar. Leer la issue, las reglas y el código igual que en el grill.
2. Validar el spec y los tickets publicados con las validaciones de
   `issue-delivery-spec-publisher` y `issue-delivery-ticket-publisher` y los requisitos de los pasos
   4 a 6 del grill.
3. Si hay historias de UI:
   - Con `Prototipo: aprobado`, ejecutar
     `python3 <plugin-root>/scripts/issue-delivery <issue> prototype-adopt`. El motor descarga las
     capturas de la issue a `prototype/approved/` y registra el prototipo como aprobado. Implement y
     la revisión UI las usan como en cualquier run.
   - Con `Prototipo: no`, registrar la omisión con
     `prototype-approve --skip-reason "<motivo del comentario>"`.
   - Con el prototipo pendiente, seguir [prototype.md](prototype.md) con el usuario antes de
     implementar.
4. Si todo pasa, el spec y el desglose quedan aprobados. No republicarlos ni pedir otra aprobación.
   Guardar los snapshots, completar el checkpoint `grill` como indica el paso 11 del grill y
   empezar Implement en el mismo turno, sin pedir confirmación.
5. Si la validación o el prototipo obligan a cambiar el spec o los tickets, proponer el cambio al
   usuario. Con su aprobación, publicarlo con los publicadores y registrar una aprobación nueva con
   el formato de abajo. Repetir `spec-approval` hasta obtener `approved: true` con el hash actual.

## Comentario de aprobación

Publicarlo con `codex-linear comment create <issue> --body-file <ruta>`, usando el
`approvalMarker` exacto que devuelve `spec-approval`:

```md
<approvalMarker>
Spec y tickets aprobados por <nombre del usuario> el <AAAA-MM-DD>.

> <cita literal de la aprobación del usuario>

Prototipo: aprobado
```

Sin prototipo, la última línea es `Prototipo: no (<motivo>)`. Sólo registrar una aprobación que el
usuario dio de forma explícita.

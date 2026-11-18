# Blast radius de la PR

Cuando el run termina, el blast radius le dice al usuario si puede hacer merge directo o
si conviene pedir review externa. Los criterios viven en `blastRadius` del perfil.

## Cuándo

Después de `runtime-handoff`, de `lessons-learned` y de la ronda de review sobre el push de las
lecciones en un run completo, como último paso antes del mensaje final. El motor exige que la última
ronda de `wait-review` haya corrido sobre el HEAD actual y que `review-gate` pase en vivo.
Repetirlo tras cada handoff con código nuevo, por ejemplo después de reparar review humano. Un
`runtime-restore` no cambia el código y no lo requiere. El motor publica un
comentario nuevo al final de la PR y borra el anterior del mismo run, así que siempre queda uno solo
y es el último. No corre en `manual-runtime`.

## Qué decide el motor

Lo mide sobre el diff entre `origin/<target>` y el código del handoff:

- Migraciones, según `migrationPaths`.
- Código de librerías `sharedLibraries` que usan `minProducts` productos o más. En archivos de
  código sigue las declaraciones que toca el diff, y las de la librería que las referencian, hasta
  los nombres exportados. Después busca qué apps usan esos nombres, sin contar tests. Las apps se
  agrupan en productos con `productGroups`; una app sin grupo es su propio producto. Si cambia un
  archivo que no es código, como un CSS, cuenta todas las apps que importan la librería.
- Tamaño, apps y librerías tocadas, archivos de tests y SKIPs publicados.

## Qué juzga el agente

Por cada entrada de `judgedTriggers`, leer el diff y decidir si dispara. La evidencia cita
`archivo:línea` y dice en una frase qué cambia. Si no dispara, decir qué se revisó para descartarlo.

- `money`: cálculos, estados o registros de cobros, pagos, precios, comisiones o contabilidad ERP.
- `permissions`: guards, roles, sesiones, procedimientos públicos o filtros por empresa, taller,
  sucursal o centro logístico.
- `mobileContract`: endpoints, DTOs o campos que consumen versiones publicadas de `shipment-app`,
  `sales-force-app` o `warehouse-mobile`.

Ante la duda, marcarlo como disparado y explicar la duda en la evidencia. Un falso alto cuesta una
review; un falso bajo puede llegar a producción.

```json
{
  "checks": {
    "money": {"triggered": false, "evidence": "Solo cambia la tabla de pedidos en apps/shops-app/src/orders/Table.tsx:40"},
    "permissions": {"triggered": false, "evidence": "No toca guards ni filtros; el endpoint nuevo usa @Roles en orders.controller.ts:88"},
    "mobileContract": {"triggered": false, "evidence": "No cambia backends que consumen las apps móviles"}
  },
  "notes": ["Opcional: riesgo concreto que el motor no mide, como un efecto externo o un cambio de default"]
}
```

```bash
python3 <plugin-root>/scripts/issue-delivery <issue> blast-radius --input <ruta-json>
```

## Nivel

- `alto`: cualquier disparador. Recomienda pedir review externa.
- `medio`: sin disparadores, pero supera `lowRiskMaxChangedLines`, toca más de `lowRiskMaxUnits`
  apps o librerías, cambia código sin tests o tiene SKIPs. Recomienda que el usuario revise esas
  señales; la review externa es opcional.
- `bajo`: nada de lo anterior. Recomienda merge directo.

## Mensaje final

Incluir el nivel, la recomendación y los disparadores o señales con su evidencia, más el link al
comentario de la PR (`commentReference`). Si el comando se bloquea, informar el motivo; no publicar
un blast radius a mano.

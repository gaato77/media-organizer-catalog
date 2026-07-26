# Codex handoff — distribución estable del catálogo

## Rama

Trabajar exclusivamente en `codex/stable-channel-backfill` hasta abrir el PR contra `main`.

## Plan fuente de verdad

El plan completo está en el repositorio privado de la aplicación:

`gaato77/mediaOrganizerTool`

Rama:

`codex/catalog-local-integration`

Archivo:

`docs/superpowers/plans/2026-07-25-stable-channel-and-historical-backfill.md`

El handoff coordinador está en:

`docs/codex/CODEX-HANDOFF.md`

## Objetivo de esta rama

- publicar de forma durable el componente base 1950–2015 mediante GitHub Release;
- construir, validar y publicar el suplemento 2016–2025;
- mantener el componente del año vigente;
- generar punteros de componentes con tamaños y SHA-256;
- generar atómicamente `catalog/channel/stable.json`;
- garantizar que ningún canal estable referencia assets inexistentes o no validados;
- dejar CI verde y abrir un PR hacia `main`.

## Reglas

- usar worktree aislado;
- aplicar TDD tarea por tarea;
- implementador fresco y revisión separada por tarea;
- mantener ledger persistente;
- no fusionar hasta que CI y las comprobaciones de assets estén verdes;
- no cambiar el esquema SQLite 1 ni el manifest de release 1;
- GitHub Releases es el origen durable, no los artifacts temporales de Actions;
- no hardcodear un año vigente permanente;
- la primera integración de la aplicación usará paquetes completos, no deltas.

Completar este plan antes de la fase final de integración en Media Organizer.

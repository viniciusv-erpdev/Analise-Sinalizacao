# AGENTS.md

## Default operating mode

This repository is a Django application for Brazilian traffic accident analysis and spatial signaling assessment.

Keep the code as the source of truth. Documentation should help navigation, not reproduce implementation details.

Use this default reading pattern:

1. Read the request and identify the affected domain.
2. Check git status/diff only when local state matters to the task.
3. Read the directly relevant code and the matched domain file in `docs/reference/`.
4. Expand the investigation only when the code shows a dependency chain that requires it.
5. Run only the smallest relevant tests for the affected scope.

Do not read the entire project or all documentation by default.

## Permanent architecture

- `accidents/`: CSV import, validation, consolidation, analysis setup, session state.
- `analysis/`: geographical validation, clustering, historical criteria, map payloads.
- `signaling/`: persistent waypoints, interventions, PGT search, and report generation.
- `templates/` and `static/js/`: main map UI, filters, and JS behavior.
- `config/`: Django settings and URL routing.

## Working rules

- Keep Django views thin and move business logic into services/modules.
- Keep data processing separate from HTTP orchestration.
- Prefer small, direct changes over broad refactors.
- Preserve local implementation changes unless the task explicitly asks to change them.
- Treat `docs/history/` as historical context only; do not read it by default.

## Default documentation context

- This file
- `docs/project-overview.md`
- relevant file(s) in `docs/reference/`

## Tests

Validate only the affected behavior. Typical commands:

- `python manage.py check`
- `python manage.py test <app-or-test-target>`
- project-specific JS tests only when the task touches frontend logic

## Safety

- Do not delete data or migrations.
- Do not modify database schema without a clear, explicit reason.
- Do not broaden the scope to unrelated cleanup or historical rewrites.
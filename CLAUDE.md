# Verixa — Claude Code project instructions

Read `README.md` first, then `docs/CLAUDE-MASTER-PROMPT.md` and `docs/12-CLAUDE-CODE-RULES.md`.
Execute work in the order defined by `TASKS/00-MASTER-EXECUTION.md`.

## Layout
- `apps/web` — Next.js + TypeScript + Tailwind (App Router)
- `services/api` — FastAPI + SQLAlchemy 2 + Alembic (Python 3.12+)
- `packages/shared-types` — TypeScript types mirrored from the API Pydantic schemas
- `infra` — local/dev infrastructure (docker-compose, deployment config)
- `docs` — product and engineering specifications (numbered 01–12)
- `TASKS` — sequential implementation tasks (T001…T043)

## API layering (enforced by `services/api/tests/test_architecture.py`)
```
api/v1 (routes)  ->  services/*  ->  repositories (models)  |  providers (external)
schemas: API contract only.   utils: pure helpers only.   workers: job execution.
```
Routes never import providers/repositories/models. Providers never import services.
Every package's `__init__.py` carries a one-line responsibility docstring.

## Web structure (`apps/web/src`)
- `app/` — App Router routes/layouts only; no data-fetching logic inline beyond calling `lib/`
- `components/` — reusable UI (`components/ui` reserved for shadcn/ui, added when first needed)
- `lib/` — API client, env, formatting helpers
- Types come from `@verixa/shared-types`; do not redeclare API shapes locally.

## Commands
- Everything CI runs: `scripts/check.sh` or `scripts\check.ps1` (accepts `api` / `web`)
- API: `cd services/api && .venv/Scripts/activate && uvicorn app.main:app --reload`
- API checks: `cd services/api && ruff check . && ruff format --check . && mypy app tests && pytest`
- API migrations: `alembic revision --autogenerate -m "..."`, `alembic upgrade head`, `alembic check`
- Web: `cd apps/web && npm run dev`
- Web checks: `cd apps/web && npm run lint && npm run typecheck && npm run build`

## Non-negotiables
- Routes → Services → Repositories/Providers. No provider calls from routes.
- Every schema change ships with an Alembic migration.
- Local dev uses SQLite + local-dir storage; production uses PostgreSQL + S3. Models and
  migrations must work on both — see `infra/README.md` portability rules.
- Never log secrets or raw uploaded content.
- Evidence levels: VERIFIED, STRONG, PROBABLE, POSSIBLE, UNKNOWN. Never overstate.
- MVP scope is image + text only. No video/audio/mobile/extension/proprietary detector.

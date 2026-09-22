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
- `lib/` — API client, env, formatting helpers. `lib/api/client.ts` and `lib/auth/*` are server-only.
- Auth: tokens live in httpOnly cookies; `proxy.ts` refreshes/guards; server actions in `app/(auth)/actions.ts`.
  Use `getSession()` (signed_in | signed_out | unavailable) — never treat "API down" as "signed out".
- Forms with server actions: React resets uncontrolled inputs after the action settles, so any
  client-held selection (e.g. a picked file) must be re-synced on submit — see `image-upload-form.tsx`.
- Upload cap lives in two places: `VERIXA_MAX_UPLOAD_BYTES` (API) and `next.config.ts`
  `serverActions.bodySizeLimit` (web). Change both.
- Report UI: `/analyses/{id}?tab=` uses link-based tabs (`report-tabs.tsx`); sections whose
  pipeline step does not exist render `NotAvailable` — never placeholder or fabricated findings.
  Evidence level text is always visible next to its colour.
- shadcn/ui here is the base-ui flavour: link-buttons use
  `<Button nativeButton={false} render={<Link … />}>`, not `asChild` (omitting `nativeButton`
  logs an accessibility error at runtime).
- Types come from `@verixa/shared-types`; do not redeclare API shapes locally.

## Commands
- Dev API on Windows: run **without** `--reload` (uvicorn's WatchFiles reload hangs and keeps
  serving stale code). Restart the process after API changes and confirm via `/openapi.json`.
- Everything CI runs: `scripts/check.sh` or `scripts\check.ps1` (accepts `api` / `web`)
- API: `cd services/api && .venv/Scripts/activate && uvicorn app.main:app --reload`
- API checks: `cd services/api && ruff check . && ruff format --check . && mypy app tests && pytest`
- API migrations: `alembic revision --autogenerate -m "..."`, `alembic upgrade head`, `alembic check`
- Web: `cd apps/web && npm run dev`
- Web checks: `cd apps/web && npm run lint && npm run typecheck && npm run build`

## Conventions
- Services raise `app.utils.errors.*` (`NotFoundError`, `UnauthorizedError`, ...); the API layer
  renders the `{"error": {code, message, request_id}}` envelope. Never raise HTTPException in services.
- Routes get the user via `app.api.deps.CurrentUser`; ownership via
  `app.services.authorization.assert_owns_analysis` (404 for foreign resources, never 403).

## Pipeline
- New processing work = a `PipelineStep` in `services/analysis/steps.py` (name, `critical`, `run(ctx)`),
  appended to `image_pipeline_steps()`. Raise `StepFailedError(code, message)` for expected failures;
  put raw observations in the returned `details`; publish objects for later steps via `ctx.artifacts`.
- Never mark a step completed with fabricated data; return `StepOutcome.skipped(reason)` instead.
- Forensic methods live in `services/analysis/forensics_steps.py` and write only their own column of
  the `image_forensics` row via `AnalysisRepository.upsert_forensics`. Generated images go to
  `storage_keys.artifact_key(...)` and are listed in `artifacts_json` (so deletion sweeps them);
  clients only ever receive signed URLs.
- Forensic region coordinates are always in *original* pixels (methods that downscale convert
  back); map artifacts are at the method's working size. `forensic-viewer.tsx` relies on both.

## Non-negotiables
- Routes → Services → Repositories/Providers. No provider calls from routes.
- Every schema change ships with an Alembic migration.
- Local dev uses SQLite + local-dir storage; production uses PostgreSQL + S3. Models and
  migrations must work on both — see `infra/README.md` portability rules.
- Never log secrets or raw uploaded content.
- Evidence levels: VERIFIED, STRONG, PROBABLE, POSSIBLE, UNKNOWN. Never overstate.
- MVP scope is image + text only. No video/audio/mobile/extension/proprietary detector.

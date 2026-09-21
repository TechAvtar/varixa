# Verixa

Multimodal content forensics for **images and text**: provenance, metadata, hashes, forensic signals,
AI-generation indicators, source matches, timelines, and evidence-backed reports.

Core principle: distinguish **verified facts**, **strong technical evidence**, **probabilistic signals**,
and **unknown/unavailable evidence**. Never claim certainty from a probabilistic signal.

## Repository layout

```text
apps/web/               Next.js 16 + TypeScript + Tailwind (App Router)
services/api/           FastAPI + Pydantic + SQLAlchemy 2 + Alembic
packages/shared-types/  TypeScript types mirrored from API schemas
infra/                  Local/dev infrastructure and deployment config
docs/                   Product + engineering specifications (01â€“12)
TASKS/                  Sequential implementation tasks (T001â€“T043)
```

## Prerequisites

- Node.js 22+ (see `.nvmrc`)
- Python 3.12+
- No database or storage service needed locally: the API defaults to SQLite and a local
  storage directory under `services/api/data/`. PostgreSQL and S3-compatible storage are
  opt-in via environment variables (see below).

## Local development

### API

```bash
cd services/api
python -m venv .venv
.venv/Scripts/activate        # Windows; use `source .venv/bin/activate` elsewhere
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head            # creates/migrates data/verixa.db (SQLite by default)
uvicorn app.main:app --reload --port 8000
```

Schema changes: edit `app/models/`, then `alembic revision --autogenerate -m "describe change"`,
review the generated file in `alembic/versions/`, and run `alembic upgrade head`. `alembic check`
fails if models and migrations have drifted. For PostgreSQL install the extra:
`pip install -e ".[dev,postgres]"`.

Health check: <http://localhost:8000/api/v1/health> Â· OpenAPI docs: <http://localhost:8000/docs>

### Web

```bash
npm install                    # from repo root (workspaces)
cp apps/web/.env.example apps/web/.env.local
npm run dev:web
```

Open <http://localhost:3000>. The home page shows live API status (or an explicit "unavailable" state).

## Quality checks

| Target | Command |
| ------ | ------- |
| API    | `cd services/api && ruff check . && ruff format --check . && mypy app tests && pytest` |
| Web    | `npm run lint && npm run format:check && npm run typecheck && npm run build` |

Or run everything at once: `scripts/check.sh` (bash) / `scripts\check.ps1` (PowerShell), optionally
with `api` or `web` to limit scope.

CI (`.github/workflows/ci.yml`) runs the same checks plus a gitleaks secret scan on every push and
pull request. Dependabot keeps Actions, npm, and pip dependencies current.

## Configuration

All configuration is via environment variables; see the `.env.example` files. Never commit `.env`.

| Variable | Where | Purpose |
| -------- | ----- | ------- |
| `VERIXA_ENVIRONMENT` | API | `development` \| `test` \| `production` (production disables `/docs`) |
| `VERIXA_DEBUG` | API | FastAPI debug mode |
| `VERIXA_CORS_ORIGINS` | API | JSON list of allowed browser origins |
| `VERIXA_DATA_DIR` | API | Root for local runtime data (default `./data`, git-ignored) |
| `VERIXA_DATABASE_URL` | API | SQLAlchemy URL. Default: SQLite at `${VERIXA_DATA_DIR}/verixa.db`. Use `postgresql+asyncpg://…` for PostgreSQL |
| `VERIXA_STORAGE_BACKEND` | API | `local` (default, files under `${VERIXA_DATA_DIR}/storage`) or `s3` |
| `VERIXA_STORAGE_LOCAL_PATH` | API | Override the local storage directory |
| `VERIXA_S3_ENDPOINT_URL`, `VERIXA_S3_REGION`, `VERIXA_S3_BUCKET`, `VERIXA_S3_ACCESS_KEY_ID`, `VERIXA_S3_SECRET_ACCESS_KEY` | API | Required only when `VERIXA_STORAGE_BACKEND=s3`; the bucket must be private |
| `NEXT_PUBLIC_API_BASE_URL` | Web | API origin used by the web app |

## Working with Claude Code

Start with `CLAUDE.md`, then `docs/CLAUDE-MASTER-PROMPT.md`. Tasks execute in the order given by
`TASKS/00-MASTER-EXECUTION.md`.

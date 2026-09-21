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
docs/                   Product + engineering specifications (01–12)
TASKS/                  Sequential implementation tasks (T001–T043)
```

## Prerequisites

- Node.js 22+ (see `.nvmrc`)
- Python 3.12+
- PostgreSQL (from T005 onward)

## Local development

### API

```bash
cd services/api
python -m venv .venv
.venv/Scripts/activate        # Windows; use `source .venv/bin/activate` elsewhere
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Health check: <http://localhost:8000/api/v1/health> · OpenAPI docs: <http://localhost:8000/docs>

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
| API    | `cd services/api && ruff check . && ruff format --check . && mypy app && pytest` |
| Web    | `npm run lint && npm run format:check && npm run typecheck && npm run build` |

CI runs the same checks on every push and pull request (`.github/workflows/ci.yml`).

## Configuration

All configuration is via environment variables; see the `.env.example` files. Never commit `.env`.

| Variable | Where | Purpose |
| -------- | ----- | ------- |
| `VERIXA_ENVIRONMENT` | API | `development` \| `test` \| `production` (production disables `/docs`) |
| `VERIXA_DEBUG` | API | FastAPI debug mode |
| `VERIXA_CORS_ORIGINS` | API | JSON list of allowed browser origins |
| `NEXT_PUBLIC_API_BASE_URL` | Web | API origin used by the web app |

## Working with Claude Code

Start with `CLAUDE.md`, then `docs/CLAUDE-MASTER-PROMPT.md`. Tasks execute in the order given by
`TASKS/00-MASTER-EXECUTION.md`.

# Verixa specifications

Reading order: `01-PRODUCT-SCOPE.md` → `12-CLAUDE-CODE-RULES.md`, then `CLAUDE-MASTER-PROMPT.md`.
Implementation tasks live in `../TASKS/`.

## Progress log

| Task | Status | Notes |
| ---- | ------ | ----- |
| T001 Bootstrap | done | Monorepo, FastAPI `/api/v1/health`, Next.js home page with API status, lint/type/test/build tooling, GitHub Actions CI |
| T002 Dev environment | done | Env-driven config; SQLite + local-dir storage by default (no Docker); PostgreSQL/S3 opt-in; `.env.example`; portability rules in `infra/README.md` |
| T003 Repository structure | done | Package responsibility docstrings; layering rules enforced by `tests/test_architecture.py`; web structure documented in `CLAUDE.md` |
| T004 CI | done | Secret scan (gitleaks) + API + web jobs; Dependabot; `scripts/check.{sh,ps1}` mirror CI locally |
| T005 Database | done | Async SQLAlchemy 2 engine/session; models users, analyses, analysis_files, evidence, provider_calls; Alembic (SQLite batch mode, PG JSONB variant); `/health` reports DB readiness |

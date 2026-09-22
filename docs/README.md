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
| T006 Authentication | done | Argon2id passwords; JWT access + rotating hashed refresh tokens (`user_sessions`); `/auth/*` routes; `CurrentUser` dependency; ownership helper; error envelope + request ids |
| T007 Storage | done | `ObjectStorage` interface; local filesystem adapter with HMAC-signed download route; S3 adapter (boto3, optional extra); key validation + layout helpers |
| T008 Analysis CRUD | done | `AnalysisService` (create, owner-scoped get/list/counts, guarded status transitions, soft delete + storage cleanup); `GET/DELETE /analysis`, `/analysis/counts`; enums moved to `app/enums.py` |
| T009 Dashboard | done | shadcn/ui; register/login/logout via server actions + httpOnly cookies; `proxy.ts` token refresh + route guarding; dashboard with counts, recent analyses, loading/empty/error states (API-down state verified) |
| T010 Image upload | done | `POST /analysis/image`: chunked size cap, magic-byte + Pillow format check, header dimension cap, verify + decode, SHA-256, private storage, no row on rejection; web: drag-and-drop upload form with preview/details, analysis detail page. **Phase 1 complete.** |

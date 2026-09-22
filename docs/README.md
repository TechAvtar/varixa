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
| T011 Image validation | done | Validation hardened (frame count recorded; Pillow bomb guard mapped) and formalised as the `validate` pipeline step; step framework (`PipelineRunner`, `AnalysisStep` table + migration, `Dispatcher`); detail page shows real step status |
| T012 Hashing | done | `services/image/hashing.py`: SHA-256, MD5 (compat), aHash/dHash/pHash (numpy DCT, imagehash-compatible), Hamming distance; committed fixtures + golden-value tests; `hashing` pipeline step records values in step details |
| T013 Metadata | done | ExifTool adapter (stdin, fixed args, timeouts, size caps) + Pillow fallback behind `MetadataExtractor`; normaliser with tz-aware timestamp parsing; `image_metadata` table + migration; `metadata` step; `GET /analysis/{id}/metadata`; metadata card with limitations on the detail page |
| T014 C2PA | done | c2patool 0.9.12 adapter (private temp file, fixed args, timeout, size cap) + Null inspector; normaliser (presence/validity/signer/actions/authors/validation codes); `image_provenance` table + migration; `provenance` step; `GET /analysis/{id}/provenance`; provenance card with evidence-level wording |
| T015 Fingerprints | done | `image_fingerprints` table + migration; `hashing` step persists idempotently; `services/image/similarity.py` exact/near comparison; `GET /analysis/{id}/fingerprints` with owner-scoped duplicates; fingerprints card |
| T016 Image report UI | done | Tabbed report (Overview / Metadata / Provenance / AI / Forensics / Matches / Timeline) with URL-addressable, link-based tabs; header evidence summary; Fact → Signal → Interpretation → Unknown overview built from preliminary deterministic evidence (`lib/evidence.ts`, per docs/07 initial rules); evidence cards with level, source, limitation; raw JSON viewers; honest "not available" states. **Phase 2 complete.** |
| T017 Text analysis | done | `POST /analysis/text` (verbatim original in private storage), text pipeline (`normalize`, `language`, `statistics`), `text_analysis` table + migration, `GET /analysis/{id}/text`; paste-text form (mode switch on New analysis), text stats card and text evidence on the report |
| T018 Text fingerprints | done | `services/text/fingerprints.py` (exact/normalised/canonical SHA-256, deterministic MinHash, Jaccard estimate); `text_fingerprints` table + migration; `fingerprints` text step; `/fingerprints` type-aware with owner-scoped exact/normalised/canonical/near matches; text fingerprints card on the Matches tab |
| T019 AI detector interface | done | `providers/ai`: `AIDetector` protocol, `DetectionResult`, threshold→label mapping, `MockAIDetector`, `DetectionCache` + in-memory LRU + `CachedAIDetector`; `ai_detections` table + migration; shared `ai` step (skipped when no provider); `GET /analysis/{id}/ai`; AI tab card with score meter, thresholds and limitations |
| T020 Source search interface | done | `providers/search`: `ImageSourceSearch` / `TextSourceSearch` protocols, `SourceMatch`/`SearchResult`, mock adapters; deterministic distinctive-phrase selection; `reverse_matches` + `source_search_runs` tables + migration; shared `search` step (skipped when none); `GET /analysis/{id}/matches`; source matches card and evidence on the Matches tab |

# Verixa MVP release checklist (T043)

Use this list for every release candidate. Every line must be **green** and dated; a line that
cannot be checked is a release blocker, not a skip. The first run (private beta, 2026-09-24) is
recorded at the end.

## 1. Code and tests

- [ ] `scripts/check.sh` (or `scripts\check.ps1`) is green locally: ruff, ruff format, mypy
      (strict), pytest; eslint, prettier, tsc, `next build`.
- [ ] GitHub Actions is green on the release commit: Secret scan, API, Web, E2E (Playwright),
      Container images (build + smoke tests).
- [ ] `alembic upgrade head` and `alembic check` pass against a **PostgreSQL** database, not only
      SQLite (`VERIXA_DATABASE_URL=postgresql+asyncpg://…`).
- [ ] No test is skipped or marked flaky without a linked reason.

## 2. Security and privacy (docs/09)

- [ ] `python -m app.preflight` exits 0 with the production environment file
      (`VERIXA_ENVIRONMENT=production`): no debug, PostgreSQL, S3, https origins, metrics token,
      32+ character secret.
- [ ] `git ls-files | grep -i '\.env'` lists only `*.env.example`; gitleaks CI job green.
- [ ] `npm audit --omit=dev` and `pip-audit` report no known vulnerabilities (or each finding
      has a written risk acceptance).
- [ ] Response headers on any API route: `Content-Security-Policy: default-src 'none'; …`,
      `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
      `Cache-Control: no-store`, `Strict-Transport-Security` (production only).
- [ ] Web headers (`next.config.ts`) present on `/`: CSP `frame-ancestors 'none'`, nosniff,
      DENY, HSTS in production.
- [ ] Ownership: another account gets **404** (never 403) for someone else's analysis, report
      and delete.
- [ ] Throttling: repeated failed logins return **429** with `Retry-After`; registration per
      address is limited.
- [ ] Bucket is private (no public-read policy); clients only ever receive short presigned URLs
      (`VERIXA_SIGNED_URL_TTL_SECONDS`, default 300 s).
- [ ] Logs contain ids, statuses and durations only. Spot-check one analysis's log lines for
      filenames, text content, emails or tokens: none.
- [ ] Provider allowlist (`VERIXA_OUTBOUND_ALLOWED_HOSTS`) lists only the providers in use.

## 3. Core user flows (run against the release candidate)

- [ ] Register, sign out, sign in; wrong password and unknown email give the same message.
- [ ] Image upload (JPEG with EXIF): all 15 pipeline steps finish (`completed` or a stated
      `skipped` reason, never `failed` on a valid file); metadata, fingerprints, forensics
      (maps + regions), AI, matches, evidence, timeline, synthesis, overview render.
- [ ] Text analysis: statistics, language, fingerprints, evidence; empty text is refused.
- [ ] PDF export: report listed, downloadable through a signed link, sha256 matches the record,
      page count > 0, disclaimer on the last page.
- [ ] Keep / release; delete removes the listing, the report and every stored object (signed
      links return 404 afterwards).
- [ ] Dashboard usage card matches `GET /usage`.

## 4. Report quality (docs/07 evidence principles)

- [ ] Every evidence item has a level from {VERIFIED, STRONG, PROBABLE, POSSIBLE, UNKNOWN},
      `refs` to raw observations, and a `limitation` unless VERIFIED.
- [ ] No AI-detection item is VERIFIED or STRONG; the AI section says it is never proof.
- [ ] Sections whose step did not run show "not available", never placeholder findings.
- [ ] The LLM interpretation cites existing evidence ids only (grounding), carries no level of
      its own, and is marked stale when evidence changes.
- [ ] Timeline events come from recorded times only (raw time + tz flag visible).
- [ ] Mock providers are **not** configured in production (`VERIXA_AI_DETECTOR_PROVIDER`,
      `VERIXA_SOURCE_SEARCH_PROVIDER`, `VERIXA_LLM_PROVIDER` are `none` or a real adapter); the
      landing page lists the configured providers.

## 5. Failure handling

- [ ] Non-image upload, oversize upload, over-pixel image: 4xx with the error envelope
      (`error.code`, `error.message`, `error.request_id`), nothing created.
- [ ] API down: the web app shows "unavailable" states, never "signed out".
- [ ] A failing non-critical pipeline step is recorded on the analysis and the rest completes.
- [ ] `GET /health` reports `degraded` when the database or the bucket is unreachable;
      `GET /health/live` still answers.

## 6. Retention and deletion (docs/09)

- [ ] `python -m app.workers.retention` (or the in-process sweeper) on a backdated analysis:
      `content_purged_at` set, stored objects removed, provider raw responses cleared,
      soft-deleted rows purged after the grace period, old signed links dead, the record
      itself still listed with the purge marker.
- [ ] Retention settings in the production env file match the privacy notice
      (`VERIXA_RAW_CONTENT_RETENTION_HOURS`, `VERIXA_PROVIDER_RESPONSE_RETENTION_DAYS`,
      `VERIXA_DELETED_RECORD_GRACE_DAYS`, `VERIXA_ANALYSIS_RETENTION_DAYS`).

## 7. Deployment and operations (T042, infra/README.md)

- [ ] Both images build from the release commit; `docker compose … up -d --build` brings up
      db, migrate (exit 0), api (healthy), web (healthy), proxy (certificate issued).
- [ ] `curl https://<host>/api/v1/health` returns `status: ok` with the storage probe `ok`.
- [ ] Backups: PostgreSQL volume/`pg_dump` and bucket versioning or replication configured;
      restore rehearsed once.
- [ ] `/metrics` reachable from the private network with the bearer token only; log shipping
      configured for JSON logs.
- [ ] Rollback plan: previous image tag noted; migrations of this release are forward-only and
      reviewed.

## 8. Documentation

- [ ] README, `infra/README.md`, `docs/README.md` progress log and `CLAUDE.md` describe the
      shipped behaviour; environment tables list every variable in `.env.example`.
- [ ] Known limitations below are current.

## Known limitations (private beta)

- AI-generation detection and reverse/source search ship with `none`/`mock` adapters only;
  real providers are added as adapters under `providers/ai` and `providers/search`.
- Login/registration throttling counts per API process; use one worker per container and scale
  with replicas.
- The retention sweeper runs inside the API process; with several replicas keep one sweeper.
- Forensic methods are heuristics (ELA, compression, ghosts, thumbnail, resampling, noise,
  copy-move); they reach STRONG only when independent families agree, never VERIFIED.
- Single-host compose deployment; no autoscaling, no multi-region.

---

## Acceptance run 1 — private beta candidate, 2026-09-24

Commit range `97836e0`…`HEAD` (T039–T043). Local machine: Windows 11, Python 3.14, Node 24;
GitHub Actions: Ubuntu, Python 3.12.

| Area | Result | Evidence |
| ---- | ------ | -------- |
| Lint / format / types / unit + integration tests | pass | ruff, ruff format, mypy strict, **477 API tests** locally; CI API job green |
| Web lint / prettier / tsc / build | pass | local and CI Web job |
| E2E (Playwright, 12 specs) | pass | CI E2E job green on `d4099a3`; local runs green after the blank-secret fix and the cold-start wait fix (below) |
| Container images | pass | CI `images` job: both images build; preflight exit code, API liveness and web landing page smoke tests |
| Secret scan | pass | gitleaks CI job; only `*.env.example` tracked |
| Dependency audit | pass | `npm audit` (prod and all): 0 vulnerabilities; `pip-audit` on the API environment: none known |
| Live core flows (60 scripted checks against the dev API with mock providers) | 60/60 | register/login, security headers, image pipeline (15 steps, 4 forensic artifacts downloadable), evidence rules (12 items, all with refs and limitations, AI never above PROBABLE), overview + methodology, synthesis grounded, timeline, PDF (10 pages, sha256 matches), text flow, usage counters, error envelopes, 401/404 paths, ownership 404s, login throttling 429, keep/release, delete + dead links |
| Retention sweep | pass | scratch instance: backdated analysis purged (`content_purged_at`), storage emptied, provider raw responses cleared, soft-deleted row purged after grace, old links 404, record still listed with the marker |
| Documentation | pass | README (deployment, configuration), infra/README, docs/README progress log, CLAUDE.md |

### Defects found and fixed during the run

1. **Blank `VERIXA_SECRET_KEY=` broke every login** (HTTP 500 "HMAC key must not be empty"):
   `.env.example` ships the key blank and a developer's `.env` copied it. Development and test
   now fall back to the built-in default when the value is blank; production still refuses it.
   The E2E API gets its own key so specs never depend on a developer's `.env`.
2. **Auth spec timed out on a slow machine**: the first dashboard render after a cold start
   took longer than the spec's default 10 s wait (CI was green). The wait now matches the 30 s
   cold-start allowance the helpers already use.
3. **Web image build failed on CI**: `apps/web/public` is empty and therefore absent from a git
   checkout; the Dockerfile now creates it before the build.

### Not verified in this run (must be done on the production candidate)

- Migrations against PostgreSQL, S3 bucket policy, TLS issuance, backups and restore rehearsal:
  they need the real infrastructure (items 1.3, 2.9, 7.x).

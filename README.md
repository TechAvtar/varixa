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
- [ExifTool](https://exiftool.org) for full metadata coverage (`winget install OliverBetz.ExifTool`
  on Windows, `apt install libimage-exiftool-perl` on Debian/Ubuntu). Without it the API falls
  back to Pillow and marks metadata as reduced-coverage.
- [c2patool](https://github.com/contentauth/c2patool) for Content Credentials (C2PA) inspection —
  download the release binary; without it provenance is reported as *not inspected*.
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

Open <http://localhost:3000>. Routes: `/` (status + sign-in), `/register`, `/login`, `/dashboard`,
`/analyses/new` (drag-and-drop image upload), `/analyses/{id}?tab=` (tabbed report: overview,
metadata, provenance, ai, forensics, matches, timeline). Until the server-side evidence engine
lands, the overview's evidence cards are derived client-side from the deterministic step results
(`apps/web/src/lib/evidence.ts`) and labelled preliminary.

The web app never exposes tokens to the browser: server actions call the API and store the
access/refresh tokens in httpOnly cookies; `src/proxy.ts` refreshes the access token (rotating the
refresh token) before protected pages render and redirects guests to `/login`. Server components
call the API with `authedRequest()` from `src/lib/auth/session.ts`. UI primitives are shadcn/ui
(`src/components/ui`, base-ui `render` prop instead of `asChild`).

## Quality checks

| Target | Command |
| ------ | ------- |
| API    | `cd services/api && ruff check . && ruff format --check . && mypy app tests && pytest` |
| Web    | `npm run lint && npm run format:check && npm run typecheck && npm run build` |

Or run everything at once: `scripts/check.sh` (bash) / `scripts\check.ps1` (PowerShell), optionally
with `api` or `web` to limit scope.

CI (`.github/workflows/ci.yml`) runs the same checks plus a gitleaks secret scan on every push and
pull request. Dependabot keeps Actions, npm, and pip dependencies current.

## Authentication

Email + password. Passwords are stored as Argon2id hashes. Login returns a short-lived JWT access
token and an opaque refresh token; refresh tokens are stored hashed, rotated on every use and
revocable, so logout takes effect immediately.

| Endpoint | Purpose |
| -------- | ------- |
| `POST /api/v1/auth/register` | Create an account (`email`, `password` 10–128 chars, optional `name`) |
| `POST /api/v1/auth/login` | Returns `{access_token, refresh_token, token_type, expires_in}` |
| `POST /api/v1/auth/refresh` | Rotate a refresh token; the old one stops working |
| `POST /api/v1/auth/logout` | Revoke the current session (Bearer) |
| `GET /api/v1/auth/me` | Current user (Bearer) |

Every error uses one envelope: `{"error": {"code", "message", "request_id"}}`; the id is also
returned in the `X-Request-ID` response header. Analysis endpoints must call
`services.authorization.assert_owns_analysis`, which answers 404 for both missing and foreign
resources.

## Analyses

| Endpoint | Purpose |
| -------- | ------- |
| `POST /api/v1/analysis/image` | Multipart `file` (+ optional `title`). Returns `201 {id, status, type}` |
| `POST /api/v1/analysis/text` | JSON `{text, title?}`; original stored verbatim; returns `201 {id, status, type}` |
| `GET /api/v1/analysis/{id}/text` | Excerpts, normalisation report, language guess, statistics, structure, limitations |
| `GET /api/v1/analysis?page=&page_size=` | Caller's analyses, newest first (soft-deleted hidden) |
| `GET /api/v1/analysis/counts` | `{total, image, text}` for the dashboard |
| `GET /api/v1/analysis/{id}` | One analysis; 404 if missing or owned by someone else |
| `GET /api/v1/analysis/{id}/metadata` | Normalised + raw metadata with plain-language limitations |
| `GET /api/v1/analysis/{id}/provenance` | C2PA summary, manifests, validation status, limitations |
| `GET /api/v1/analysis/{id}/ai` | AI-detector signal with provider/model/version, thresholds, evidence level, raw response |
| `GET /api/v1/analysis/{id}/matches` | External source / reverse-image matches with queried phrases and limitations |
| `GET /api/v1/analysis/{id}/provider-calls` | Audit trail: provider, operation, model/version, status, latency, request hash, estimated cost, bounded response/error |
| `GET /api/v1/analysis/{id}/fingerprints` | Hashes plus exact/near duplicates among the caller's analyses |
| `DELETE /api/v1/analysis/{id}` | Soft delete (record kept for audit) and remove stored files |

Status lifecycle: `queued → processing → completed | failed`; illegal moves return
`409 INVALID_TRANSITION`. Text creation arrives with T017.

### Image upload rules

The filename and client MIME type are never trusted. An upload is accepted only if all pass:

1. size ≤ `VERIXA_MAX_UPLOAD_BYTES` (read in 1 MB chunks; overflow → `413 PAYLOAD_TOO_LARGE`)
2. magic bytes identify JPEG, PNG, WebP or TIFF and match what Pillow decodes
3. header dimensions ≤ `VERIXA_MAX_IMAGE_PIXELS` (checked before decoding; guards decompression bombs)
4. `Image.verify()` and a full decode succeed (malformed/truncated → `422 INVALID_FILE`)

Only then is the original stored (private key `uploads/{user}/{analysis}/{sha256}.{ext}`) and the
analysis row committed; a rejected file leaves no record. `GET /analysis/{id}` returns a `file`
block with the detected type, size, dimensions and SHA-256.

### Forensics (heuristics)

Forensic methods run as non-critical pipeline steps and write into one `image_forensics` row per
analysis (one JSON column per method: `{method, version, applicable, observation, confidence,
limitations, ...metrics}`). Visualisations are stored as private artifacts under
`artifacts/<user>/<analysis>/` and served through short-lived signed URLs from
`GET /analysis/{id}/forensics`. Every method is labelled a heuristic and never counts as proof.

- **ELA** (`services/image/ela.py`, JPEG only): re-save at `VERIXA_ELA_QUALITY`, per-pixel error,
  16 px block statistics, outlier blocks above `VERIXA_ELA_OUTLIER_SIGMA`, connected regions in
  original pixel coordinates, and an amplified difference map (`ela.png`). A localised pattern
  is `anomaly: true` and surfaces as POSSIBLE at most (docs/07). Other formats are recorded as
  not applicable, not as clean.

- **Compression** (`services/image/compression.py`, any format): JPEG encoding facts read from
  the headers (estimated IJG quality, standard vs custom tables, chroma subsampling,
  progressive/baseline, JFIF/Adobe markers) plus an 8×8 block-grid measurement. A second grid
  offset from the file's block boundaries (`anomaly`) or a JPEG grid inside a lossless file
  (`prior_jpeg_grid`) surfaces as POSSIBLE; encoding facts alone are UNKNOWN-level context.
  Threshold: `VERIXA_COMPRESSION_GRID_MIN_STRENGTH`.

- **Resampling** (`services/image/resampling.py`, any format): Kirchner-style fixed-predictor
  residual, probability map and averaged 2D spectrum over up to six 512 px tiles (the image is
  never resized first). Isolated peaks above `VERIXA_RESAMPLING_MIN_PEAK_RATIO`, with DC, the
  Nyquist line and JPEG multiples of 1/8 masked, mean the picture was rescaled or rotated at
  some point (`detected`, POSSIBLE). Global only; routine resizing leaves the same trace.

- **Noise** (`services/image/noise.py`, any format): per-block noise sigma from a high-pass
  residual (robust MAD), compared only across the least-textured 70% of blocks (texture is
  measured on an 8× downsample so noise itself does not count as texture). Compact clusters
  more than `VERIXA_NOISE_OUTLIER_K` × IQR (with absolute and relative floors) from the
  baseline are `anomaly` → POSSIBLE. A block-level noise map is stored as `noise.png`.

- **Copy-move** (`services/image/copy_move.py`, any format): block matching at every pixel
  position of a ≤ `VERIXA_COPY_MOVE_MAX_SIDE` working copy (integral-image 4×4 pooled
  features, quantised, packed and sorted; near-identical sorted neighbours become candidate
  pairs). A displacement shared by ≥ `VERIXA_COPY_MOVE_MIN_MATCHES` spatially coherent pairs at
  least `VERIXA_COPY_MOVE_MIN_SHIFT` px apart is `detected` → POSSIBLE. Translated copies only;
  flat blocks excluded; mask of source/target blocks stored as `copy_move.png`.

### Evidence engine

`services/evidence/engine.py` is a pure rules module: it reads the rows every pipeline step
persisted (file, metadata, provenance, fingerprints + account-level similarity, text statistics,
AI detection, source search, forensics, provider calls) and emits `EvidenceDraft` records with a
stable `rule` id, category, level, kind (`fact` / `signal` / `unknown` / `conflict`), claim,
source, confidence, limitation and `refs` to the raw observations (`step:`, `provider_call:`,
`row:`). Levels follow the docs/07 table; thresholds come from `EvidenceThresholds`
(`VERIXA_AI_SCORE_*`, `VERIXA_FINGERPRINT_NEAR_THRESHOLD`, `VERIXA_TEXT_NEAR_THRESHOLD`,
`VERIXA_LANGUAGE_PROBABLE_CONFIDENCE`, `VERIXA_FORENSIC_FAMILIES_FOR_STRONG`). Correlated forensic
signals are grouped into families (ELA + compression; noise; copy-move) so they are never double
counted, and a valid C2PA manifest coexisting with a STRONG/PROBABLE contrary signal produces an
explicit `conflict` record that keeps both sides. The `evidence` step runs last in both pipelines
and replaces the analysis' rows; `GET /analysis/{id}/evidence` returns them and the report uses
them instead of its client-side preliminary derivation once they exist.

Conflicts (T031): three rules produce `kind: conflict` records that keep both sides and lower
synthesis confidence: a validated C2PA manifest against a STRONG forensic or PROBABLE AI signal;
a metadata capture time later than the manifest's signing time; a source published before the
recorded capture time. Timestamps are parsed by `utils/timeparse.py` (RFC 3339, EXIF, plain
dates); naive values are compared as if UTC with a one-minute tolerance and the record says so.
The report shows an alert whenever conflicts exist.

Configurable confidence (T030): `VERIXA_EVIDENCE_CONFIDENCE_{VERIFIED,STRONG,PROBABLE,POSSIBLE}`
set the default confidence per level (rules with their own number, such as an AI score, keep it);
`VERIXA_EVIDENCE_LEVEL_OVERRIDES` (JSON, rule id → level) lets a deployment make a rule more
conservative, clamped to the rule's docs/07 ceiling so nothing can be overstated;
`VERIXA_EVIDENCE_CONFLICT_PENALTY` is subtracted from the synthesis confidence per conflict
record. The thresholds in force are recorded in the `evidence` step details and echoed by the
evidence endpoint.

### Matches

`GET /analysis/{id}/matches` returns every normalised match (URL, title, similarity on the
provider's scale, provider, source kind, matched phrase, reported publication date, discovery
time, raw provider record) plus a deterministic `summary` (`services/search/summary.py`: count,
distinct domains most frequent first, kinds, similarity range, how many matches carry a reported
date and the earliest of them, labelled as reported). The Matches tab lists them with sort
(provider rank, similarity, reported date) and kind/domain filters; every match carries the
POSSIBLE badge (docs/07) and the view says plainly that a match shows discovery, not origin.
Account-level duplicates (fingerprints) sit below it.

### Overview

`services/reports/overview.py` assembles the report's first page from stored rows only: evidence
grouped into verified facts, strong evidence, probabilistic signals (PROBABLE and POSSIBLE),
conflicts and unknowns (UNKNOWN records, including checks that found nothing); the synthesis when
one exists; and methodology notes: the evidence-level definitions (docs/07), the steps that ran
with status and duration, the engines and providers involved with versions and audited call
counts, the thresholds in force, and the reporting principles. Served by `GET /analysis/{id}/overview`
and rendered by the Overview tab; the PDF export (T036) renders the same structure.

### LLM synthesis (explanation layer only)

`providers/llm/` holds the synthesiser adapters (`mock`, `openai` via Chat Completions with a
strict JSON schema) behind one interface, cached by evidence fingerprint like every other
provider. The model receives *structured evidence only* (`services/synthesis/request.py`: record
ids, rules, levels, claims, sources, limitations, conflicts, timeline events) and must answer the
six docs/07 summary questions, each with the evidence ids it relied on. `services/synthesis/
grounding.py` then drops citations that name no sent record, flags sections that make statements
without citing evidence, and warns about level words the evidence does not carry or certainty
wording with nothing VERIFIED. The result is stored in `syntheses` with the evidence fingerprint
(so `GET /analysis/{id}/synthesis` can report `current: false` after the evidence changes) and
shown under Interpretation on the overview with its citations, grounding flags and warnings.
Settings: `VERIXA_LLM_PROVIDER` (none | mock | openai), `VERIXA_OPENAI_API_KEY`,
`VERIXA_OPENAI_MODEL`, `VERIXA_OPENAI_BASE_URL`, `VERIXA_LLM_TIMEOUT_SECONDS`,
`VERIXA_LLM_PROMPT_VERSION`, `VERIXA_OPENAI_COST_PER_MILLION_INPUT|OUTPUT`. Provider data
handling: no file bytes, user text, storage keys or user identity are ever sent; the system prompt
declares file-derived field values to be data, not instructions.

### Timeline

`services/evidence/timeline.py` turns *recorded* times into ordered events: C2PA signing time
and dated manifest actions (certainty = the provenance record's level), metadata capture and
modification times (POSSIBLE), source publication dates as reported (POSSIBLE), our own source
discovery time and the submission time (VERIFIED). Each event keeps the raw string, whether a
timezone was recorded, its source, and the evidence row ids it came from; events whose time could
not be parsed sort last with a null `event_time`. Rows live in `timeline_events` (replaced by
the evidence step) and are served by `GET /analysis/{id}/timeline`; the Timeline tab renders
them as a vertical line with level, source and raw time.

### Forensics UI

The Forensics tab shows, per method, the observation, the method's design confidence, the
visualisation (when the method produces one) and its limitations. Above the cards: a summary
table of every method's outcome, and a viewer that draws each method's regions (ELA outliers,
noise regions, copy-move source → target) over the original image and can blend the ELA, noise
and copy-move maps in with adjustable opacity. The original is fetched through
`GET /analysis/{id}/file`, a short-lived signed link for the owner only. On the web side the
docs/07 rule "multiple independent forensic anomalies → STRONG" is applied preliminarily: ELA and
compression count as one correlated family; noise and copy-move are independent; resampling
never counts as an anomaly.

### Provider result cache

Repeatable provider results (AI detection, reverse-image and phrase search) are cached in the
`provider_cache` table (`repositories/provider_cache.py`; the interface and key helpers live in
`providers/cache.py`) keyed by `sha256(provider | operation | model_version | content_hash)`,
with a TTL (`VERIXA_PROVIDER_CACHE_TTL_HOURS`, default 168; `0` disables). The cache is shared
across users on purpose — identical content gets the same answer without a second paid call —
and payloads never contain user identity. Hits are recorded in the audit trail as `cached` with
zero latency and cost; the `hit_count` per entry is kept for cost reporting.

### Provider call audit

Every engine or provider invocation made by a pipeline step is wrapped in
`ProviderCallRecorder.track()` (`app/services/provider_calls.py`) and persisted to
`provider_calls`: provider, operation (`ai.detect`, `search.image`, `search.text`,
`metadata.extract`, `provenance.inspect`), model/version, status
(`success | cached | failed | timeout | skipped`), latency, SHA-256 request hash (never the
content), estimated USD cost, request id, and a size-bounded response or error summary. Failures
are recorded and re-raised; cached hits are recorded with zero latency and cost.

### Processing pipeline

Uploads are processed by a step pipeline (`app/services/analysis/pipeline.py`) dispatched after
the response through `app/workers/dispatcher.py` (FastAPI background task in the MVP; the
`Dispatcher` interface is the seam for a real queue). Every step is persisted in
`analysis_steps` with status, timing, a stable `error_code` and non-sensitive `details`, and is
returned in `GET /analysis/{id}` as `steps[]`. Non-critical step failures are recorded and the
run continues; a critical failure fails the analysis and marks the remaining steps `skipped`.

Steps today:

| Step | Critical | What it records |
| ---- | -------- | --------------- |
| `validate` | yes | Re-reads the stored original, checks SHA-256 against the record, re-runs upload validation; format, dimensions, frames |
| `hashing` | yes | SHA-256, MD5 (compatibility only), aHash, dHash, pHash (64-bit, imagehash-compatible), persisted to `image_fingerprints` (replaced on re-run); `GET /analysis/{id}/fingerprints` also lists exact/near duplicates among the user's own analyses (Hamming ≤ `VERIXA_FINGERPRINT_NEAR_THRESHOLD`) — similarity is a *signal*, not proof of origin |
| `provenance` | no | C2PA manifests via c2patool (temp file, fixed args); presence, signature validity, stated signer, claim generator, actions, authors, validation codes; absence is UNKNOWN, issuer trust not evaluated; `GET /analysis/{id}/provenance` |
| `ai` | no | AI-generation signal via the configured `AIDetector` adapter (`VERIXA_AI_DETECTOR_PROVIDER`: `none` skips the step; `mock` is a deterministic stand-in). Results are cached by content hash + provider/model/version, persisted to `ai_detections` with provider, model, version, score, label, thresholds and raw response; `GET /analysis/{id}/ai`. A score maps to PROBABLE/POSSIBLE/UNKNOWN per docs/07 and is never presented as proof |
| `search` | no | Reverse-image / phrase source search via `ImageSourceSearch` / `TextSourceSearch` adapters (`VERIXA_SOURCE_SEARCH_PROVIDER`: `none` skips; `mock` returns synthetic `.invalid` hits). Distinctive phrases are chosen deterministically (`services/text/phrases.py`, capped by `VERIXA_TEXT_SEARCH_MAX_PHRASES`); matches persist to `reverse_matches` with the run summary in `source_search_runs`; `GET /analysis/{id}/matches`. A match is a discovery signal (POSSIBLE), never origin proof |
| `metadata` | no | EXIF/XMP/IPTC/ICC via ExifTool (stdin, fixed args) or Pillow fallback; raw groups preserved in `image_metadata`, normalised camera/software/timestamps/orientation/GPS-presence; `GET /analysis/{id}/metadata` |

Later tasks add metadata, provenance, fingerprint persistence/matching, forensics, AI signals,
source search, evidence and report steps.

## Object storage

All uploads, derived artifacts and reports go through `app.providers.storage.ObjectStorage`
(`put`, `get`, `exists`, `delete`, `signed_url`). Keys are internal and validated against path
traversal; they are never returned to clients. Reads happen only via short-lived signed URLs:

- `local` backend: files under `${VERIXA_DATA_DIR}/storage`, served by
  `GET /api/v1/files/{key}?exp=&sig=` after HMAC verification.
- `s3` backend (`pip install -e ".[s3]"`): private bucket, presigned `get_object` URLs.

Key layout (`app/services/storage_keys.py`): `uploads/{user}/{analysis}/{sha256}.{ext}`,
`artifacts/{user}/{analysis}/{name}`, `reports/{user}/{analysis}/{report}.{fmt}`.

## Configuration

All configuration is via environment variables; see the `.env.example` files. Never commit `.env`.

| Variable | Where | Purpose |
| -------- | ----- | ------- |
| `VERIXA_ENVIRONMENT` | API | `development` \| `test` \| `production` (production disables `/docs`) |
| `VERIXA_DEBUG` | API | FastAPI debug mode |
| `VERIXA_CORS_ORIGINS` | API | JSON list of allowed browser origins |
| `VERIXA_SECRET_KEY` | API | Signs access tokens. Random, 32+ chars; the built-in dev default is refused in production |
| `VERIXA_ACCESS_TOKEN_TTL_MINUTES` | API | Access-token lifetime (default 30) |
| `VERIXA_REFRESH_TOKEN_TTL_DAYS` | API | Refresh-token lifetime (default 14) |
| `VERIXA_METADATA_ENGINE` | API | `auto` (ExifTool if found, else Pillow), `exiftool`, or `pillow` |
| `VERIXA_EXIFTOOL_PATH` | API | Explicit ExifTool executable; otherwise PATH and known install dirs are searched |
| `VERIXA_EXIFTOOL_TIMEOUT_SECONDS` | API | Per-file extraction timeout (default 30) |
| `VERIXA_PROVENANCE_ENGINE` | API | `auto` (c2patool if found, else none), `c2patool`, or `none` |
| `VERIXA_C2PATOOL_PATH` | API | Explicit c2patool executable |
| `VERIXA_C2PATOOL_TIMEOUT_SECONDS` | API | Per-run timeout (default 30) |
| `VERIXA_FINGERPRINT_NEAR_THRESHOLD` | API | Max Hamming distance (bits) on pHash/dHash counted as a near duplicate (default 10) |
| `VERIXA_ELA_QUALITY` / `VERIXA_ELA_MAX_SIDE` | API | ELA resave quality (default 95) and working-size cap (default 3000 px) |
| `VERIXA_ELA_OUTLIER_SIGMA` / `VERIXA_ELA_ANOMALY_MIN_FRACTION` / `VERIXA_ELA_ANOMALY_MAX_FRACTION` | API | Outlier threshold and the outlier-block band that counts as localised |
| `VERIXA_COMPRESSION_GRID_MIN_STRENGTH` | API | Minimum relative strength of an 8 px periodicity to count as a block grid (default 0.08) |
| `VERIXA_RESAMPLING_MIN_PEAK_RATIO` | API | Spectral peak / local-background ratio that counts as a resampling trace (default 5.0) |
| `VERIXA_NOISE_BLOCK_SIZE` / `VERIXA_NOISE_OUTLIER_K` / `VERIXA_NOISE_ANOMALY_MIN|MAX_FRACTION` | API | Noise-consistency block size (32), outlier threshold in IQR multiples (3.0) and anomaly band |
| `VERIXA_COPY_MOVE_MAX_SIDE` / `VERIXA_COPY_MOVE_MIN_MATCHES` / `VERIXA_COPY_MOVE_MIN_SHIFT` | API | Copy-move working size (1024), block pairs per displacement (200) and minimum displacement (32 px) |
| `VERIXA_PROVIDER_CACHE_TTL_HOURS` | API | TTL for cached provider results (default 168; 0 disables) |
| `VERIXA_AI_DETECTOR_PROVIDER` | API | `none` (default) or `mock`; real adapters register under `providers/ai` |
| `VERIXA_AI_SCORE_HIGH` / `VERIXA_AI_SCORE_MEDIUM` | API | Score thresholds → PROBABLE / POSSIBLE (defaults 0.85 / 0.6) |
| `VERIXA_SOURCE_SEARCH_PROVIDER` | API | `none` (default) or `mock`; real adapters register under `providers/search` |
| `VERIXA_TEXT_SEARCH_MAX_PHRASES` | API | Max distinctive phrases queried per text (default 5) |
| `VERIXA_TEXT_NEAR_THRESHOLD` | API | Min estimated Jaccard (0–1) for a text near duplicate (default 0.5) |
| `VERIXA_MAX_TEXT_CHARS` | API | Pasted-text cap in characters (default 200000) |
| `VERIXA_MAX_UPLOAD_BYTES` | API | Upload size cap (default 26214400 = 25 MB); mirror it in `next.config.ts` `serverActions.bodySizeLimit` |
| `VERIXA_MAX_IMAGE_PIXELS` | API | Width × height cap checked from the header (default 40 MP) |
| `VERIXA_DATA_DIR` | API | Root for local runtime data (default `./data`, git-ignored) |
| `VERIXA_DATABASE_URL` | API | SQLAlchemy URL. Default: SQLite at `${VERIXA_DATA_DIR}/verixa.db`. Use `postgresql+asyncpg://…` for PostgreSQL |
| `VERIXA_STORAGE_BACKEND` | API | `local` (default, files under `${VERIXA_DATA_DIR}/storage`) or `s3` |
| `VERIXA_STORAGE_LOCAL_PATH` | API | Override the local storage directory |
| `VERIXA_API_PUBLIC_URL` | API | Public origin of the API; local-storage signed URLs point here |
| `VERIXA_SIGNED_URL_TTL_SECONDS` | API | Lifetime of signed download links (default 300) |
| `VERIXA_S3_ENDPOINT_URL`, `VERIXA_S3_REGION`, `VERIXA_S3_BUCKET`, `VERIXA_S3_ACCESS_KEY_ID`, `VERIXA_S3_SECRET_ACCESS_KEY` | API | Required only when `VERIXA_STORAGE_BACKEND=s3`; the bucket must be private |
| `NEXT_PUBLIC_API_BASE_URL` | Web | API origin used by the web app |

## Working with Claude Code

Start with `CLAUDE.md`, then `docs/CLAUDE-MASTER-PROMPT.md`. Tasks execute in the order given by
`TASKS/00-MASTER-EXECUTION.md`.

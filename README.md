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

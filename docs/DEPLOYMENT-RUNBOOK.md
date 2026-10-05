# Verixa Deployment Runbook

Audience: DevOps / platform. Repository: <https://github.com/TechAvtar/varixa>.
Code state: `main` at `8f77f29`, 5 Oct 2026 (through T051: C2PA phases 1 to 7 and the real
AI-detection and source-search providers). Supersedes the version written at `d75ddc0` (T042/T043).

Verixa is an image and text forensics service: a Next.js web app in front of a FastAPI API that
runs a deterministic analysis pipeline and stores private artifacts. This document covers how to
run it in production on PostgreSQL and an S3-compatible bucket, what the API needs on its host,
every environment variable that matters, and the operational behaviour to plan around.

## What changed since the previous runbook

| Area | Change | What you must do |
| ---- | ------ | ---------------- |
| c2patool | Pinned to **v0.28.0** (was 0.9.12). Release asset is named `v0.28.0-x86_64-unknown-linux-gnu.tar.gz`. | Nothing for the images (the Dockerfile and CI already use it). Hosts that install it by hand must upgrade; below 0.28 the engine cannot be stopped from fetching remote manifests. |
| Signer trust | The official C2PA trust list is **bundled in the code**; reports distinguish "intact" from "intact and signer trusted". | Refresh the list before each release (`scripts/refresh_trust_list.py`). `VERIXA_C2PA_TRUST_MODE` defaults to `bundled`. |
| Provenance depth | Hash coverage, signed declarations, ingredient tree, signing certificate chain (needs the `cryptography` package, now a runtime dependency), signed claim thumbnail comparison (pipeline is now **16 steps**). | None; up to five short `c2patool` runs per image. |
| Sidecar upload | `POST /api/v1/analysis/image` accepts an optional second part `sidecar` (a `.c2pa` manifest store). | Allow the extra bytes (up to 4 MiB) in body limits, see section 5. Migration `5522ab366c39`. |
| Real providers | New `local` AI detector (open-source models run in the API process) and new `web` source search (Wikipedia, OpenAlex, optional SearXNG, optional Google Cloud Vision). | Optional. Read section 6 before enabling either. |
| Settings | New variables for all of the above. Source search hosts are checked against `VERIXA_OUTBOUND_ALLOWED_HOSTS` **when settings load**. | A misconfigured allowlist now stops the API (and the `migrate` job) from starting instead of failing per analysis. |
| Health | `/api/v1/health` now includes an `engines` block (c2patool status and version, never the path) and the trust list version. | Update dashboards if they parse the response. |
| Database | Head revision is `5522ab366c39`. All migrations since the first runbook add columns or tables only. | Run `alembic upgrade head` as before. |

## 1. Topology

```
browser --HTTPS--> reverse proxy --> web  (Next.js 16, Node 22+, port 3000)
                              |            | server-side calls to the API (never from the browser)
                              |            v
                              +------> api  (FastAPI + uvicorn, Python 3.12+, port 8000)
                                           |- pipeline steps run inside the API process (CPU-bound)
                                           |- retention sweeper runs inside the API process (timer)
                                           |- optional local AI-detector models, loaded in-process
                                           |--> PostgreSQL 15+   (VERIXA_DATABASE_URL)
                                           |--> S3-compatible private bucket (originals, sidecars, maps, PDFs)
                                           '--> optional HTTPS egress: OpenAI, Wikipedia, OpenAlex,
                                                SearXNG, Google Cloud Vision (see section 6)
browser --presigned GET--> bucket (forensic maps, thumbnails, PDFs; short-lived signed URLs)
```

- **Two deployable units**: `apps/web` and `services/api`, each with a Dockerfile. There is no
  separate worker or queue; analyses run as background tasks inside the API process.
  `infra/compose.yml` adds PostgreSQL, a one-shot `migrate` job and a Caddy proxy for a single host.
- **Browser traffic**: pages and server actions go to the web app, which calls the API server-side
  with the user's token from an httpOnly cookie. Browsers reach the API directly only for signed
  downloads when storage is `local`; with S3 they fetch presigned bucket URLs.
- **Auth**: JWT access tokens (30 min) plus rotating refresh tokens (14 days), signed with
  `VERIXA_SECRET_KEY`. Rotating that key signs every user out.

## 2. Runtime requirements

| Component | Requirement |
| --------- | ----------- |
| API host | Python 3.12+, pip extras `postgres` and `s3`. About 2 vCPU and 2 GB RAM per process for the forensic steps on 25 MB uploads; no GPU. With the local AI detectors add roughly 2 to 3 GB RAM (the two models are about 1.3 GB of weights on disk; this is an estimate, measure it on your instance size). |
| System binaries | `exiftool` (full metadata; Pillow fallback otherwise) and `c2patool` **0.28.0** (content credentials; skipped otherwise). The report states which engine ran. |
| Web host | Node 22+ (`.nvmrc` pins 24; the image uses `node:24-alpine`). |
| Data services | PostgreSQL 15+ and one private S3-compatible bucket. No Redis, no broker. |
| Optional | `ml` extra (`torch`, `transformers`, `huggingface_hub`) for the local AI detectors, about 2.5 GB more in the image. |

The API image installs both binaries; CI does the same on Ubuntu:

```bash
apt-get install -y --no-install-recommends libimage-exiftool-perl
curl -sSL -o /tmp/c2patool.tar.gz \
  https://github.com/contentauth/c2patool/releases/download/v0.28.0/v0.28.0-x86_64-unknown-linux-gnu.tar.gz
tar -xzf /tmp/c2patool.tar.gz -C /usr/local/bin --strip-components=1 c2patool/c2patool
```

## 3. Build and start commands

### Containers (recommended)

```bash
# from the repository root
docker build -t verixa-api:<tag> services/api
docker build -t verixa-web:<tag> -f apps/web/Dockerfile --build-arg NEXT_PUBLIC_API_BASE_URL=https://app.example.com .

# API image WITH the local AI detector models baked in (optional, see section 6)
docker build -t verixa-api:<tag> --build-arg INSTALL_ML=1 services/api

# API container: configuration check, migrations, then serve
docker run --rm --env-file prod.env verixa-api:<tag> python -m app.preflight
docker run --rm --env-file prod.env verixa-api:<tag> alembic upgrade head
docker run -d --env-file prod.env -e FORWARDED_ALLOW_IPS="*" -p 8000:8000 verixa-api:<tag>

# web container: server-side calls go to the private API address
docker run -d -e API_BASE_URL=http://api:8000 -p 3000:3000 verixa-web:<tag>
```

Both images run as non-root users and carry a `HEALTHCHECK` (API: `/api/v1/health/live`; web: `/`).
The API default command is `uvicorn ... --proxy-headers --no-server-header`; it honours
`X-Forwarded-*` only from `FORWARDED_ALLOW_IPS`, so set that to the proxy's address, or `*` when the
proxy is the only ingress.

### Single host with Compose

```bash
cp infra/.env.example infra/.env        # host, ACME email, DB password, bucket, secrets
docker compose -f infra/compose.yml --env-file infra/.env up -d --build
docker compose -f infra/compose.yml --env-file infra/.env logs migrate   # preflight + migrations
curl -fsS https://<host>/api/v1/health
```

Services: `db` (PostgreSQL 16, volume), `migrate` (runs `python -m app.preflight && alembic upgrade
head` once per deploy), `api` (after `migrate` succeeds), `web` (after `api` is healthy), `proxy`
(Caddy 2, automatic Let's Encrypt, the only service with published ports). `--profile minio` adds a
private MinIO bucket and an init job; presigned links then need the public `files.<host>` site (copy
`infra/sites.d/minio.caddy.example` to `minio.caddy` and add the DNS record).

With the local AI detectors: `docker compose -f infra/compose.yml --env-file infra/.env build --build-arg INSTALL_ML=1 migrate`
(the `api` service reuses the `migrate` image).

### API without containers

```bash
cd services/api
python -m venv .venv && . .venv/bin/activate
pip install -e ".[postgres,s3]"           # add ,ml for the local AI detectors
python scripts/fetch_detector_models.py   # only with the ml extra, once (about 1.2 GB)

alembic upgrade head                       # once per release, before starting the new version
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips="*"
```

Never use `--reload` outside a laptop. Pass variables through the environment or a secret manager,
not a `.env` file, in production.

### Web without containers

```bash
npm ci                                  # repository root (workspaces)
NEXT_PUBLIC_API_BASE_URL=https://app.example.com NEXT_TELEMETRY_DISABLED=1 npm run build
API_BASE_URL=http://10.0.0.5:8000 npm run start --workspace @verixa/web -- --port 3000
```

`API_BASE_URL` (runtime, never sent to browsers) wins over `NEXT_PUBLIC_API_BASE_URL` (build time).
`VERIXA_CORS_ORIGINS` only matters when browsers call the API directly (local storage mode).

## 4. Environment variables

All API settings carry the `VERIXA_` prefix and are validated at start-up. **required** marks what
production cannot start or run safely without.

**Preflight.** `python -m app.preflight` exits 1 and lists every problem when
`VERIXA_ENVIRONMENT=production` is combined with: debug on, SQLite, `local` storage, a non-https
`VERIXA_API_PUBLIC_URL`, non-https CORS origins, metrics enabled without a token, or
`VERIXA_C2PA_REMOTE_MANIFEST_FETCH=true`. Run it before `alembic upgrade head`; the Compose
`migrate` service does. `infra/.env.example` is the production subset of
`services/api/.env.example` (the full list with defaults).

### Core

| Variable | Production value | Notes |
| -------- | ---------------- | ----- |
| `VERIXA_ENVIRONMENT` **required** | `production` | Disables `/docs`, enables HSTS, enforces the secret and metrics rules. |
| `VERIXA_SECRET_KEY` **required** | random, 32+ chars | `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Rotation logs everyone out. Blank or the built-in default is refused in production. |
| `VERIXA_DATABASE_URL` **required** | `postgresql+asyncpg://user:pass@host:5432/verixa` | Async driver is mandatory. Default SQLite is for development only. |
| `VERIXA_STORAGE_BACKEND` **required** | `s3` | Private bucket. `local` is development only. |
| `VERIXA_S3_BUCKET`, `VERIXA_S3_ACCESS_KEY_ID`, `VERIXA_S3_SECRET_ACCESS_KEY` **required** | bucket and credentials | Plus `VERIXA_S3_ENDPOINT_URL` for non-AWS and `VERIXA_S3_REGION` (default `auto`). |
| `VERIXA_CORS_ORIGINS` | `["https://app.example.com"]` | JSON list; only for direct browser calls. |
| `VERIXA_API_PUBLIC_URL` | `https://app.example.com` | Must be https in production. |
| `VERIXA_TRUST_PROXY_HEADERS` | `true` | Use the first `X-Forwarded-For` for login throttling; only behind a proxy that overwrites it. |
| `VERIXA_DATA_DIR` | writable path | Scratch space for engines that need files (c2patool) even with S3. Small writable volume. |
| `VERIXA_MAX_UPLOAD_BYTES` | `26214400` (25 MB) | Keep equal to the web `serverActions.bodySizeLimit` (26mb) and the proxy limit. |

### Content Credentials (C2PA)

| Variable | Default | Notes |
| -------- | ------- | ----- |
| `VERIXA_PROVENANCE_ENGINE` | `auto` | `auto` uses c2patool when found, else skips. `VERIXA_C2PATOOL_PATH`, `VERIXA_C2PATOOL_TIMEOUT_SECONDS` (30). |
| `VERIXA_C2PA_REMOTE_MANIFEST_FETCH` | `false` | c2patool must never fetch remote manifests itself; preflight refuses `true`. Remote references are reported (host only), not fetched. |
| `VERIXA_C2PA_TRUST_MODE` | `bundled` | `bundled` (official list shipped in the repo), `custom` (your own local PEM files via `VERIXA_C2PA_TRUST_ANCHORS_PATH`, `VERIXA_C2PA_ALLOWED_LIST_PATH`, `VERIXA_C2PA_TRUST_CONFIG_PATH`; local files only, URLs refused), or `off`. |
| `VERIXA_SIDECAR_UPLOAD_ENABLED`, `VERIXA_SIDECAR_MAX_BYTES` | `true`, `4194304` | Optional `.c2pa` upload beside an image. The content is sniffed (the file name and MIME type are ignored). |

### Observability and abuse controls

| Variable | Production value | Notes |
| -------- | ---------------- | ----- |
| `VERIXA_LOG_FORMAT` | `json` | One JSON object per line on stderr with `request_id` and `analysis_id`. `VERIXA_LOG_LEVEL` defaults to `INFO`. |
| `VERIXA_METRICS_TOKEN` **required** | random string | Scrapes send `Authorization: Bearer <token>`. Without it production returns 404 on `/metrics`. |
| `VERIXA_LOGIN_MAX_ATTEMPTS` / `_PER_IP` / `VERIXA_LOGIN_WINDOW_MINUTES` | 10 / 50 / 15 | Per API process; add a shared rate limit at the proxy for several containers. |
| `VERIXA_REGISTER_MAX_PER_HOUR` | 20 | Per client address, per process. |
| `VERIXA_RETENTION_SWEEP_INTERVAL_MINUTES` | 60, or 0 with an external cron | In-process sweeper, see section 7. |
| `VERIXA_RAW_CONTENT_RETENTION_HOURS`, `VERIXA_PROVIDER_RESPONSE_RETENTION_DAYS`, `VERIXA_DELETED_RECORD_GRACE_DAYS`, `VERIXA_ANALYSIS_RETENTION_DAYS` | 24 / 30 / 7 / 0 | Product retention policy; confirm with legal before changing. |
| `VERIXA_USAGE_MONTHLY_ANALYSIS_LIMIT`, `VERIXA_USAGE_STORAGE_LIMIT_BYTES`, `VERIXA_USAGE_MONTHLY_PROVIDER_COST_LIMIT` | 0 (unlimited) | Per-user caps; 429 when exceeded, paid steps skipped once the cost budget is spent. |

### External providers

Providers are all optional; `none` keeps the step skipped and the report says so. **Never run
`mock` in production**: the report labels it, but it carries no information.

| Variable | Values | Notes |
| -------- | ------ | ----- |
| `VERIXA_LLM_PROVIDER` | `none`, `openai` | With `openai`: `VERIXA_OPENAI_API_KEY`, `VERIXA_OPENAI_MODEL` (default `gpt-4o-mini`), `VERIXA_OPENAI_BASE_URL`, cost settings. Only structured evidence is sent, never uploads. |
| `VERIXA_AI_DETECTOR_PROVIDER` | `none`, `local` | `local`: see section 6. |
| `VERIXA_SOURCE_SEARCH_PROVIDER` | `none`, `web` | `web`: see section 6. |
| `VERIXA_OUTBOUND_ALLOWED_HOSTS` | JSON list | Egress allowlist enforced in code. Must contain every host in use (section 6). Match it at the network layer too. |
| `VERIXA_EXIFTOOL_PATH` | only if not on PATH | `VERIXA_METADATA_ENGINE` is `auto` by default. |

Web: `NEXT_PUBLIC_API_BASE_URL` (build time), `API_BASE_URL` (runtime, private address),
`NODE_ENV=production`.

## 5. Reverse proxy and networking

`infra/Caddyfile` is a working reference: one public host, `/api/*` to `api:8000`, everything else
to `web:3000`, zstd/gzip, a 30 MB request body limit, automatic certificates (ports 80/443 reachable
and DNS resolving). `/metrics` is deliberately not routed; scrape it on the private network.

- **TLS** terminates at the proxy. The API emits HSTS itself in production, plus nosniff, frame
  denial, a locked CSP and `Cache-Control: no-store`. The web app sets its own headers.
- **Body size**: an image upload may now carry a sidecar, so allow image plus sidecar. The web
  server action limit is 26 MB and the Caddy limit 30 MB; an image near 25 MB plus a 4 MiB sidecar
  can exceed the web limit. Raise `serverActions.bodySizeLimit` and the proxy limit together if you
  expect that.
- **Timeouts**: uploads return 201 immediately and processing continues in the background, but PDF
  generation and the forensic steps can take 10 to 30 seconds. With the local image detector add
  roughly 6 to 9 seconds per image on CPU (measured on a developer machine). Use upstream read
  timeouts of 60 seconds or more on the API.
- **Client address**: forward `X-Forwarded-For` and set `VERIXA_TRUST_PROXY_HEADERS=true`.
- **Request correlation**: the API honours and returns `X-Request-ID`.
- **Egress**: the API needs outbound HTTPS to the bucket and the providers in use, nothing else.
  Block everything else at the network layer. The C2PA engine itself must have **no** network access
  (it is told not to fetch anything; a network policy is a good second line).

## 6. Real providers (optional)

Both stay `none` until chosen and are independent of each other.

### Local AI detectors (`VERIXA_AI_DETECTOR_PROVIDER=local`)

- Two open-source classifiers run inside the API process; **nothing is sent anywhere**: an image
  model (`haywoodsloan/ai-image-detector-deploy`, Apache-2.0) and a text model
  (`openai-community/roberta-base-openai-detector`, MIT).
- The service never downloads models. They are fetched once by `scripts/fetch_detector_models.py`
  (pinned to a commit; records revision and weights hash) into `VERIXA_AI_DETECTOR_MODEL_DIR`
  (default `<data dir>/models`). In the image, `--build-arg INSTALL_ML=1` installs CPU-only torch and
  bakes the models into `/opt/models` (`VERIXA_AI_DETECTOR_MODEL_DIR` and `HF_HUB_OFFLINE=1` are set).
- Models load once per process and are **warmed in the background at start-up**; the first analyses
  right after a restart wait for that (up to `VERIXA_AI_DETECTOR_LOAD_TIMEOUT_SECONDS`, default 300).
  Scoring has its own timeout (`VERIXA_AI_DETECTOR_TIMEOUT_SECONDS`, default 30) and runs in a worker
  thread, one request at a time per process.
- Other settings: `VERIXA_AI_DETECTOR_IMAGE_MODEL`, `_IMAGE_AI_LABEL`, `_TEXT_MODEL`, `_TEXT_AI_LABEL`,
  `_TEXT_MIN_TOKENS` (50), `_TEXT_MAX_CHUNKS` (8). If a label does not exist in the model's label set the
  analysis reports a clear error.
- **The scores are weak, uncalibrated signals.** The evidence engine caps them at POSSIBLE and every
  result carries limitations. They can flag real images (a plain synthetic gradient scored as strongly
  AI in testing) and miss modern AI text. Do not describe them as a verdict in any customer material.
- CPU only. Budget several seconds per image and about 2 to 3 GB extra RAM; scale by adding containers.

### Web source search (`VERIXA_SOURCE_SEARCH_PROVIDER=web`)

| Backend | Setting | Egress host to allow | Notes |
| ------- | ------- | -------------------- | ----- |
| Wikipedia (text) | `VERIXA_SOURCE_SEARCH_TEXT_BACKENDS` includes `wikipedia`; `VERIXA_WIKIPEDIA_LANGUAGE` (`en`) | `en.wikipedia.org` | No key. |
| OpenAlex (text) | includes `openalex` | `api.openalex.org` | No key. |
| SearXNG (text) | includes `searxng`; `VERIXA_SEARXNG_BASE_URL` | your instance | Self-hosted, JSON output enabled. Must be **https** in production (plain http is accepted only for localhost outside production). Not covered by CI or tested against a real instance. |
| Google Cloud Vision (image) | `VERIXA_SOURCE_SEARCH_IMAGE_BACKEND=google_vision`, `VERIXA_GOOGLE_VISION_API_KEY` | `vision.googleapis.com` | Sends **each uploaded image to Google**; billed per image after the free allowance. Without it image source search is skipped and reported as UNKNOWN. |

- Default text backends are `wikipedia` and `openalex`. Example allowlist:
  `VERIXA_OUTBOUND_ALLOWED_HOSTS=["api.openai.com","en.wikipedia.org","api.openalex.org"]`.
- **The API refuses to start** (and `migrate` fails preflight) if an enabled backend's host is not on the
  allowlist, if `searxng` has no URL, or if `google_vision` has no key.
- Privacy: short phrases from submitted text (never the whole text) go to the enabled text services; the
  image goes to Google when that backend is on. Reflect this in your privacy notice and data-processing
  agreements before enabling.
- A failing backend gives a visibly incomplete result that is not cached; all backends failing marks the
  search step failed (the analysis still completes).
- Keys travel in request headers, never in URLs, and are never logged.

## 7. Database, storage, retention

### PostgreSQL

- Run `python -m app.preflight` then `alembic upgrade head` before starting a new API version. Alembic
  creates the local data directory itself on a fresh host. Current head: `5522ab366c39`. Migrations so
  far are additive.
- Models use JSONB, timestamptz and native UUIDs on PostgreSQL. The test suite runs on SQLite, so run
  the migrations against a PostgreSQL copy before each release.
- Sizing: rows are small (tens of KB of JSON per analysis); uploaded content is never stored in the
  database.

### Object storage

- One private bucket, public access blocked. Keys: `uploads/<user>/<analysis>/<sha256>.<ext>` (the
  sidecar is `<sha256>.c2pa` beside it), `artifacts/<user>/<analysis>/<name>`, reports beside them.
- IAM for the API credentials: `s3:PutObject`, `s3:GetObject`, `s3:HeadObject`, `s3:DeleteObject` on the
  bucket's objects and `s3:ListBucket`. Nothing on other buckets.
- Browsers get presigned GET links that expire after `VERIXA_SIGNED_URL_TTL_SECONDS` (default 300).
  Allow GET from the web origin in the bucket's CORS policy if the bucket is on another origin.

### Retention

The API runs an in-process sweeper every `VERIXA_RETENTION_SWEEP_INTERVAL_MINUTES` that expires raw
content after 24 hours unless kept (this covers sidecars, which live under the same upload prefix),
purges provider responses, soft-deletes old records when configured and hard-deletes soft-deleted
records after the grace period. With several API containers either leave the sweeper on (the passes are
idempotent) or set the interval to 0 and schedule `python -m app.workers.retention` as a cron job.

## 8. Health, logs, metrics

| Endpoint | Use | Behaviour |
| -------- | --- | --------- |
| `GET /api/v1/health/live` | liveness | `{"status":"ok"}` as soon as the process serves. |
| `GET /api/v1/health` | readiness | Checks the database and storage; `degraded` when either fails. Also lists configured engine and provider **names**, an `engines` block (c2patool `status` and `version`, trust mode and list version) and uptime. |
| `GET /metrics` | Prometheus | Bearer token required. HTTP requests by route template and status, pipeline steps, analyses, provider calls, uptime. Per process; scrape every container. |

- **Logs** go to stderr; with `VERIXA_LOG_FORMAT=json` each line has `ts`, `level`, `logger`, `msg`,
  `request_id`, `analysis_id` and event fields. Tokens, JWTs, signatures and API keys are redacted at
  record creation; content and filenames are never logged. The AI detector logs `local AI detector
  ready` / `not ready` per modality at start-up.
- **Alerts worth having**: readiness flapping; `verixa_provider_calls_total{status="failed"}` rising;
  `verixa_analyses_total{status="failed"}` rising; p95 of `verixa_http_request_duration_seconds` on the
  upload and report routes; retention sweep errors; repeated `local AI detector not ready` after start-up.

## 9. Security checklist

- Secrets only in the environment or a secret manager; `.env` files stay out of images and git.
- Distinct secrets per environment: `VERIXA_SECRET_KEY`, `VERIXA_METRICS_TOKEN`, S3 credentials, and any
  provider keys (`VERIXA_OPENAI_API_KEY`, `VERIXA_GOOGLE_VISION_API_KEY`). Rotate any key that was ever
  pasted into chat or a ticket.
- `VERIXA_ENVIRONMENT=production`, so API docs are off and the dev secret is refused.
- Bucket private, presigned links only, TTL 5 minutes.
- Egress restricted to the bucket and the allowlisted hosts; the code-level allowlist is the second line.
- Upload cap agreed in three places: API setting, web `bodySizeLimit`, proxy body limit (now including a
  possible sidecar).
- Login and registration throttling is per process; add a proxy rate limit on `/api/v1/auth/*` for several
  containers.
- Non-root containers; the API only needs write access to `VERIXA_DATA_DIR`.
- The bundled C2PA trust list is current (`python services/api/scripts/refresh_trust_list.py --check`).

## 10. Scaling and known limitations

- **Analyses run inside the API process.** Uploads are accepted immediately and the pipeline runs as a
  background task in the same process; the forensic steps are CPU-bound (roughly 5 to 30 seconds per
  image, more with the local detector).
- **One uvicorn worker per container**; scale by adding containers. With `local` detectors every container
  loads its own copy of the models.
- **Restarts lose in-flight work.** An analysis being processed when a container stops stays in
  `processing` and is not re-queued. Drain connections, roll gradually, and expect to clean up after an
  unclean restart. A durable queue is the planned fix and is not in the code yet.
- **Provider result cache** lives in PostgreSQL (shared across containers). Incomplete search results are
  never cached.
- **SQLite and local storage** are development conveniences only.
- **Memory**: a 25 MB JPEG at 40 megapixels decodes to about 120 MB and the ghost analysis re-encodes a
  centre crop 26 times; budget 1.5 to 2 GB per container, plus the models if enabled.

## 11. Rollout, smoke test, rollback

### Order of operations

1. CI is green on the release commit (all five jobs: Secret scan, API, Web, E2E, Container images) and
   `docs/13-RELEASE-CHECKLIST.md` has been walked.
2. Build the API and web images from that commit (or pull them; set `VERIXA_IMAGE_TAG`).
3. `python -m app.preflight`, then `alembic upgrade head`, from the new API image with the production
   environment (the `migrate` service). Snapshot the database first when the release has a migration.
4. Roll the API containers; wait for readiness (`/api/v1/health` with storage ok). With the local
   detectors, wait for the `local AI detector ready` log lines too.
5. Roll the web containers.

### Smoke test

```bash
curl -fsS https://app.example.com/api/v1/health/live
curl -fsS https://app.example.com/api/v1/health            # "status":"ok", storage ok, c2patool ok
# metrics from inside the private network only:
docker compose -f infra/compose.yml exec web wget -qO- --header "Authorization: Bearer $METRICS_TOKEN" http://api:8000/metrics | head -3
```

Then in a browser: register a throwaway account, upload a small JPEG, wait for Completed, open the
Provenance and Forensics tabs (maps must load = presigned URLs work), generate a PDF and download it,
delete the analysis, sign out. Also upload a signed image plus its `.c2pa` sidecar once to prove the
Content Credentials path, and (if enabled) paste a paragraph of well-known text and confirm the Sources
tab lists matches.

### Rollback

- Application: redeploy the previous images; the previous API runs against the newer schema because
  migrations only add columns and tables.
- Schema: `alembic downgrade -1` per migration if a column must go; snapshot before any migration.
- Storage: objects are never rewritten in place.
- Providers: set `VERIXA_AI_DETECTOR_PROVIDER=none` and/or `VERIXA_SOURCE_SEARCH_PROVIDER=none` and restart
  to switch the real providers off without a redeploy; those steps are then skipped and reported as such.

## 12. Vercel deployment (alternative to containers)

`vercel.json` deploys the repository as one Vercel project with two services (`web`, `api`) and a
service binding from `web` to `api` (`API_BASE_URL`). The full list of what changes and which
variables to set is in `infra/README.md` ("Vercel (one project, two services)"). In short:

- Analyses run **inline** (before the upload answers) because work after the response is not kept
  alive; expect uploads to take as long as the analysis, within `maxDuration` 300 s.
- Scratch files use `/tmp/verixa`; PostgreSQL and S3 are mandatory; migrations are run by you, not by
  the functions.
- Retention comes from a daily Vercel Cron call to `/api/v1/internal/retention` (needs `CRON_SECRET`).
  Daily means raw content can outlive its 24-hour limit by up to a day; use an hourly schedule on a plan
  that allows it.
- No `exiftool`, `c2patool` or local AI models there; those parts are skipped and reported as such.
- A function killed mid-analysis leaves it in `processing`; there is no automatic re-queue.
- **Not verified on Vercel itself** (see the list at the end of the infra section).

## 13. Containers and Compose stack

| File | What it is |
| ---- | ---------- |
| `services/api/Dockerfile` | Multi-stage `python:3.12-slim`: venv with `.[postgres,s3]` (and `.[ml]` plus baked models with `INSTALL_ML=1`) in a build stage; runtime stage adds ExifTool and c2patool v0.28.0, user `verixa`, `VERIXA_DATA_DIR=/var/lib/verixa`, models at `/opt/models`, liveness `HEALTHCHECK`, port 8000. Context: `services/api`. |
| `apps/web/Dockerfile` | Multi-stage `node:24-alpine`, Next standalone output, user `node`, port 3000. Context: the repository root. Build arg `NEXT_PUBLIC_API_BASE_URL`. |
| `infra/compose.yml` | `db`, `migrate`, `api`, `web`, `proxy`; optional profile `minio`. Named volumes. Only the proxy publishes ports. Health-gated start order. |
| `infra/Caddyfile`, `infra/sites.d/` | Reverse proxy config; `sites.d/*.caddy` are imported. |
| `infra/.env.example` | Variables the stack needs, including the provider choices above. |
| `services/api/app/preflight.py` | `python -m app.preflight`, the configuration gate. |

The Compose file hard-wires the production-only choices (production environment, PostgreSQL URL, `s3`
storage, https origins, proxy headers, JSON logs), so `infra/.env` carries host names, credentials and
policy. For Kubernetes or another orchestrator the same two images and variables apply: run the
`migrate` command as a Job, give the API a small writable volume at `/var/lib/verixa`, and gate the web
rollout on API readiness.

Upgrades: check out the release commit (or bump `VERIXA_IMAGE_TAG`) and run the same `up -d --build`.
Backups: the `postgres-data` volume (or `pg_dump`) and the bucket; `api-scratch` holds only temporary
files. Prefer a managed bucket over MinIO; with MinIO the endpoint must be the public `https://files.<host>`.

## 14. CI

`.github/workflows/ci.yml` runs on every push and pull request:

- **Secret scan** (gitleaks, with a small `.gitleaksignore` for two historical false positives).
- **API**: `ruff check .` on the whole `services/api` directory, `ruff format --check .`, `mypy` strict, the
  pytest suite (606 tests at this commit; tests that need real AI models skip themselves), migrations applied
  and checked on a fresh directory. Installs ExifTool and c2patool 0.28.0.
- **Web**: eslint, prettier, `tsc`, `next build`.
- **E2E**: Playwright against an isolated API and a production web build (mock providers), including the
  signed-image and sidecar flows.
- **Container images**: builds both Dockerfiles with a cache and smoke-tests them (preflight must exit 1 on a
  bad production configuration, the API container answers `/api/v1/health/live`, the web container serves `/`).
  This builds the default API image only: the `INSTALL_ML=1` path is **not** exercised.

All five jobs are green on `8f77f29`. Images are built but not pushed; add a registry login and `push: true`
when CI should publish them.

## 15. Release checklist and acceptance

`docs/13-RELEASE-CHECKLIST.md` is the gate for every release candidate (code and tests, security and
privacy, core flows, report quality, failure handling, retention, deployment, documentation). It was last
walked in full on 24 Sep 2026 (before the C2PA and real-provider work), so for the next release also check:

- Trust list current; an unsigned image, a signed image and a signed image with a sidecar all give the right
  provenance wording (intact versus intact-and-trusted; untrusted signer is UNKNOWN, never a failure).
- With `local` detectors on: models loaded (log lines), an image and a text analysis complete, the AI result
  is labelled a weak signal and never above POSSIBLE.
- With `web` search on: a text analysis lists matches, the search step says which backends ran, a blocked
  backend shows an incomplete result rather than "no matches".
- Egress test from the API container: only the allowlisted hosts are reachable.

## 16. Not verified yet / not in the repo

- **Not verified on real infrastructure**: migrations against PostgreSQL, bucket policy, certificate
  issuance, backup and restore rehearsal, the `INSTALL_ML=1` image build, a real SearXNG instance, Google
  Cloud Vision with a live key (adapter tested with mocked responses only), and the detector's accuracy.
- **Detector accuracy has not been measured.** Thresholds (`VERIXA_AI_SCORE_HIGH` 0.85, `_MEDIUM` 0.6) are
  defaults, not tuned values. Treat the AI signal as informational.
- Kubernetes or Terraform manifests (the Compose stack is the reference for a single host).
- A durable job queue for the analysis pipeline; today it runs in-process.
- Publishing images to a registry from CI.

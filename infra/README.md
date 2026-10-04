# infra

## Local development (default: no external services)

Local development intentionally needs **no Docker, PostgreSQL, or object-storage service**:

- Database: SQLite file at `services/api/data/verixa.db`
- Object storage: local directory `services/api/data/storage/`

Both live under `VERIXA_DATA_DIR` (git-ignored). Delete that directory to reset local state.

## Opting into PostgreSQL / S3 locally

Set `VERIXA_DATABASE_URL` and/or `VERIXA_STORAGE_BACKEND=s3` (+ `VERIXA_S3_*`) in
`services/api/.env`. Any locally installed PostgreSQL 15+ works; no compose file is provided
because the default path is service-free.

## Portability rules (SQLite and PostgreSQL)

Models and migrations must run on both engines:

- Use `sqlalchemy.JSON().with_variant(JSONB, "postgresql")` instead of bare `JSONB`.
- Use `DateTime(timezone=True)` and always store UTC; SQLite has no `TIMESTAMPTZ`.
- Use `Uuid` (SQLAlchemy 2 native type) for primary keys; it maps to `UUID` on PostgreSQL
  and `CHAR(32)` on SQLite.
- Avoid PostgreSQL-only DDL (partial indexes, `ON CONFLICT` specifics) in Alembic migrations,
  or guard it with `op.get_bind().dialect.name`.
- Run the test suite against SQLite; run migrations against PostgreSQL before a release.

## Production (T042)

Production runs the API container against **PostgreSQL** and a **private S3-compatible bucket**,
behind one TLS origin. Everything needed for a single-host deployment is in this directory:

| File | Purpose |
| ---- | ------- |
| `compose.yml` | `db` (PostgreSQL 16), `migrate` (preflight + `alembic upgrade head`, once per deploy), `api`, `web`, `proxy` (Caddy, automatic certificates); optional `minio` profile |
| `Caddyfile` | `/api/*` to the API, everything else to the web app; `/metrics` stays private |
| `.env.example` | The variables a deployment must provide (copy to `infra/.env`, git-ignored) |
| `sites.d/minio.caddy.example` | Public host for presigned links when the MinIO profile is used |
| `../services/api/Dockerfile` | API image: Python 3.12, ExifTool, pinned c2patool, `.[postgres,s3]`, non-root |
| `../apps/web/Dockerfile` | Web image: Next.js standalone output, non-root, built from the repo root |

### First deployment

```bash
cp infra/.env.example infra/.env            # fill in: host, ACME email, DB password, bucket, secrets
docker compose -f infra/compose.yml --env-file infra/.env up -d --build
docker compose -f infra/compose.yml --env-file infra/.env logs migrate   # preflight + migrations
curl -fsS https://<host>/api/v1/health      # readiness: database + storage probe
```

`migrate` runs `python -m app.preflight` first and refuses to continue when the configuration is
not deployable (debug on, SQLite, local storage, non-https origins, metrics without a token, weak
secret). The API starts only after migrations succeeded, the web app only after the API is healthy.

Upgrades are the same command with the new commit checked out (or a new `VERIXA_IMAGE_TAG` when
images come from a registry). Migrations are forward-only and run before the new API replaces the
old one.

### Real AI detection and source search (optional)

Both stay `none` until chosen. They are independent of each other and of the rest of the stack.

- **Local AI detectors** (`VERIXA_AI_DETECTOR_PROVIDER=local`): open-source classifiers that run
  inside the API container; nothing is sent anywhere. Build the API image with the models baked in:
  `docker compose ... build --build-arg INSTALL_ML=1 migrate` (adds about 2.5 GB and needs CPU time:
  several seconds per image). The models load once per process and are warmed at startup. CI's
  images job builds the default image only, so the `INSTALL_ML=1` path is not exercised there:
  build it once before relying on it. The scores are weak, uncalibrated signals.
- **Web source search** (`VERIXA_SOURCE_SEARCH_PROVIDER=web`): Wikipedia and OpenAlex need no key;
  add their hosts (`en.wikipedia.org`, `api.openalex.org`) to `VERIXA_OUTBOUND_ALLOWED_HOSTS`, or
  the API refuses to start. A self-hosted SearXNG (`VERIXA_SEARXNG_BASE_URL`, JSON output enabled)
  must be reachable over **https** in production (plain http is only accepted for localhost outside
  production). Google Cloud Vision (`VERIXA_SOURCE_SEARCH_IMAGE_BACKEND=google_vision`) sends each
  image to Google and bills per image after its free allowance; it needs
  `VERIXA_GOOGLE_VISION_API_KEY` and `vision.googleapis.com` on the allowlist. Without it, image
  source search is skipped and reported as UNKNOWN.

### Storage options

- **Managed bucket (recommended)**: set `VERIXA_S3_ENDPOINT_URL`, region, bucket and keys in
  `infra/.env`. The bucket must block public access; clients only ever get short presigned URLs.
- **MinIO profile** (`--profile minio`): a private bucket on the same host. Presigned links must be
  reachable by browsers, so copy `sites.d/minio.caddy.example` to `sites.d/minio.caddy`, add a
  DNS record for `files.<host>` and set `VERIXA_S3_ENDPOINT_URL=https://files.<host>`.

### Operations

- Logs are JSON on stdout (`VERIXA_LOG_FORMAT=json`); ship them with the platform's log driver.
- Metrics: `GET /metrics` with `Authorization: Bearer $VERIXA_METRICS_TOKEN` from inside the
  compose network (`docker compose exec web wget -qO- --header "Authorization: Bearer …" http://api:8000/metrics`).
- Retention sweeps run inside the API process (`VERIXA_RETENTION_SWEEP_INTERVAL_MINUTES`); with
  several API replicas keep one sweeper (`0` on the others) or run
  `docker compose run --rm api python -m app.workers.retention` from a scheduler.
- The API's rate limits are per process; run one uvicorn worker per container and scale with
  replicas behind the proxy.
- Backups: `postgres-data` volume (or `pg_dump`) plus the bucket. `api-scratch` holds only
  temporary files.
- Only the proxy publishes ports (80/443). The database, the API and the bucket are not reachable
  from outside the compose network.
- The C2PA trust list is bundled with the code (`services/api/app/providers/provenance/trust/`);
  refresh it before a release with `python services/api/scripts/refresh_trust_list.py` (or
  `--check` to see whether it is stale) and commit the result. Reports record the list version.

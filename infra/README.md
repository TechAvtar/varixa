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

## Production

Deployment configuration is added in T042.

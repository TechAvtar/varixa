# Verixa API — production image (PostgreSQL + S3 extras, ExifTool, c2patool).
# Build context: services/api. See infra/README.md for the full stack.

FROM python:3.12-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
# A self-contained venv is copied into the runtime stage without build tooling.
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install ".[postgres,s3]"

FROM python:3.12-slim AS runtime

ARG C2PATOOL_VERSION=0.9.12
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH" \
    VERIXA_DATA_DIR=/var/lib/verixa

# ExifTool from Debian; c2patool from its GitHub release (pinned).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libimage-exiftool-perl curl ca-certificates \
    && curl -sSL -o /tmp/c2patool.tar.gz \
        "https://github.com/contentauth/c2patool/releases/download/v${C2PATOOL_VERSION}/c2patool-v${C2PATOOL_VERSION}-x86_64-unknown-linux-gnu.tar.gz" \
    && tar -xzf /tmp/c2patool.tar.gz -C /usr/local/bin --strip-components=1 c2patool/c2patool \
    && rm /tmp/c2patool.tar.gz \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* \
    && c2patool --version && exiftool -ver

RUN groupadd --system verixa && useradd --system --gid verixa --create-home verixa \
    && mkdir -p /var/lib/verixa && chown verixa:verixa /var/lib/verixa

WORKDIR /srv/verixa
COPY --from=build /opt/venv /opt/venv
COPY --chown=verixa:verixa alembic.ini ./
COPY --chown=verixa:verixa alembic ./alembic
COPY --chown=verixa:verixa app ./app

USER verixa
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=4).status == 200 else 1)"

# Behind a reverse proxy: --proxy-headers reads X-Forwarded-* from the addresses in
# FORWARDED_ALLOW_IPS (uvicorn reads that env var; default is the loopback only).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]

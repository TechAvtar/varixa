# Verixa API — production image (PostgreSQL + S3 extras, ExifTool, c2patool).
# Build context: services/api. See infra/README.md for the full stack.

FROM python:3.12-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
ARG INSTALL_ML=0
COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts
# A self-contained venv is copied into the runtime stage without build tooling.
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install ".[postgres,s3]"
# Optional local AI detectors (INSTALL_ML=1): CPU-only torch, then the two pinned models
# baked into /opt/models (the service never downloads a model). Adds about 2.5 GB.
RUN mkdir -p /opt/models \
    && if [ "$INSTALL_ML" = "1" ]; then \
        /opt/venv/bin/pip install ".[ml]" \
            --extra-index-url https://download.pytorch.org/whl/cpu \
        && /opt/venv/bin/python scripts/fetch_detector_models.py --dir /opt/models; \
    fi

FROM python:3.12-slim AS runtime

ARG C2PATOOL_VERSION=0.28.0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH" \
    VERIXA_DATA_DIR=/var/lib/verixa VERIXA_AI_DETECTOR_MODEL_DIR=/opt/models HF_HUB_OFFLINE=1

# ExifTool from Debian; c2patool from its GitHub release (pinned).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libimage-exiftool-perl curl ca-certificates \
    && curl -sSL -o /tmp/c2patool.tar.gz \
        "https://github.com/contentauth/c2patool/releases/download/v${C2PATOOL_VERSION}/v${C2PATOOL_VERSION}-x86_64-unknown-linux-gnu.tar.gz" \
    && tar -xzf /tmp/c2patool.tar.gz -C /usr/local/bin --strip-components=1 c2patool/c2patool \
    && rm /tmp/c2patool.tar.gz \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* \
    && c2patool --version && exiftool -ver

RUN groupadd --system verixa && useradd --system --gid verixa --create-home verixa \
    && mkdir -p /var/lib/verixa && chown verixa:verixa /var/lib/verixa

WORKDIR /srv/verixa
COPY --from=build /opt/venv /opt/venv
COPY --from=build /opt/models /opt/models
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

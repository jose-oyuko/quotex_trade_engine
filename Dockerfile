# syntax=docker/dockerfile:1
#
# Quotex Trade Engine as one image: the API, the engine and the built dashboard (docs/DOCKER.md).
# Three stages, so neither Node.js, git nor a compiler ends up in the image that runs.

# ---- 1. the dashboard ----------------------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. the backend's packages ---------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS python-deps
ENV UV_PROJECT_ENVIRONMENT=/app/backend/.venv \
    UV_PYTHON_PREFERENCE=only-system \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PIP_DISABLE_PIP_VERSION_CHECK=1
# git: the Quotex library is installed from GitHub (decision D-5).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.13.4
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ---- 3. what runs ------------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm
RUN groupadd --system --gid 10001 qte \
    && useradd --system --uid 10001 --gid qte --home-dir /nonexistent --shell /usr/sbin/nologin qte \
    && mkdir -p /data \
    && chown qte:qte /data

# The virtual environment keeps the path it was built at, so it works as copied.
COPY --from=python-deps /app/backend/.venv /app/backend/.venv
COPY backend/app /app/backend/app
COPY backend/alembic /app/backend/alembic
COPY backend/alembic.ini /app/backend/alembic.ini
COPY backend/scripts /app/backend/scripts
COPY --from=web /build/dist /app/frontend/dist
COPY docker/entrypoint.sh /usr/local/bin/qte-entrypoint
# (a carriage return from a Windows checkout would break `sh`; .gitattributes prevents it, this insures)
RUN sed -i 's/\r$//' /usr/local/bin/qte-entrypoint && chmod 0755 /usr/local/bin/qte-entrypoint

# CONTAINER=true lets the application listen on all addresses *inside* the container; it keeps the
# localhost-only host-name check on. The compose file publishes the port to 127.0.0.1 only.
ENV PATH="/app/backend/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CONTAINER=true \
    HOST=0.0.0.0 \
    PORT=8000 \
    ENVIRONMENT=production \
    DATA_DIR=/data \
    FRONTEND_DIR=/app/frontend/dist

WORKDIR /app/backend
USER qte
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"]
ENTRYPOINT ["qte-entrypoint"]
CMD ["python", "-m", "app"]

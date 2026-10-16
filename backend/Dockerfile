# syntax=docker/dockerfile:1
# MedDefender Twin API (FastAPI). Build from the repository root, because the seed reads
# shared/hospital_layout.json:
#   docker build -f backend/Dockerfile -t meddefender-backend .

# ---- dependencies: a locked virtualenv built with uv -------------------------------------
FROM python:3.12-slim AS deps
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /srv/backend
COPY backend/pyproject.toml backend/uv.lock ./
# Runtime dependencies only, exactly as locked (no dev tools, no embedded PostgreSQL).
RUN uv sync --frozen --no-dev --no-install-project

# ---- runtime -----------------------------------------------------------------------------
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin meddefender
COPY --from=deps /opt/venv /opt/venv
# Same relative layout as the repository: /srv/backend next to /srv/shared.
COPY shared /srv/shared
WORKDIR /srv/backend
COPY backend ./
RUN chmod 0755 docker-entrypoint.sh
USER meddefender

EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --start-period=30s --retries=12 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3).status == 200 else 1)"]

# Migrations and the (idempotent) seed run first; see docker-entrypoint.sh.
ENTRYPOINT ["./docker-entrypoint.sh"]
# One worker: the event bus is in-process (see docs/ARCHITECTURE.md, limitations).
# The API is reachable only through the frontend proxy, so its forwarded headers are trusted.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]

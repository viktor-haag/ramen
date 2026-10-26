# Stage 1: build the frontend
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: download Tectonic (LaTeX engine for PDF cover letters); curl stays out of the final image
FROM debian:bookworm-slim AS tectonic
ARG TARGETARCH
ARG TECTONIC_VERSION=0.17.0
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN set -eu; \
    case "$TARGETARCH" in \
      amd64) triple=x86_64-unknown-linux-musl; \
             sha=8533d07f9ccbd7a65824b9e0459041bca34af1eb33daba48f59215593753a3b7 ;; \
      arm64) triple=aarch64-unknown-linux-musl; \
             sha=b10954a95404f3ab2328d2fa59a5ebab8e657f893fab096f98be8db7c0c979b8 ;; \
      *) echo "unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/tectonic.tar.gz \
      "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40${TECTONIC_VERSION}/tectonic-${TECTONIC_VERSION}-${triple}.tar.gz"; \
    echo "${sha}  /tmp/tectonic.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/tectonic.tar.gz -C /usr/local/bin tectonic; \
    chmod 0755 /usr/local/bin/tectonic

# Stage 3: backend + built frontend
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    JOBTRACKER_DATA_DIR=/data \
    JOBTRACKER_PLUGIN_DIRS=/app/plugins \
    JOBTRACKER_FRONTEND_DIST=/app/frontend_dist \
    TECTONIC_CACHE_DIR=/opt/tectonic-cache \
    JOBTRACKER_TECTONIC_USER=ramen-tex
COPY --from=tectonic /usr/local/bin/tectonic /usr/local/bin/tectonic
# Unprivileged user that runs the LaTeX compiler. The package cache lives outside /data (the app locks /data
# down to 0700) and is owned by this user, so templates can fetch new packages.
RUN useradd --system --create-home ramen-tex \
    && mkdir -p /opt/tectonic-cache \
    && chown ramen-tex:ramen-tex /opt/tectonic-cache
WORKDIR /app
# Editable install: the migrations (alembic.ini, migrations/) are located relative to the app package,
# so the source tree must stay at /app/backend.
COPY backend/ /app/backend/
RUN pip install -e /app/backend
# Warm up the Tectonic cache with the default template so the first compile works offline.
RUN set -eu; \
    tmp="$(mktemp -d)"; \
    python -c "import sys; from app.latex.default_template import DEFAULT_TEMPLATE; open(sys.argv[1] + '/main.tex', 'w', encoding='utf-8').write(DEFAULT_TEMPLATE)" "$tmp"; \
    (cd "$tmp" && tectonic -X compile --untrusted main.tex); \
    rm -rf "$tmp"; \
    chown -R ramen-tex:ramen-tex /opt/tectonic-cache; \
    chmod -R a+rX /opt/tectonic-cache
COPY plugins/ /app/plugins/
COPY --from=frontend /build/dist /app/frontend_dist
WORKDIR /app/backend
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

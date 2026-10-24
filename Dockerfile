# Stage 1: build the frontend
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: backend + built frontend
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    JOBTRACKER_DATA_DIR=/data \
    JOBTRACKER_PLUGIN_DIRS=/app/plugins \
    JOBTRACKER_FRONTEND_DIST=/app/frontend_dist
WORKDIR /app
# Editable install: the migrations (alembic.ini, migrations/) are located relative to the app package,
# so the source tree must stay at /app/backend.
COPY backend/ /app/backend/
RUN pip install -e /app/backend
COPY plugins/ /app/plugins/
COPY --from=frontend /build/dist /app/frontend_dist
WORKDIR /app/backend
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

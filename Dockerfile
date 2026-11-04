# Single-container image for Google Cloud Run: Next.js frontend (public, $PORT) + FastAPI backend
# (private, 127.0.0.1:8000). Synthetic data, search index and model weights are baked in at build
# time, so a cold-started instance serves immediately and needs no persistent disk.
#
#   gcloud run deploy clinical-rag --source .        (see deploy/CLOUD_RUN.md)

FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# The /api proxy target is fixed at build time: the backend runs in the same container.
ENV BACKEND_URL=http://127.0.0.1:8000 NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 RAG_DATA_DIR=/app/data \
    HF_HUB_DISABLE_TELEMETRY=1 NEXT_TELEMETRY_DISABLED=1 PORT=8080
COPY --from=web /usr/local/bin/node /usr/local/bin/node

WORKDIR /app/backend
COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/knowledge ./knowledge
RUN pip install --no-cache-dir . && pip uninstall -y clinical-rag >/dev/null

# Bake the demo data: 30 synthetic patients, note + reference index, embedding/reranker weights.
# No API key is needed for this step.
RUN python -m app.seed && python -m app.warmup && rm -rf /root/.cache

COPY --from=web /web/.next/standalone /app/web
COPY --from=web /web/.next/static /app/web/.next/static
COPY deploy/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8080
CMD ["/app/entrypoint.sh"]

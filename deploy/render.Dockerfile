# Backend for Render's free tier (512 MB RAM, 0.1 vCPU). The frontend is hosted on Vercel and calls
# this API directly. Synthetic data, search index and the embedding model are baked in at build time
# because Render's free filesystem is wiped on every restart.
#
# Build context: repository root (see render.yaml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 RAG_DATA_DIR=/app/data RAG_RERANKER=none \
    HF_HUB_DISABLE_TELEMETRY=1
WORKDIR /app/backend
COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/knowledge ./knowledge
RUN pip install --no-cache-dir . && pip uninstall -y clinical-rag >/dev/null

# 30 synthetic patients, note + reference index, embedding model weights. No API key needed.
RUN python -m app.seed && python -m app.warmup && rm -rf /root/.cache

# Runtime tuning for 512 MB and a small CPU share: reranker off (set above), one ONNX thread,
# fewer glibc malloc arenas (less memory fragmentation).
ENV RAG_ONNX_THREADS=1 OMP_NUM_THREADS=1 MALLOC_ARENA_MAX=2
# Staging: public demo, so the backend refuses upload / URL ingest / delete / re-seed requests.
ENV RAG_KB_WRITES_ENABLED=false
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1 --log-level warning"]

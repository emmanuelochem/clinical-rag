#!/usr/bin/env bash
# Runs the backend (private) and frontend (public) in one container. If either exits, the container
# exits so Cloud Run replaces the instance.
set -euo pipefail

cd /app/backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning &
BACKEND=$!

trap 'kill -TERM "$BACKEND" "${FRONTEND:-}" 2>/dev/null || true' TERM INT

# Wait for the backend before accepting traffic, so the first request never hits a dead proxy.
for _ in $(seq 1 240); do
  if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/ping', timeout=1)" 2>/dev/null; then
    break
  fi
  kill -0 "$BACKEND" 2>/dev/null || { echo "backend exited during startup" >&2; exit 1; }
  sleep 0.5
done

cd /app/web
HOSTNAME=0.0.0.0 PORT="${PORT:-8080}" node server.js &
FRONTEND=$!
echo "clinical-rag: serving on port ${PORT:-8080}"

wait -n "$BACKEND" "$FRONTEND"
STATUS=$?
kill -TERM "$BACKEND" "$FRONTEND" 2>/dev/null || true
exit "$STATUS"

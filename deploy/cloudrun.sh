#!/usr/bin/env bash
# Deploy Clinical RAG to Google Cloud Run (free tier) with a Cloud Scheduler keep-alive.
#
# Usage (from the repo root, after `gcloud auth login`):
#   export GROQ_API_KEY=gsk_...            # only needed the first time (stored in Secret Manager)
#   PROJECT_ID=my-project ./deploy/cloudrun.sh
#
# Optional: REGION (default europe-west1), SERVICE (default clinical-rag),
#           KEEPALIVE_SCHEDULE (default every 10 min), ROTATE_KEY=1 to store a new Groq key.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID to your Google Cloud project ID}"
REGION="${REGION:-europe-west1}"           # Tier 1 region: free-tier pricing applies
SERVICE="${SERVICE:-clinical-rag}"
SECRET="${SECRET:-groq-api-key}"
SCHEDULE="${KEEPALIVE_SCHEDULE:-*/10 * * * *}"

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

gcloud config set project "$PROJECT_ID" >/dev/null

step "Enabling APIs (Cloud Run, Cloud Build, Artifact Registry, Secret Manager, Cloud Scheduler)"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com cloudscheduler.googleapis.com

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

step "Granting the default service account permission to build from source"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${RUNTIME_SA}" \
  --role=roles/run.builder --condition=None >/dev/null

step "Storing the Groq API key in Secret Manager ($SECRET)"
if gcloud secrets describe "$SECRET" >/dev/null 2>&1; then
  if [[ "${ROTATE_KEY:-0}" == "1" ]]; then
    : "${GROQ_API_KEY:?export GROQ_API_KEY to rotate the key}"
    printf %s "$GROQ_API_KEY" | gcloud secrets versions add "$SECRET" --data-file=-
  else
    echo "Secret exists; keeping it (ROTATE_KEY=1 to replace)."
  fi
else
  : "${GROQ_API_KEY:?export GROQ_API_KEY first (free key: https://console.groq.com/keys)}"
  printf %s "$GROQ_API_KEY" | gcloud secrets create "$SECRET" --data-file=- --replication-policy=automatic
fi
gcloud secrets add-iam-policy-binding "$SECRET" --member="serviceAccount:${RUNTIME_SA}" \
  --role=roles/secretmanager.secretAccessor >/dev/null

# Reuse the existing keep-alive token so the scheduler job keeps working across redeploys.
TOKEN="$(gcloud run services describe "$SERVICE" --region "$REGION" --format=json 2>/dev/null | python3 -c '
import json, sys
try:
    env = json.load(sys.stdin)["spec"]["template"]["spec"]["containers"][0].get("env", [])
    print(next((e["value"] for e in env if e.get("name") == "RAG_KEEPALIVE_TOKEN"), ""))
except Exception:
    pass' || true)"
TOKEN="${TOKEN:-$(openssl rand -hex 16)}"

step "Building and deploying $SERVICE to Cloud Run in $REGION (first build takes ~10 minutes)"
# Cost guardrails: scale to zero when idle, never more than one instance.
gcloud run deploy "$SERVICE" --source . --region "$REGION" --quiet \
  --allow-unauthenticated \
  --cpu 1 --memory 2Gi --concurrency 40 --timeout 300 \
  --min-instances 0 --max-instances 1 \
  --set-secrets "GROQ_API_KEY=${SECRET}:latest" \
  --set-env-vars "RAG_KEEPALIVE_TOKEN=${TOKEN}"

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
KEEPALIVE_URL="${URL}/api/keepalive?token=${TOKEN}"

step "Scheduling keep-alive ping ($SCHEDULE) with Cloud Scheduler"
JOB="${SERVICE}-keepalive"
if gcloud scheduler jobs describe "$JOB" --location "$REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$JOB" --location "$REGION" --schedule "$SCHEDULE" \
    --uri "$KEEPALIVE_URL" --http-method GET --attempt-deadline 120s >/dev/null
else
  gcloud scheduler jobs create http "$JOB" --location "$REGION" --schedule "$SCHEDULE" \
    --uri "$KEEPALIVE_URL" --http-method GET --attempt-deadline 120s \
    --description "Keeps Clinical RAG warm" >/dev/null
fi

step "Warming the new instance"
curl -fsS "$KEEPALIVE_URL" && echo

cat <<EOF

Deployed: ${URL}

Keep-alive endpoint (for Cloud Scheduler or an external cron such as cron-job.org / UptimeRobot):
  ${KEEPALIVE_URL}

Next: set a budget alert so you are notified before any charge (see deploy/CLOUD_RUN.md).
EOF

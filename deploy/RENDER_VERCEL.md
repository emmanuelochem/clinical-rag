# Free hosting: Vercel (frontend) + Render (backend)

```
Browser ──► Vercel: Next.js frontend (never sleeps, global CDN)
   │
   └──────► Render: FastAPI backend (one free web service, kept awake by a cron ping)
              └─► Groq API (chat model)
```

The browser calls the backend directly (`NEXT_PUBLIC_API_URL`), so long streaming answers are never
cut off by a proxy timeout. The backend must allow the Vercel site's address through **CORS**
(step 3).

**Measured under Render's free limits** (512 MB RAM, 0.1 CPU): memory peak ≈ 340 MiB; fast-mode
answer ≈ 7 s, agentic answer ≈ 20 s, differential ≈ 25 s; cold start (after a deploy or restart)
≈ 45 s plus ≈ 17 s model warm-up, which the keep-alive ping absorbs. The local reranker is off to fit
in 512 MB; retrieval still uses hybrid vector + keyword search.

## 1. Backend on Render (about 15 minutes)

Sign up at https://render.com with **GitHub**. Render may verify a card with a temporary $1 hold
before allowing a web service; you are not charged on the free plan.

Choose **one** of the two ways below.

### Option A: manual web service from the public repo (used for the live deployment)

This works even when Render can't connect to your GitHub account, but the repository must be
**public**.

1. **New → Web Service → Public Git Repository** → `https://github.com/emmanuelochem/clinical-rag`.
2. Fill in:

   | Setting | Value |
   |---|---|
   | Name | `clinical-rag-api` (Render may add a suffix, e.g. `clinical-rag-api-r7fg`) |
   | Language / Runtime | Docker |
   | Branch | `main` |
   | Dockerfile Path | `./deploy/render.Dockerfile` |
   | Docker Build Context Directory | `.` |
   | Region | Frankfurt |
   | Instance Type | **Free** |
   | Health Check Path | `/api/ping` (under *Advanced*) |

3. **Environment variables** (under *Advanced*, or *Environment* after creation):

   | Key | Value |
   |---|---|
   | `GROQ_API_KEY` | your key (free at https://console.groq.com/keys) |
   | `RAG_KEEPALIVE_TOKEN` | any long random string you choose, e.g. 32 letters and digits |
   | `RAG_CORS_ORIGIN_REGEX` | see step 3 |
   | `RAG_CORS_ORIGINS` | see step 3 |

4. **Create Web Service.** The first build takes about 10 minutes (it builds the synthetic patients,
   the search index and the embedding model into the image).

A public-repo service does **not** redeploy when you push. After backend changes, click
**Manual Deploy → Deploy latest commit**.

### Option B: Blueprint (needs Render connected to GitHub)

**New → Blueprint** → select the repo. Render reads [`render.yaml`](../render.yaml), asks for
`GROQ_API_KEY`, generates `RAG_KEEPALIVE_TOKEN` and redeploys automatically when backend files
change. If the repo list is empty or GitHub won't connect, give the Render GitHub App access to the
repo at https://github.com/settings/installations (Render → Configure → Repository access), or use
Option A. You still need to set the CORS values from step 3 to match your Vercel address.

### Check it

When the service shows **Live**, open `https://<your-render-url>/api/health` in a browser. You should
see JSON with `"status":"ok"` and `"reachable": true` under `llm`. The first load after a deploy can
take up to a minute.

## 2. Frontend on Vercel (about 5 minutes)

1. Sign up at https://vercel.com with **GitHub** (Hobby plan: free, no card, non-commercial use).
2. **Add New → Project** → import `clinical-rag`.
3. **Root Directory:** click *Edit* and choose `frontend`. The framework is detected as Next.js.
4. **Environment Variables:** add `NEXT_PUBLIC_API_URL` = your Render URL, e.g.
   `https://clinical-rag-api-r7fg.onrender.com`, with no trailing slash.
5. **Deploy.**

The **project name decides your addresses.** With the project named `frontend` under the team
`emmanuelochems-projects` (the live deployment), Vercel serves it at addresses like:

- `https://frontend-git-main-emmanuelochems-projects.vercel.app` (latest `main` branch)
- `https://frontend-<hash>-emmanuelochems-projects.vercel.app` (each individual deployment)
- a production domain listed under *Project → Domains* (use this one on a CV)

You can rename the project (*Settings → General → Project Name*) for a cleaner production domain
such as `clinical-rag.vercel.app`; then update the CORS values in step 3.

`NEXT_PUBLIC_API_URL` is built into the frontend. If the Render URL changes, update it in Vercel and
**redeploy** (*Deployments → ⋯ → Redeploy*).

## 3. Allow the Vercel site in the backend (CORS)

Without this, the browser blocks every request with *"No 'Access-Control-Allow-Origin' header is
present on the requested resource"*. Set these in Render → your service → **Environment**, then
**Save Changes** (the service restarts):

| Key | Value for the live deployment |
|---|---|
| `RAG_CORS_ORIGIN_REGEX` | `https://frontend[a-z0-9-]*-emmanuelochems-projects\.vercel\.app` |
| `RAG_CORS_ORIGINS` | `["https://YOUR-PRODUCTION-DOMAIN"]` |

- The **regex** allows every branch and deployment address of the `frontend` project in your
  Vercel team, and blocks other people's Vercel apps. If you rename the project, replace `frontend`
  with the new name.
- `RAG_CORS_ORIGINS` is a JSON list: keep the square brackets and quotes, no trailing slash. Add
  any other exact address, such as a renamed project's domain or a custom domain, separated by
  commas: `["https://a.vercel.app", "https://b.example.com"]`.
- The Blueprint (`render.yaml`) defaults to `clinical-rag.vercel.app` and
  `clinical-rag…vercel.app`, which only match a project named `clinical-rag`.

The same error also appears while the backend is asleep, restarting or crashed. If CORS still
fails after the restart, open `/api/health` first (step 1, *Check it*).

## 4. Keep the backend awake (cron ping, 2 minutes)

Render's free services sleep after 15 minutes without traffic. A ping every 10 minutes keeps it
awake, and the endpoint also loads the models after a restart so visitors don't wait for that.

1. Sign up at https://cron-job.org (free).
2. **Create cronjob** → URL:
   `https://<your-render-url>/api/keepalive?token=YOUR_RAG_KEEPALIVE_TOKEN` → schedule **every 10
   minutes** → save.
3. The job history should show `200` responses with `"status":"ok"`. A `401` means the token in the
   URL doesn't match `RAG_KEEPALIVE_TOKEN`.

Alternative: UptimeRobot (free), an HTTP monitor on the same URL every 5 minutes.

**Hours budget:** a free Render account has 750 instance-hours a month; one service running all
month uses about 744. Don't run another free web service in the same account, or both run out of
hours before the month ends.

## Updating

Push to `main` on GitHub:
- **Vercel** rebuilds the frontend on every push. To skip backend-only commits, set
  *Settings → Git → Ignored Build Step* to `git diff --quiet HEAD^ HEAD ./`.
- **Render, Option A (public repo):** click **Manual Deploy → Deploy latest commit** after backend
  changes.
- **Render, Option B (Blueprint):** rebuilds automatically when `backend/`,
  `deploy/render.Dockerfile` or `render.yaml` change (about 10 minutes per build).

## Limitations of the free setup

- **Data resets on restart or redeploy:** uploaded documents and the audit log live on Render's
  temporary disk. The bundled synthetic data and reference library are always there.
- **0.1 CPU:** answers take longer than on a laptop (see the timings above).
- **Groq free tier:** many requests within a minute can hit Groq's rate limit; the app waits and
  retries automatically, so answers arrive later. Fast mode uses fewer requests.
- **No login:** anyone with the link can use the app and your Groq quota.
- **Knowledge-base changes are locked:** the hosted images set `RAG_KB_WRITES_ENABLED=false`, so the
  backend refuses file upload, URL ingest, document delete and re-seed requests with `403`, and the
  Knowledge base page shows a notice and a toast instead. To allow them (for example on a private
  deployment), set `RAG_KB_WRITES_ENABLED=true` in Render and restore the commented-out code in
  `frontend/app/knowledge/page.tsx`.

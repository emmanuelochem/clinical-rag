# Free hosting: Vercel (frontend) + Render (backend)

```
Browser ──► Vercel: Next.js frontend (never sleeps, global CDN)
   │
   └──────► Render: FastAPI backend (one free web service, kept awake by a cron ping)
              └─► Groq API (chat model)
```

The browser calls the backend directly (`NEXT_PUBLIC_API_URL`), so long streaming answers are never
cut off by a proxy timeout. The backend allows the Vercel site through CORS.

**Measured under Render's free limits** (512 MB RAM, 0.1 CPU): memory peak ≈ 340 MiB; fast-mode
answer ≈ 7 s, agentic answer ≈ 20 s, differential ≈ 25 s; cold start (after a deploy or restart)
≈ 45 s plus ≈ 17 s model warm-up, which the keep-alive ping absorbs. The local reranker is off to fit
in 512 MB; retrieval still uses hybrid vector + keyword search.

## 1. Backend on Render (about 15 minutes)

1. Sign up at https://render.com with **GitHub**. Render may verify a card with a temporary $1 hold
   before allowing a web service; you are not charged on the free plan.
2. **New → Blueprint** → connect GitHub and give Render access to the `clinical-rag` repository →
   select it. Render reads [`render.yaml`](../render.yaml) and shows one service,
   `clinical-rag-api` (Free plan, Frankfurt).
3. When asked for `GROQ_API_KEY`, paste your key (free at https://console.groq.com/keys). It is
   stored as a Render secret, never in the repo.
4. Click **Apply**. The first build takes about 10 minutes (it builds the synthetic patients, the
   search index and the embedding model into the image).
5. When the service shows **Live**, copy its URL, e.g. `https://clinical-rag-api.onrender.com`, and
   check `https://clinical-rag-api.onrender.com/api/health` in your browser.
6. Copy the keep-alive token: service → **Environment** → `RAG_KEEPALIVE_TOKEN` → reveal value.

## 2. Frontend on Vercel (about 5 minutes)

1. Sign up at https://vercel.com with **GitHub** (Hobby plan: free, no card, non-commercial use).
2. **Add New → Project** → import `clinical-rag`.
3. **Root Directory:** click *Edit* and choose `frontend`. The framework is detected as Next.js.
4. **Environment Variables:** add `NEXT_PUBLIC_API_URL` = your Render URL from step 1.5, with no
   trailing slash.
5. Name the project `clinical-rag` and click **Deploy**. Your site will be
   `https://clinical-rag.vercel.app` (or `clinical-rag-xxxx.vercel.app` if the name is taken).

**CORS:** the backend already allows `https://clinical-rag.vercel.app` and any
`https://clinical-rag…vercel.app` preview URL. If your Vercel address is different (for example a
custom domain), set `RAG_CORS_ORIGINS` in Render to `["https://your-domain"]` and redeploy.

`NEXT_PUBLIC_API_URL` is built into the frontend. If the Render URL ever changes, update the variable
in Vercel and **redeploy**.

## 3. Keep the backend awake (cron ping, 2 minutes)

Render's free services sleep after 15 minutes without traffic. A ping every 10 minutes keeps it awake,
and the endpoint also loads the models after a restart so visitors don't wait for that.

1. Sign up at https://cron-job.org (free).
2. **Create cronjob** → URL:
   `https://clinical-rag-api.onrender.com/api/keepalive?token=YOUR_TOKEN` → schedule **every 10
   minutes** → save.
3. The job history should show `200` responses with `"status":"ok"`.

Alternative: UptimeRobot (free), an HTTP monitor on the same URL every 5 minutes.

**Hours budget:** a free Render account has 750 instance-hours a month; one service running all
month uses about 744. Don't run another free web service in the same account, or both run out of
hours before the month ends.

## Updating

Push to `main` on GitHub:
- **Render** rebuilds the backend only when `backend/`, `deploy/render.Dockerfile` or `render.yaml`
  change (each build takes about 10 minutes).
- **Vercel** rebuilds the frontend on every push. To skip backend-only commits, set
  *Settings → Git → Ignored Build Step* to `git diff --quiet HEAD^ HEAD ./`.

## Limitations of the free setup

- **Data resets on restart or redeploy:** uploaded documents and the audit log live on Render's
  temporary disk. The bundled synthetic data and reference library are always there.
- **0.1 CPU:** answers take longer than on a laptop (see the timings above).
- **Groq free tier:** many requests within a minute can hit Groq's rate limit; the app waits and
  retries automatically, so answers arrive later. Fast mode uses fewer requests.
- **No login:** anyone with the link can use the app and your Groq quota.

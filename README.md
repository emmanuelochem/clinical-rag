# Clinical RAG

A **clinical decision-support** web app for clinicians. It answers questions about a patient's record, charts lab and vital trends, and produces **evidence-cited differential diagnoses**. Every claim links back to the record, a clinical note or a medical reference passage.

> ⚠️ **Decision support, not diagnosis.** Outputs come from a language model and may be wrong or incomplete. The bundled patient data is **synthetic**. Before using real patient data, see [Going to production](#going-to-production).

## Features

| | |
|---|---|
| **Patient workspace** | Problems, meds, allergies, latest labs/vitals with H/L/critical flags, encounter timeline, NEWS2 |
| **Trend charts** | Any lab or vital over time with the reference range shaded and out-of-range points highlighted; BP plotted as systolic/diastolic |
| **Clinical assistant** | Chat scoped to one patient plus the reference library. Streams answers with inline `[n]` citations, adds charts when you ask about trends, and shows the agent trace |
| **Differential Dx** | Symptoms + presentation → ranked differentials (likelihood, can't-miss flag, supporting/against findings each with a citation, next steps, workup, information gaps) |
| **Deterministic safety screen** | Rules that don't use the LLM: critical values, NEWS2, qSOFA, symptom red flags (ACS, PE, stroke, GI bleed, sepsis…), medication–lab checks (ACEi + K⁺, metformin + eGFR, NSAID + CKD/HF, anticoagulant + bleeding, SGLT2i + acute illness) |
| **Cohort analytics** | Prevalence, age bands, treatment-target attainment (HbA1c, BP, LDL), HbA1c trend, abnormal-result frequency, encounter volume (every chart also has a table view) |
| **Knowledge base** | Upload PDF/DOCX/HTML/MD/TXT/CSV or ingest URLs; bulk-load MedlinePlus; retrieval test bench with per-hit diagnostics |
| **Audit log** | Every record view, assistant query and differential is logged (`GET /api/audit`) |

## Architecture

```
Next.js (React 19, Tailwind 4, Recharts) ──/api──►  FastAPI
                                                     ├─ SQLite: patients, encounters, conditions, observations (LOINC),
                                                     │          medications, allergies, notes, documents, audit log
                                                     ├─ LanceDB: chunk vectors + BM25 full-text index (embedded, on disk)
                                                     ├─ Chat LLM: Groq (default) · Gemini · any OpenAI-compatible API · Ollama
                                                     └─ Local, in-process: embeddings + cross-encoder reranker (fastembed/ONNX)
```

Only the chat model runs in the cloud. Embeddings, reranking, search, the database and the safety rules all run inside the backend. They need no API key and no GPU.

**Retrieval pipeline** (`backend/app/retrieval/hybrid.py`)

1. Each query runs through **dense vector search** and **BM25** (LanceDB FTS with stemming).
2. Results from every query are merged with **Reciprocal Rank Fusion**.
3. The top candidates are **reranked** by a local cross-encoder (`ms-marco-MiniLM-L-6-v2` by default, via fastembed). LLM listwise reranking is an option.
4. **MMR** removes near-duplicate passages.
5. Each hit is expanded with its **neighbouring chunks**.
6. Patient notes are **hard-filtered by `patient_id`**, so one patient's text can't leak into another's answer (there's a test for this).

**Ingestion** (`backend/app/ingest/`)

- Structure-aware parsers: PDF headings are detected by font size, PDF tables are extracted as Markdown, DOCX heading styles and tables are preserved, and HTML boilerplate is stripped.
- Chunking follows section boundaries and keeps a heading breadcrumb. Tables are kept whole or split by rows with the header repeated, and consecutive chunks overlap.
- Each chunk is embedded together with its "document title › section" context.

**Agent** (`backend/app/agent/orchestrator.py`)

- **Plan:** rewrite the question using the chat history, break it into note queries, reference queries and the labs to chart.
- **Gather:** read the structured record and trends, then search the notes and the reference library.
- **Reflect:** check whether the evidence is enough. If not, run follow-up queries, for up to *N* rounds.
- **Answer:** stream a grounded, cited answer. Citations are validated on the server.
- **Fast mode** skips the LLM planning and reflection steps.

## Quick start

You need Python 3.11+, Node 20+ and a **free Groq API key** from https://console.groq.com/keys. No GPU, no Ollama.

```bash
make install
```

Put your key in `.env` (created by `make install`):

```bash
GROQ_API_KEY=gsk_...
```

```bash
make seed
```

```bash
make dev
```

Open http://localhost:3000 (API docs: http://localhost:8000/docs).

`make seed` doesn't need the key. On first run it downloads the local embedding model (~70 MB) and the reranker (~80 MB) from Hugging Face and caches them in `backend/data/models`. Patient records, charts, cohort analytics and search work without a key; the assistant and differentials need one.

**Docker:** put the key in `.env`, then:

```bash
docker compose up --build
```

```bash
docker compose exec backend python -m app.seed
```

**Hosting for free:**
- **Vercel + Render** (no Google/AWS billing needed): frontend on Vercel, backend on Render's free tier, kept awake by a cron ping. See [deploy/RENDER_VERCEL.md](deploy/RENDER_VERCEL.md).
- **Google Cloud Run** (free tier, needs a billing account): one-command deploy with a keep-alive job. See [deploy/CLOUD_RUN.md](deploy/CLOUD_RUN.md).

### Choosing a chat provider

| Provider | Setup in `.env` | Default models (answer / planning) |
|---|---|---|
| **Groq** (default) | `GROQ_API_KEY=…` | `openai/gpt-oss-120b` / `openai/gpt-oss-20b` |
| **Gemini** | `RAG_LLM_PROVIDER=gemini` and `GEMINI_API_KEY=…` ([free key](https://aistudio.google.com/apikey)) | `gemini-flash-latest` / `gemini-flash-lite-latest` |
| **Other OpenAI-compatible** (OpenRouter, Mistral, NVIDIA NIM, vLLM, LM Studio…) | `RAG_LLM_PROVIDER=openai_compatible`, `RAG_LLM_BASE_URL`, `RAG_LLM_API_KEY`, `RAG_CHAT_MODEL` | — |
| **Ollama** (fully local) | `RAG_LLM_PROVIDER=ollama`, optionally `RAG_EMBED_PROVIDER=ollama`; `make ollama-models` or `docker compose --profile ollama up` | `qwen2.5:7b-instruct` |

Model IDs on hosted providers change over time. The status indicator in the header (and `GET /api/health`) lists the provider's live models and warns if a configured model is missing; override with `RAG_CHAT_MODEL` / `RAG_PLANNER_MODEL`. Planning and evidence checks go to the smaller planner model, which saves quota (Groq limits each model separately).

**Free-tier rate limits.** Agentic mode makes about 3 calls per question (plan, evidence check, answer); a differential makes 1. Rate-limited calls (HTTP 429) are retried automatically using the provider's `Retry-After`. If you still hit the daily cap, switch the chat to **Fast** mode (1 call per question) or wait for the quota to reset.

> **Privacy:** free cloud tiers are fine for the **synthetic** data here. Do **not** send real patient data to them: free tiers may use prompts to improve their services and don't offer the data-processing agreements (e.g. a HIPAA BAA) health data requires. For real data, use the Ollama setup or a paid provider that signs one.

## Medical knowledge base

- **Bundled:** 16 concise reference summaries covering the synthetic cohort's conditions and acute presentations (`backend/knowledge/`). They were written for this demo and must be verified against current guidelines.
- **MedlinePlus** (public domain, U.S. National Library of Medicine): download the *Health Topics* XML from https://medlineplus.gov/xml.html, then run:

```bash
cd backend && .venv/bin/python -m app.seed --medlineplus mplus_topics_YYYY-MM-DD.xml
```

  By default only topics relevant to the cohort are loaded. Add `--all-topics` for all ~1,000.
- **Your own guidelines/protocols:** upload them on the Knowledge base page or `POST /api/documents`. Only ingest material you are licensed to use.

## Models

All settings are `RAG_*` variables in `.env`; see `.env.example`.

| Use | Default | Alternatives |
|---|---|---|
| Chat / differential | Groq `openai/gpt-oss-120b` | Gemini Flash, any OpenAI-compatible model, Ollama `qwen2.5:14b-instruct` |
| Planner (JSON planning, evidence checks) | Groq `openai/gpt-oss-20b` | any small, fast model |
| Embeddings (local) | `BAAI/bge-small-en-v1.5` (384-d) | `BAAI/bge-base-en-v1.5`, `nomic-ai/nomic-embed-text-v1.5`, or Ollama |
| Reranker (local) | `Xenova/ms-marco-MiniLM-L-6-v2` | `BAAI/bge-reranker-base` (more accurate, ~1 GB), `llm`, `none` |

The search index records which embedding model built it. If you change the embedding model, the app refuses to mix vectors and shows a "re-index needed" banner; rebuild with `python -m app.seed --wipe-all`.

## Evaluation and tests

```bash
make test
```

```bash
make eval
```

`make test` runs the pytest suite (parsers, chunker, safety rules, NEWS2, scoped hybrid retrieval, full chat and differential SSE flows, upload/delete) plus the TypeScript typecheck. Provider behaviour (streaming, rate-limit retries, JSON-mode fallback, auth errors) is tested against a mocked HTTP API. It uses deterministic stand-in models, so it needs no API key or network.

`make eval` compares vector, BM25, hybrid and hybrid+rerank retrieval on `app/eval/gold.jsonl` (hit@1, hit@k, MRR). Add questions from your own content to track retrieval quality as you tune it.

## Synthetic data

`app/clinical/synthetic.py` generates a deterministic cohort (seeded). Comorbidity bundles drive lab trajectories over ~3 years, and medication starts bend those curves (e.g. HbA1c falling after metformin, LDL after a statin). Some patients end with an acute ED presentation: ACS, decompensated heart failure, pneumonia, hyperglycaemia, hyperkalaemia on an ACE inhibitor after NSAID use, or symptomatic anaemia with melaena. These exercise the safety screen and the differential workflow. Regenerate with `python -m app.seed --reset --patients 60 --seed 7`.

## API

| Method | Path | |
|---|---|---|
| GET | `/api/health` | LLM provider status, key/model checks, embedding index status, counts |
| GET | `/api/patients?q=` · `/api/patients/{id}` | List / full record + safety screen |
| GET | `/api/patients/{id}/series?codes=4548-4,33914-3` | Time series for charts |
| GET | `/api/patients/{id}/notes` · `/api/notes/{id}` | Clinical notes |
| POST | `/api/chat` | **SSE** agent stream (`status`, `plan`, `alerts`, `chart`, `sources`, `token`, `done`) |
| POST | `/api/differential` | **SSE** differential stream (`alerts`, `sources`, `result`) |
| POST | `/api/search` | Raw hybrid retrieval with diagnostics |
| GET/POST/DELETE | `/api/documents…` | Knowledge base management |
| GET | `/api/cohort` · `/api/audit` | Analytics · audit log |
| GET | `/api/ping` · `/api/keepalive?token=` | Liveness · warm-up target for an external cron |
| POST | `/api/admin/seed` | Generate synthetic data |

## Going to production

This is a well-structured prototype, not a certified medical device. Before using real patient data you need at least:

- **Authentication and authorisation** (SSO/OIDC, role-based access, patient-level access control). There is currently **no auth**.
- **PHI handling:** a chat provider under a signed data-processing agreement/BAA (or Ollama on-premises; never a free tier), encryption at rest (SQLite/LanceDB volume), TLS, retention policies, and HIPAA/GDPR compliance review.
- **EHR integration:** map FHIR R4 `Patient`, `Condition`, `Observation`, `MedicationRequest`, `AllergyIntolerance`, `Encounter` and `DocumentReference` into the existing schema (`app/store/db.py`).
- **Lab-specific reference ranges** (the catalog uses typical adult ranges), plus sex- and age-specific ranges.
- **Clinical validation and governance** of prompts, rules and models, including regulatory assessment (e.g. FDA CDS guidance, EU MDR).
- Move the SQLite audit log to an append-only store.

## Project layout

```
backend/
  app/
    agent/        orchestrator (plan → gather → reflect → answer), prompts
    clinical/     catalog (LOINC/ranges), synthetic generator, repository, safety rules, differential engine
    ingest/       parsers (PDF/DOCX/HTML/MD/CSV), chunker, pipeline, MedlinePlus loader
    retrieval/    hybrid retriever (vector + BM25 → RRF → rerank → MMR → neighbours)
    providers/    LLMs (OpenAI-compatible: Groq/Gemini/…, Ollama), local + Ollama embeddings, rerankers
    store/        SQLite, LanceDB
    eval/         retrieval evaluation harness + gold set
    main.py       FastAPI app · seed.py CLI
  knowledge/      bundled reference library
  tests/
frontend/
  app/            pages: patients, patients/[id], cohort, assistant, knowledge
  components/     Chat, DifferentialPanel, TrendChart, SourceDrawer, CitedMarkdown, AppShell
```

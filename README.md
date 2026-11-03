# Clinical RAG

A local-first **clinical decision-support** web app for clinicians. It answers questions about a patient's record, charts lab and vital trends, and produces **evidence-cited differential diagnoses**. Every claim links back to the record, a clinical note or a medical reference passage.

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
                                                     └─ Ollama: chat model + embedding model (local)
```

**Retrieval pipeline** (`backend/app/retrieval/hybrid.py`)

1. Each query runs through **dense vector search** and **BM25** (LanceDB FTS with stemming).
2. Results from every query are merged with **Reciprocal Rank Fusion**.
3. The top candidates are **reranked** by a local cross-encoder (`BAAI/bge-reranker-base`). LLM listwise reranking is the fallback.
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

### Option A: Docker (everything local)

```bash
cp .env.example .env
```

```bash
docker compose up --build
```

```bash
docker compose exec backend python -m app.seed
```

Open http://localhost:3000. The first run pulls `qwen2.5:7b-instruct` (~4.7 GB) and `nomic-embed-text`. For the cross-encoder reranker, set `BACKEND_EXTRAS=[rerank]` in `.env` before building (this adds PyTorch, ~2 GB).

### Option B: Native

Requires Python 3.11+, Node 20+ and [Ollama](https://ollama.com).

```bash
make install
```

```bash
make models
```

```bash
make seed
```

```bash
make dev
```

Backend: http://localhost:8000/docs · Frontend: http://localhost:3000

## Medical knowledge base

- **Bundled:** 16 concise reference summaries covering the synthetic cohort's conditions and acute presentations (`backend/knowledge/`). They were written for this demo and must be verified against current guidelines.
- **MedlinePlus** (public domain, U.S. National Library of Medicine): download the *Health Topics* XML from https://medlineplus.gov/xml.html, then run:

```bash
cd backend && .venv/bin/python -m app.seed --medlineplus mplus_topics_YYYY-MM-DD.xml
```

  By default only topics relevant to the cohort are loaded. Add `--all-topics` for all ~1,000.
- **Your own guidelines/protocols:** upload them on the Knowledge base page or `POST /api/documents`. Only ingest material you are licensed to use.

## Models

Configure in `.env` (all `RAG_*`). Bigger models give noticeably better differentials and JSON reliability:

| Use | Suggested |
|---|---|
| Chat / differential | `qwen2.5:7b-instruct` (default), `qwen2.5:14b-instruct`, `llama3.1:8b`, or a medical fine-tune |
| Planner (fast JSON) | `qwen2.5:3b-instruct` via `RAG_PLANNER_MODEL` |
| Embeddings | `nomic-embed-text` (default), `mxbai-embed-large`, `bge-m3`. Change the query/doc prefixes to match |
| Reranker | `cross-encoder` (`BAAI/bge-reranker-base`, or `-large`), `llm`, or `none` |

Changing the embedding model requires re-indexing: `python -m app.seed --wipe-all`.

## Evaluation and tests

```bash
make test
```

```bash
make eval
```

`make test` runs the pytest suite (parsers, chunker, safety rules, NEWS2, scoped hybrid retrieval, full chat and differential SSE flows, upload/delete) plus the TypeScript typecheck. It uses deterministic stand-in models, so it needs no Ollama.

`make eval` compares vector, BM25, hybrid and hybrid+rerank retrieval on `app/eval/gold.jsonl` (hit@1, hit@k, MRR). Add questions from your own content to track retrieval quality as you tune it.

## Synthetic data

`app/clinical/synthetic.py` generates a deterministic cohort (seeded). Comorbidity bundles drive lab trajectories over ~3 years, and medication starts bend those curves (e.g. HbA1c falling after metformin, LDL after a statin). Some patients end with an acute ED presentation: ACS, decompensated heart failure, pneumonia, hyperglycaemia, hyperkalaemia on an ACE inhibitor after NSAID use, or symptomatic anaemia with melaena. These exercise the safety screen and the differential workflow. Regenerate with `python -m app.seed --reset --patients 60 --seed 7`.

## API

| Method | Path | |
|---|---|---|
| GET | `/api/health` | Ollama status, missing models, counts |
| GET | `/api/patients?q=` · `/api/patients/{id}` | List / full record + safety screen |
| GET | `/api/patients/{id}/series?codes=4548-4,33914-3` | Time series for charts |
| GET | `/api/patients/{id}/notes` · `/api/notes/{id}` | Clinical notes |
| POST | `/api/chat` | **SSE** agent stream (`status`, `plan`, `alerts`, `chart`, `sources`, `token`, `done`) |
| POST | `/api/differential` | **SSE** differential stream (`alerts`, `sources`, `result`) |
| POST | `/api/search` | Raw hybrid retrieval with diagnostics |
| GET/POST/DELETE | `/api/documents…` | Knowledge base management |
| GET | `/api/cohort` · `/api/audit` | Analytics · audit log |
| POST | `/api/admin/seed` | Generate synthetic data |

## Going to production

This is a well-structured prototype, not a certified medical device. Before using real patient data you need at least:

- **Authentication and authorisation** (SSO/OIDC, role-based access, patient-level access control). There is currently **no auth**.
- **PHI handling:** encryption at rest (SQLite/LanceDB volume), TLS, retention policies, and HIPAA/GDPR compliance review. Local models keep data on-premises, which helps.
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
    providers/    Ollama LLM + embeddings, rerankers
    store/        SQLite, LanceDB
    eval/         retrieval evaluation harness + gold set
    main.py       FastAPI app · seed.py CLI
  knowledge/      bundled reference library
  tests/
frontend/
  app/            pages: patients, patients/[id], cohort, assistant, knowledge
  components/     Chat, DifferentialPanel, TrendChart, SourceDrawer, CitedMarkdown, AppShell
```

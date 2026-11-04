.PHONY: install ollama-models seed backend frontend dev test eval

install:            ## Install backend and frontend deps
	cd backend && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
	cd frontend && npm install
	@test -f .env || cp .env.example .env
	@grep -q '^GROQ_API_KEY=.' .env || echo "\n>> Next: put your free Groq key in .env (GROQ_API_KEY=...). Get one at https://console.groq.com/keys\n"

ollama-models:      ## Only for the fully local setup (RAG_LLM_PROVIDER=ollama)
	ollama pull qwen2.5:7b-instruct
	ollama pull nomic-embed-text

seed:               ## Generate 30 synthetic patients and index notes + bundled reference library (no API key needed)
	cd backend && set -a && . ../.env && set +a && .venv/bin/python -m app.seed

backend:
	cd backend && set -a && . ../.env && set +a && .venv/bin/uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

dev:                ## Run backend and frontend together
	$(MAKE) -j2 backend frontend

test:
	cd backend && .venv/bin/python -m pytest -q
	cd frontend && npm run typecheck

eval:               ## Compare vector / BM25 / hybrid / hybrid+rerank retrieval
	cd backend && set -a && . ../.env && set +a && .venv/bin/python -m app.eval.run

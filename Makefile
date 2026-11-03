.PHONY: install models seed backend frontend dev test eval

install:            ## Install backend (with cross-encoder reranker) and frontend deps
	cd backend && python3 -m venv .venv && .venv/bin/pip install -e '.[rerank,dev]'
	cd frontend && npm install

models:             ## Pull local models into Ollama
	ollama pull qwen2.5:7b-instruct
	ollama pull nomic-embed-text

seed:               ## Generate 30 synthetic patients and index notes + bundled reference library
	cd backend && .venv/bin/python -m app.seed

backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

dev:                ## Run backend and frontend together
	$(MAKE) -j2 backend frontend

test:
	cd backend && .venv/bin/python -m pytest -q
	cd frontend && npm run typecheck

eval:               ## Compare vector / BM25 / hybrid / hybrid+rerank retrieval
	cd backend && .venv/bin/python -m app.eval.run

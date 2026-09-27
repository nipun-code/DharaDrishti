# DharaDrishti

AI legal research assistant for Indian statutes (BNS, BNSS, BSA, IPC, IT Act, …), built on hybrid
RAG over PostgreSQL full-text search + pgvector.

> Status: Phase 4 (LLM layer, generation, guardrails). Full README (architecture, guardrails, eval results) comes later.

## Quick start (Docker)

```bash
cp .env.example .env          # then set POSTGRES_PASSWORD and JWT_SECRET_KEY
docker compose up --build
docker compose exec api alembic upgrade head
```

| Service  | URL                                  |
|----------|--------------------------------------|
| Frontend | http://localhost:5173                |
| API      | http://localhost:8000                |
| API docs | http://localhost:8000/docs           |
| Health   | http://localhost:8000/health/live, http://localhost:8000/health/ready |

## Commands

```bash
docker compose exec api pytest -q                 # backend tests (+ coverage, >= 80%)
docker compose exec api alembic upgrade head      # migrations
docker compose exec api python -m app.cli create-admin --email you@example.com   # prompts for password
docker compose exec api python -m app.cli ingest --file /data/raw/<file>.pdf --act CODE --name "Full name" --year YYYY --wait
docker compose exec api python -m app.cli load-mappings          # data/mappings/ipc_bns.csv
docker compose exec api python -m app.cli download-models        # pre-fetch embedder + re-ranker (~1.2 GB)
docker compose exec api sh -c "ruff check . && ruff format --check . && mypy app"   # lint
```

## Local backend development (without Docker for the API)

```bash
docker compose up -d postgres redis
cd backend
python -m venv .venv && . .venv/Scripts/activate   # Windows; use .venv/bin/activate elsewhere
pip install -e ".[dev]"
cp ../.env.example .env                            # DATABASE_URL/REDIS_URL point at localhost
uvicorn app.main:create_app --factory --reload
```

## Data

Legal source files are **user-provided** and never generated:

- `data/raw/` — bare act PDFs
- `data/mappings/ipc_bns.csv` — verified IPC → BNS mapping table
- `data/eval/golden.jsonl` — evaluation dataset

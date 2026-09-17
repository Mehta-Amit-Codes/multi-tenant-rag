# Multi-Tenant RAG-as-a-Service

[![Diagram](https://img.shields.io/badge/gitdiagram-view%20architecture-blue)](https://gitdiagram.com/mehta-amit-codes/multi-tenant-rag)

Reference implementation of the "Multi-Tenant RAG-as-a-Service" blueprint:
tenant isolation, onboarding, incremental ingestion, usage metering, rate
limiting, and API-key auth.

## Isolation model (the core of this project)

Two independent layers, so a bug in one doesn't cause a leak:

1. **Application-level filtering** — every query in `services/` explicitly
   filters by `tenant_id`.
2. **Postgres Row-Level Security** — `db_init.sql` adds RLS policies that
   restrict every row to `current_setting('app.tenant_id')`, which
   `core/db_session.py` sets per-request. Even a forgotten `WHERE` clause
   cannot return another tenant's rows.

## Run it

```bash
cp .env.example .env
# then edit .env and fill in your real GROK_API_KEY

docker compose up -d postgres redis
pip install -r requirements.txt

python scripts/create_tables.py
psql postgresql://rag:rag@localhost:5432/rag -f db_init.sql

uvicorn app.main:app --reload
```

`.env` is loaded automatically (via `python-dotenv`) by `main.py`, `scripts/create_tables.py`, and `streamlit_app.py` — no need to `export` variables manually in each terminal. It's git-ignored, so never commit it; `.env.example` documents every variable the app reads.

If you run everything through `docker compose up` instead (including the `api` service), Compose injects `GROK_API_KEY` from your shell environment via `${GROK_API_KEY}` in `docker-compose.yml` — either export it in your shell first, or Compose also auto-reads a `.env` file in the project root for variable substitution, so the same `.env` works for both paths.

## Walkthrough

```bash
# 1. Onboard two tenants
curl -X POST localhost:8000/tenants -d '{"name": "Acme Corp"}' -H "Content-Type: application/json"
# -> {"tenant_id": "...", "api_key": "rag_live_..."}   <- save this, shown once

curl -X POST localhost:8000/tenants -d '{"name": "Globex Inc"}' -H "Content-Type: application/json"

# 2. Ingest a document for Acme only
curl -X POST localhost:8000/documents \
  -H "X-API-Key: <acme_key>" -H "Content-Type: application/json" \
  -d '{"filename": "handbook.txt", "text": "Acme'\''s refund policy is 30 days."}'

# 3. Query as Acme -> gets the answer
curl -X POST localhost:8000/query \
  -H "X-API-Key: <acme_key>" -H "Content-Type: application/json" \
  -d '{"question": "What is the refund policy?"}'

# 4. Query as Globex -> empty context, model says it doesn't know
#    (proves isolation: Globex cannot see Acme's document)
curl -X POST localhost:8000/query \
  -H "X-API-Key: <globex_key>" -H "Content-Type: application/json" \
  -d '{"question": "What is the refund policy?"}'

# 5. Re-ingest the identical text -> status: "unchanged", 0 chunks embedded
curl -X POST localhost:8000/documents \
  -H "X-API-Key: <acme_key>" -H "Content-Type: application/json" \
  -d '{"filename": "handbook.txt", "text": "Acme'\''s refund policy is 30 days."}'

# 6. Check usage
curl localhost:8000/usage -H "X-API-Key: <acme_key>"

# 7. Hammer the rate limit (61st request in a burst -> 429)
for i in $(seq 1 65); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8000/query \
    -H "X-API-Key: <acme_key>" -H "Content-Type: application/json" \
    -d '{"question": "test"}'
done
```

## Streamlit UI

A thin client over the API — onboarding, ingestion, query, and a usage
dashboard, one tab each. Useful as a demo without needing `curl`.

```bash
export API_BASE_URL=http://localhost:8000   # default, can omit
streamlit run streamlit_app.py
```

Flow: **Onboard Tenant** tab creates a tenant and logs you in with its key
(shown once, copy it) → **Ingest Documents** to upload text → **Query** to
ask questions with retrieved sources shown in an expander → **Usage** for
live token/query/storage metrics. Log out and onboard a second tenant to
see isolation firsthand (its queries return no results from the first
tenant's documents).

## Project layout

```
app/
  core/
    auth.py          # API key hashing + verification, get_current_tenant dependency
    db_session.py     # per-request session that pins Postgres RLS to one tenant
    rate_limit.py      # Redis token-bucket, per-tenant
  models/
    db.py              # SQLAlchemy models (Tenant, Document, Chunk, UsageEvent, ...)
  services/
    embedding.py        # chunking + sentence-transformers embeddings
    ingestion.py          # hash-based idempotent ingest/update/delete
    retrieval.py            # tenant-scoped vector search + LLM call
  routers/
    onboarding.py          # POST /tenants
    ingestion.py            # POST/DELETE /documents
    query.py                 # POST /query
    usage.py                  # GET /usage
  main.py
streamlit_app.py         # UI: onboarding, ingest, query, usage dashboard
db_init.sql              # pgvector extension + RLS policies + indexes
docker-compose.yml
```
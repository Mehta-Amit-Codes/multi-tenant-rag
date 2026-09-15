-- Run once against the database after tables are created (e.g. via Alembic
-- or Base.metadata.create_all). This adds the belt-and-braces isolation
-- layer: even if application code forgets a tenant_id filter, Postgres
-- itself will refuse to return another tenant's rows.

CREATE EXTENSION IF NOT EXISTS vector;

-- Enable RLS on every tenant-scoped table
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_events ENABLE ROW LEVEL SECURITY;

-- The app sets `SET app.tenant_id = '<uuid>'` at the start of each request
-- (see core/db_session.py). These policies compare every row's tenant_id
-- against that session variable.
CREATE POLICY tenant_isolation_documents ON documents
    USING (tenant_id = current_setting('app.tenant_id')::uuid);

CREATE POLICY tenant_isolation_chunks ON chunks
    USING (tenant_id = current_setting('app.tenant_id')::uuid);

CREATE POLICY tenant_isolation_usage_events ON usage_events
    USING (tenant_id = current_setting('app.tenant_id')::uuid);

-- Speed up cosine similarity search per tenant. IVFFlat requires ANALYZE
-- after enough rows exist; HNSW (pgvector >= 0.5) needs no training step
-- and is preferred for production:
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS chunks_tenant_idx ON chunks (tenant_id);
CREATE INDEX IF NOT EXISTS documents_tenant_hash_idx ON documents (tenant_id, content_hash);

"""
Tenant-scoped retrieval. Note the explicit `Chunk.tenant_id == tenant.id`
filter below is deliberately redundant with RLS -- this is the
"defense-in-depth" point from the blueprint: app-level filtering AND
database-level RLS both have to be bypassed for a cross-tenant leak to
happen, not just one.
"""
import os
import time

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db import Chunk, Tenant
from app.services.embedding import embed_texts
from app.services.ingestion import _log_usage

# Grok (xAI) exposes an OpenAI-compatible API, so the official `openai`
# client works unmodified -- just point base_url at xAI and use a Grok
# model name.
GROK_BASE_URL = os.environ.get("GROK_BASE_URL", "https://api.x.ai/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "grok-4")


def retrieve_chunks(session: Session, tenant: Tenant, query: str, top_k: int = 5) -> list[Chunk]:
    [query_vector] = embed_texts([query], model_name=tenant.embedding_model)

    stmt = (
        select(Chunk)
        .where(Chunk.tenant_id == tenant.id)  # explicit filter, on top of RLS
        .order_by(Chunk.embedding.cosine_distance(query_vector))
        .limit(top_k)
    )
    return list(session.execute(stmt).scalars().all())


def answer_query(session: Session, tenant: Tenant, query: str, top_k: int = 5) -> dict:
    start = time.perf_counter()
    chunks = retrieve_chunks(session, tenant, query, top_k=top_k)

    context = "\n\n".join(f"[{c.chunk_index}] {c.text}" for c in chunks)
    prompt = (
        "Answer the question using ONLY the context below. "
        "Cite chunk indices in brackets. If the context doesn't contain "
        "the answer, say so.\n\n"
        f"Context:\n{context}\n\nQuestion: {query}"
    )

    answer_text, tokens_in, tokens_out = _call_llm(prompt)
    latency_ms = int((time.perf_counter() - start) * 1000)

    _log_usage(
        session, tenant.id, event_type="query",
        tokens_in=tokens_in, tokens_out=tokens_out, latency_ms=latency_ms,
    )

    return {
        "answer": answer_text,
        "sources": [{"chunk_index": c.chunk_index, "document_id": str(c.document_id),
                     "text": c.text} for c in chunks],
        "latency_ms": latency_ms,
    }


def _call_llm(prompt: str) -> tuple[str, int, int]:
    """Thin wrapper so the rest of the code doesn't depend on call sites
    knowing the provider. Reads GROK_API_KEY from the environment."""
    client = OpenAI(api_key=os.environ["GROK_API_KEY"], base_url=GROK_BASE_URL)
    response = client.chat.completions.create(
        model=LLM_MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.choices[0].message.content or ""
    return text, response.usage.prompt_tokens, response.usage.completion_tokens

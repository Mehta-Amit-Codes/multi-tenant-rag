"""
Incremental ingestion: a document is identified by a content hash. If a
tenant re-uploads byte-identical content, we skip re-embedding entirely
(idempotent). If the content changed, we version it, remove the old
document's chunks, and re-embed only the new content -- never a full
tenant-wide re-index.
"""
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.db import Chunk, Document, Tenant, TenantStorageUsage, UsageEvent
from app.services.embedding import chunk_text, embed_texts, sha256_of


class IngestResult:
    def __init__(self, status: str, document_id: str, chunks_embedded: int):
        self.status = status              # "unchanged" | "created" | "updated"
        self.document_id = document_id
        self.chunks_embedded = chunks_embedded


def ingest_document(session: Session, tenant: Tenant, filename: str, raw_text: str) -> IngestResult:
    content_hash = sha256_of(raw_text)

    existing = session.execute(
        select(Document).where(
            Document.tenant_id == tenant.id,
            Document.filename == filename,
        )
    ).scalar_one_or_none()

    if existing and existing.content_hash == content_hash:
        # Byte-identical re-upload: nothing to do. This is what makes
        # ingestion idempotent/safe to retry or re-run on a schedule.
        return IngestResult("unchanged", str(existing.id), 0)

    if existing:
        # Content changed: remove old chunks (cascade), bump version, keep same doc id.
        session.execute(delete(Chunk).where(Chunk.document_id == existing.id))
        existing.content_hash = content_hash
        existing.version += 1
        document = existing
        status = "updated"
    else:
        document = Document(tenant_id=tenant.id, filename=filename, content_hash=content_hash)
        session.add(document)
        session.flush()  # populate document.id before creating chunks
        status = "created"

    pieces = chunk_text(raw_text, chunk_size=tenant.chunk_size, overlap=tenant.chunk_overlap)
    if not pieces:
        session.flush()
        return IngestResult(status, str(document.id), 0)

    vectors = embed_texts(pieces, model_name=tenant.embedding_model)

    for idx, (piece, vector) in enumerate(zip(pieces, vectors)):
        session.add(Chunk(
            tenant_id=tenant.id,
            document_id=document.id,
            chunk_index=idx,
            text=piece,
            embedding=vector,
            chunk_hash=sha256_of(piece),
        ))

    _update_storage_counters(session, tenant.id)
    _log_usage(session, tenant.id, event_type="ingest", chunks_embedded=len(pieces))

    session.flush()
    return IngestResult(status, str(document.id), len(pieces))


def delete_document(session: Session, tenant: Tenant, document_id: UUID) -> None:
    """Deletes only this tenant's document + chunks (RLS backs this up too)."""
    session.execute(
        delete(Document).where(Document.id == document_id, Document.tenant_id == tenant.id)
    )
    _update_storage_counters(session, tenant.id)


def _update_storage_counters(session: Session, tenant_id) -> None:
    chunk_count = session.execute(
        select(Chunk.id).where(Chunk.tenant_id == tenant_id)
    ).rowcount or 0
    doc_count = session.execute(
        select(Document.id).where(Document.tenant_id == tenant_id)
    ).rowcount or 0

    usage = session.get(TenantStorageUsage, tenant_id)
    if usage is None:
        usage = TenantStorageUsage(tenant_id=tenant_id)
        session.add(usage)
    usage.chunk_count = chunk_count
    usage.document_count = doc_count


def _log_usage(session: Session, tenant_id, event_type: str, chunks_embedded: int = 0,
                tokens_in: int = 0, tokens_out: int = 0, latency_ms: int = 0) -> None:
    session.add(UsageEvent(
        tenant_id=tenant_id,
        event_type=event_type,
        chunks_embedded=chunks_embedded,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
    ))

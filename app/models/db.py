"""
SQLAlchemy models for the multi-tenant RAG service.

Isolation strategy: every table that holds tenant data carries a `tenant_id`
column, and Postgres Row-Level Security (RLS) policies (see db_init.sql)
enforce that a session can only ever see rows matching the `app.tenant_id`
session variable. This is defense-in-depth on top of always filtering by
tenant_id in application code -- if a developer ever forgets a WHERE clause,
RLS still blocks cross-tenant reads at the database layer.
"""
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column, String, DateTime, Integer, ForeignKey, UniqueConstraint, BigInteger
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

EMBEDDING_DIM = 384  # matches sentence-transformers/all-MiniLM-L6-v2


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    api_key_hash = Column(String, nullable=False, unique=True)
    embedding_model = Column(String, nullable=False, default="all-MiniLM-L6-v2")
    chunk_size = Column(Integer, nullable=False, default=500)
    chunk_overlap = Column(Integer, nullable=False, default=50)
    created_at = Column(DateTime, default=datetime.utcnow)

    documents = relationship("Document", back_populates="tenant", cascade="all, delete-orphan")
    usage_events = relationship("UsageEvent", back_populates="tenant", cascade="all, delete-orphan")


class Document(Base):
    """One uploaded source document. Tracked by content hash for idempotent re-ingestion."""
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("tenant_id", "content_hash", name="uq_tenant_doc_hash"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    filename = Column(String, nullable=False)
    content_hash = Column(String, nullable=False, index=True)  # sha256 of raw file bytes
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="documents")
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    """A single embedded chunk. tenant_id is duplicated here (denormalized) so
    every retrieval query can filter/RLS-check without a join."""
    __tablename__ = "chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    text = Column(String, nullable=False)
    embedding = Column(Vector(EMBEDDING_DIM), nullable=False)
    chunk_hash = Column(String, nullable=False)  # sha256 of this chunk's text
    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("Document", back_populates="chunks")


class UsageEvent(Base):
    """Append-only log of billable/measurable events per tenant."""
    __tablename__ = "usage_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    event_type = Column(String, nullable=False)  # "query" | "ingest"
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    chunks_embedded = Column(Integer, default=0)
    latency_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    tenant = relationship("Tenant", back_populates="usage_events")


class TenantStorageUsage(Base):
    """Rolling storage counter per tenant, updated on ingest/delete rather than
    computed with a full COUNT(*) on every /usage call."""
    __tablename__ = "tenant_storage_usage"

    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True)
    chunk_count = Column(BigInteger, nullable=False, default=0)
    document_count = Column(BigInteger, nullable=False, default=0)

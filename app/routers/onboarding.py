from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.auth import generate_api_key
from app.core.db_session import SessionLocal
from app.models.db import Tenant, TenantStorageUsage

router = APIRouter(prefix="/tenants", tags=["onboarding"])


class TenantCreateRequest(BaseModel):
    name: str = Field(..., examples=["Acme Corp"])
    embedding_model: str = "all-MiniLM-L6-v2"
    chunk_size: int = 500
    chunk_overlap: int = 50


class TenantCreateResponse(BaseModel):
    tenant_id: str
    api_key: str  # shown exactly once -- caller must store it


@router.post("", response_model=TenantCreateResponse, status_code=201)
def create_tenant(req: TenantCreateRequest) -> TenantCreateResponse:
    """
    Provisions a new tenant: creates its row, issues an API key, and
    initializes its storage counters. The plaintext API key is returned
    only in this response -- only its hash is persisted.
    """
    plaintext_key, key_hash = generate_api_key()

    with SessionLocal() as session:
        tenant = Tenant(
            name=req.name,
            api_key_hash=key_hash,
            embedding_model=req.embedding_model,
            chunk_size=req.chunk_size,
            chunk_overlap=req.chunk_overlap,
        )
        session.add(tenant)
        session.flush()
        session.add(TenantStorageUsage(tenant_id=tenant.id, chunk_count=0, document_count=0))
        session.commit()
        tenant_id = str(tenant.id)

    return TenantCreateResponse(tenant_id=tenant_id, api_key=plaintext_key)

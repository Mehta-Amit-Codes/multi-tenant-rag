from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.db_session import tenant_session
from app.core.rate_limit import rate_limited_tenant
from app.models.db import Tenant
from app.services.ingestion import delete_document, ingest_document

router = APIRouter(prefix="/documents", tags=["ingestion"])


class IngestRequest(BaseModel):
    filename: str
    text: str  # pre-extracted text; add a PDF/DOCX parsing step upstream if needed


class IngestResponse(BaseModel):
    status: str
    document_id: str
    chunks_embedded: int


@router.post("", response_model=IngestResponse)
def ingest(req: IngestRequest, tenant: Tenant = Depends(rate_limited_tenant)) -> IngestResponse:
    with tenant_session(tenant.id) as session:
        result = ingest_document(session, tenant, req.filename, req.text)
    return IngestResponse(
        status=result.status,
        document_id=result.document_id,
        chunks_embedded=result.chunks_embedded,
    )


@router.delete("/{document_id}", status_code=204)
def delete(document_id: UUID, tenant: Tenant = Depends(rate_limited_tenant)) -> None:
    with tenant_session(tenant.id) as session:
        delete_document(session, tenant, document_id)

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.db_session import tenant_session
from app.core.rate_limit import rate_limited_tenant
from app.models.db import Tenant
from app.services.retrieval import answer_query

router = APIRouter(prefix="/query", tags=["query"])


class QueryRequest(BaseModel):
    question: str
    top_k: int = 5


class Source(BaseModel):
    chunk_index: int
    document_id: str
    text: str


class QueryResponse(BaseModel):
    answer: str
    sources: list[Source]
    latency_ms: int


@router.post("", response_model=QueryResponse)
def query(req: QueryRequest, tenant: Tenant = Depends(rate_limited_tenant)) -> QueryResponse:
    with tenant_session(tenant.id) as session:
        result = answer_query(session, tenant, req.question, top_k=req.top_k)
    return QueryResponse(**result)

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.db_session import tenant_session
from app.core.rate_limit import rate_limited_tenant
from app.models.db import Tenant
from app.services.retrieval import answer_query, retrieve_chunks

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


class RetrieveRequest(BaseModel):
    question: str
    top_k: int = 5


class RetrieveResponse(BaseModel):
    sources: list[Source]


@router.post("/retrieve", response_model=RetrieveResponse)
def retrieve(req: RetrieveRequest, tenant: Tenant = Depends(rate_limited_tenant)) -> RetrieveResponse:
    """
    Retrieval only -- no LLM call. Used by external cost-control /
    orchestration layers (e.g. Project 2) that want tenant-isolated
    context without paying for Project 1's own generation on top of
    their own routed model call.
    """
    with tenant_session(tenant.id) as session:
        chunks = retrieve_chunks(session, tenant, req.question, top_k=req.top_k)
    return RetrieveResponse(sources=[
        Source(chunk_index=c.chunk_index, document_id=str(c.document_id), text=c.text)
        for c in chunks
    ])

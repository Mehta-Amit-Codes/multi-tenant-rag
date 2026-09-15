from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.auth import get_current_tenant
from app.core.db_session import tenant_session
from app.models.db import Tenant, TenantStorageUsage, UsageEvent

router = APIRouter(prefix="/usage", tags=["usage"])


class UsageResponse(BaseModel):
    tenant_id: str
    window_days: int
    total_queries: int
    total_ingests: int
    tokens_in: int
    tokens_out: int
    avg_query_latency_ms: float
    chunk_count: int
    document_count: int


@router.get("", response_model=UsageResponse)
def get_usage(window_days: int = 30, tenant: Tenant = Depends(get_current_tenant)) -> UsageResponse:
    since = datetime.utcnow() - timedelta(days=window_days)

    with tenant_session(tenant.id) as session:
        events = session.execute(
            select(UsageEvent).where(UsageEvent.created_at >= since)
        ).scalars().all()

        storage = session.get(TenantStorageUsage, tenant.id)

    total_queries = sum(1 for e in events if e.event_type == "query")
    total_ingests = sum(1 for e in events if e.event_type == "ingest")
    tokens_in = sum(e.tokens_in for e in events)
    tokens_out = sum(e.tokens_out for e in events)
    query_latencies = [e.latency_ms for e in events if e.event_type == "query"]
    avg_latency = sum(query_latencies) / len(query_latencies) if query_latencies else 0.0

    return UsageResponse(
        tenant_id=str(tenant.id),
        window_days=window_days,
        total_queries=total_queries,
        total_ingests=total_ingests,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        avg_query_latency_ms=round(avg_latency, 1),
        chunk_count=storage.chunk_count if storage else 0,
        document_count=storage.document_count if storage else 0,
    )

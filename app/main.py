from fastapi import FastAPI

from app.routers import ingestion, onboarding, query, usage

app = FastAPI(
    title="Multi-Tenant RAG-as-a-Service",
    description="RAG backend serving multiple isolated tenants from shared infrastructure.",
    version="0.1.0",
)

app.include_router(onboarding.router)
app.include_router(ingestion.router)
app.include_router(query.router)
app.include_router(usage.router)


@app.get("/health")
def health():
    return {"status": "ok"}

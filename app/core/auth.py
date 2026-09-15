"""
API-key auth scoped to a tenant. Keys are generated once at onboarding,
shown to the caller a single time, and stored only as a salted hash --
identical to how you'd handle passwords. Every authenticated request
resolves to exactly one tenant_id, which is then used for both RLS
(db_session.py) and rate limiting (rate_limit.py).
"""
import hashlib
import hmac
import os
import secrets

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select

from app.core.db_session import SessionLocal
from app.models.db import Tenant

API_KEY_PEPPER = os.environ.get("API_KEY_PEPPER", "dev-only-pepper-change-me")
API_KEY_PREFIX = "rag_live_"


def generate_api_key() -> tuple[str, str]:
    """Returns (plaintext_key_to_show_once, hash_to_store)."""
    raw = secrets.token_urlsafe(32)
    plaintext = f"{API_KEY_PREFIX}{raw}"
    key_hash = _hash_key(plaintext)
    return plaintext, key_hash


def _hash_key(plaintext: str) -> str:
    return hashlib.sha256((plaintext + API_KEY_PEPPER).encode()).hexdigest()


def verify_api_key(plaintext: str, stored_hash: str) -> bool:
    return hmac.compare_digest(_hash_key(plaintext), stored_hash)


def get_current_tenant(x_api_key: str = Header(..., alias="X-API-Key")) -> Tenant:
    """
    FastAPI dependency: resolves and returns the Tenant for the given API
    key, or raises 401. This runs on a plain (non-RLS-scoped) session
    because we don't know the tenant_id yet -- that's exactly what this
    lookup determines. The lookup table (tenants) itself is not
    tenant-scoped data, so this is safe.
    """
    key_hash = _hash_key(x_api_key)
    with SessionLocal() as session:
        tenant = session.execute(
            select(Tenant).where(Tenant.api_key_hash == key_hash)
        ).scalar_one_or_none()

    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return tenant

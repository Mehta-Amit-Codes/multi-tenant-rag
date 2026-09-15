"""
Provides a request-scoped DB session that is pinned to a single tenant via
Postgres RLS (SET app.tenant_id). This is the second half of the isolation
story from db_init.sql -- app-level filtering happens too, but this is what
makes a forgotten WHERE clause non-catastrophic.
"""
import os
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://rag:rag@localhost:5432/rag"
)

engine = create_engine(DATABASE_URL, pool_size=10, max_overflow=20)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@contextmanager
def tenant_session(tenant_id: str):
    """
    Yields a SQLAlchemy session scoped to one tenant. Every query run inside
    this context is restricted by Postgres RLS to rows matching tenant_id,
    regardless of whether application code also filters explicitly.
    """
    session: Session = SessionLocal()
    try:
        # set_config's third arg (is_local=True) scopes the setting to this
        # transaction only, so it can never leak to a pooled connection
        # reused by a different tenant's request.
        session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

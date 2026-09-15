"""Run once to create tables, before applying db_init.sql (RLS + indexes)."""
from app.core.db_session import engine
from app.models.db import Base

if __name__ == "__main__":
    Base.metadata.create_all(engine)
    print("Tables created. Now run: psql $DATABASE_URL -f db_init.sql")

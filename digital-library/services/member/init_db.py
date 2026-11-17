"""Explicit local schema initialization; never invoked on API startup."""

from sqlalchemy.engine import make_url

from app.database import configured_engine
from app.models import Base


if __name__ == "__main__":
    engine = configured_engine()
    if make_url(engine.url).host not in {"localhost", "127.0.0.1", "postgres"}:
        raise SystemExit("Initialization is restricted to local PostgreSQL hosts")
    try:
        Base.metadata.create_all(engine)
        print("Local members table initialized (existing tables preserved).")
    finally:
        engine.dispose()

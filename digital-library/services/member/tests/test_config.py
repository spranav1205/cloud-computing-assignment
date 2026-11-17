"""Check cloud TLS configuration without opening a database connection."""
import pytest

from app.database import configured_engine


def test_cloud_requires_verified_tls(monkeypatch):
    monkeypatch.setenv("APP_ENV", "aws")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://dummy:dummy@db.invalid/library")
    with pytest.raises(RuntimeError, match="verify-full"):
        configured_engine()


def test_verified_tls_configuration(monkeypatch):
    monkeypatch.setenv("APP_ENV", "aws")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://dummy:dummy@db.invalid/library?sslmode=verify-full&sslrootcert=/etc/rds-ca/global-bundle.pem")
    engine = configured_engine()
    assert engine.url.query["sslmode"] == "verify-full"
    engine.dispose()

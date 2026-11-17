"""Essential real-PostgreSQL checks; use a dedicated local member_test database."""

import os
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.engine import make_url

from app.main import create_app
from app.models import Base, Member

pytestmark = pytest.mark.integration


@pytest.fixture
def postgres_client():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL for local PostgreSQL integration tests")
    parsed = make_url(url)
    if parsed.host not in {"localhost", "127.0.0.1"} or parsed.database != "member_test":
        pytest.fail("Integration tests require local PostgreSQL database member_test")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(delete(Member))
    try:
        with TestClient(create_app(engine)) as client:
            yield client
    finally:
        with engine.begin() as connection:
            connection.execute(delete(Member))
        engine.dispose()


def test_postgres_persistence_and_unique_constraint(postgres_client):
    client = postgres_client
    first = client.post("/members", json={"name": "Ada", "email": "ada@example.com"})
    assert first.status_code == 201
    timestamp = datetime.fromisoformat(first.json()["created_at"].replace("Z", "+00:00"))
    assert timestamp.utcoffset() == timedelta(0)
    assert client.get(first.headers["location"]).json() == first.json()
    assert client.post("/members", json={"name": "Other", "email": "ADA@example.com"}).status_code == 409
    second = client.post("/members", json={"name": "Grace", "email": "grace@example.com"})
    assert second.status_code == 201
    assert client.patch(second.headers["location"], json={"email": "ada@example.com"}).status_code == 409
    assert client.get(second.headers["location"]).json()["email"] == "grace@example.com"
    assert len(client.get("/members").json()["items"]) == 2

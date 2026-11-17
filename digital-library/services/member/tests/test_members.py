"""HTTP tests use SQLite only as a lightweight test double, not PostgreSQL proof."""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool

from app import database
from app.main import create_app
from app.models import Base


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with TestClient(create_app(engine)) as test_client:
        yield test_client
    engine.dispose()


def test_member_workflow(client):
    created = client.post("/members", json={"name": " Ada ", "email": "ADA@example.com"})
    assert created.status_code == 201
    member = created.json()
    UUID(member["member_id"])
    assert member["name"] == "Ada"
    assert member["email"] == "ada@example.com"
    assert member["created_at"]
    location = created.headers["location"]
    assert client.get(location).json() == member
    patched = client.patch(location, json={"name": "Grace", "email": "grace@example.com"})
    assert patched.status_code == 200
    assert patched.json()["name"] == "Grace"
    assert patched.json()["created_at"] == member["created_at"]
    assert client.get(location).json()["email"] == "grace@example.com"


def test_limit_offset(client):
    for index in range(3):
        assert client.post("/members", json={"name": f"Member {index}", "email": f"m{index}@example.com"}).status_code == 201
    page = client.get("/members?limit=2&offset=1").json()
    assert page["limit"] == 2 and page["offset"] == 1
    assert [item["name"] for item in page["items"]] == ["Member 1", "Member 2"]
    assert client.get("/members?offset=99").json()["items"] == []


@pytest.mark.parametrize("body", [
    {}, {"name": " ", "email": "a@example.com"},
    {"name": "Ada", "email": "invalid"},
    {"name": "A" * 201, "email": "a@example.com"},
    {"name": "Ada", "email": "a@example.com", "member_id": str(uuid4())},
])
def test_invalid_create(client, body):
    assert client.post("/members", json=body).status_code == 422


@pytest.mark.parametrize("body", [{}, {"name": None}, {"email": None}, {"name": " "}, {"created_at": "now"}])
def test_invalid_patch(client, body):
    assert client.patch(f"/members/{uuid4()}", json=body).status_code == 422


def test_missing_and_invalid_ids(client):
    assert client.get(f"/members/{uuid4()}").status_code == 404
    assert client.patch(f"/members/{uuid4()}", json={"name": "Ada"}).status_code == 404
    assert client.get("/members/not-a-uuid").status_code == 422


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "offset=abc"])
def test_invalid_pagination(client, query):
    assert client.get(f"/members?{query}").status_code == 422


def test_health_docs_and_metrics(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").status_code == 200
    assert "/members/{member_id}" in client.get("/openapi.json").json()["paths"]
    client.get(f"/members/{uuid4()}")
    metrics = client.get("/metrics")
    assert "member_http_requests_total" in metrics.text
    assert 'route="/members/{member_id}"' in metrics.text
    assert "member_http_request_duration_seconds" in metrics.text


def test_database_failure(client, monkeypatch):
    def unavailable(*args):
        raise OperationalError("query", {}, Exception("private connection information"))

    monkeypatch.setattr(database, "list_members", unavailable)
    response = client.get("/members")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    assert client.get("/health").status_code == 200

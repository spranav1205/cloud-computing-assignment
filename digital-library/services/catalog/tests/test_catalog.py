"""Tests use real DynamoDB Local tables; unavailable dependencies fail, never skip."""
import json
from time import monotonic, sleep
from uuid import uuid4

import pytest
from botocore.exceptions import EndpointConnectionError
from fastapi.testclient import TestClient

from app.database import CatalogDatabase, initialize_tables, local_resource
from app.main import create_app


@pytest.fixture(scope="module")
def database():
    resource = local_resource()
    prefix = "test_" + uuid4().hex
    names = prefix + "_Books", prefix + "_Copies"
    initialize_tables(resource, *names)
    db = CatalogDatabase(resource, *names)
    yield db
    db.copies.delete()
    db.books.delete()
    resource.meta.client.close()


@pytest.fixture
def client(database):
    with TestClient(create_app(database)) as client:
        yield client


def test_book_copy_workflow(client):
    response = client.post("/books", json={"title": " Example ", "author": " Author ", "isbn": "978-0131103627"})
    assert response.status_code == 201
    book = response.json()
    assert book["title"] == "Example" and book["isbn"] == "9780131103627"
    assert book["created_at"]
    path = response.headers["location"]
    assert client.get(path).json() == book
    assert client.get(path + "/copies").json()["items"] == []
    created = [client.post(path + "/copies") for _ in range(3)]
    assert all(response.status_code == 201 for response in created)
    expected = {response.json()["copy_id"] for response in created}
    # GSI reads can lag behind writes, including on implementations beyond Local.
    deadline = monotonic() + 5
    while True:
        all_copies = client.get(path + "/copies").json()["items"]
        if len(all_copies) == 3 or monotonic() >= deadline:
            break
        sleep(0.05)
    assert {item["copy_id"] for item in all_copies} == expected
    first = client.get(path + "/copies", params={"limit": 1}).json()
    assert len(first["items"]) == 1
    key = first["last_evaluated_key"]
    assert key is not None
    second = client.get(path + "/copies", params={"last_evaluated_key": json.dumps(key)}).json()
    assert {item["copy_id"] for item in first["items"] + second["items"]} == expected


def test_book_pagination(client):
    for index in range(3):
        assert client.post("/books", json={"title": f"Book {index}", "author": "Author"}).status_code == 201
    found = []
    key = None
    for _ in range(10):
        params = {"limit": 1}
        if key:
            params["last_evaluated_key"] = json.dumps(key)
        page = client.get("/books", params=params)
        assert page.status_code == 200
        found.extend(item["book_id"] for item in page.json()["items"])
        key = page.json()["last_evaluated_key"]
        if key is None:
            break
    assert key is None
    assert len(found) >= 3 and len(found) == len(set(found))


@pytest.mark.parametrize("body", [{}, {"title": " ", "author": "A"},
    {"title": "T", "author": "A", "isbn": "bad"},
    {"title": "T", "author": "A", "available": True},
    {"title": "T", "author": "A", "title_extra": "unknown"}])
def test_validation(client, body):
    assert client.post("/books", json=body).status_code == 422


def test_missing_records(client):
    path = f"/books/{uuid4()}"
    assert client.get(path).status_code == 404
    assert client.get(path + "/copies").status_code == 404
    assert client.post(path + "/copies").status_code == 404
    assert client.get("/books/not-a-uuid").status_code == 422


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"last_evaluated_key": "bad"},
    {"last_evaluated_key": "{}"}])
def test_bad_pagination(client, params):
    assert client.get("/books", params=params).status_code == 422


def test_cross_book_key(client):
    book = str(uuid4())
    key = {"book_id": str(uuid4()), "copy_id": str(uuid4())}
    assert client.get(f"/books/{book}/copies", params={"last_evaluated_key": json.dumps(key)}).status_code == 422


def test_health_docs_metrics(client):
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    assert "/books/{book_id}/copies" in client.get("/openapi.json").json()["paths"]
    assert "catalog_http_requests_total" in client.get("/metrics").text


def test_database_failure(client, database, monkeypatch):
    def failed():
        raise EndpointConnectionError(endpoint_url="http://127.0.0.1:8000")
    monkeypatch.setattr(database, "ready", failed)
    assert client.get("/ready").status_code == 503
    assert client.get("/health").status_code == 200


def test_aws_endpoint_refused(monkeypatch):
    monkeypatch.setenv("DYNAMODB_ENDPOINT_URL", "https://dynamodb.us-east-1.amazonaws.com")
    with pytest.raises(ValueError, match="Only local"):
        local_resource()

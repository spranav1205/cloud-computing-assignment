"""Actual presigned HTTP uploads/downloads using private MinIO and DynamoDB Local."""
import base64
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from app.covers import MAX_COVER_BYTES, local_s3

# A tiny PNG fixture, not an image-processing dependency.
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1sAAAAASUVORK5CYII=")


@pytest.fixture
def book_path(client):
    response = client.post("/books", json={"title": "Cover test", "author": "Author"})
    assert response.status_code == 201
    return response.headers["location"]


def request_upload(client, path, content_type="image/png"):
    response = client.post(path + "/cover/upload-url", json={"content_type": content_type})
    assert response.status_code == 200
    return response.json()


def test_private_cover_workflow(client, database, book_path):
    assert client.get(book_path + "/cover-url").status_code == 404
    upload = request_upload(client, book_path)
    assert upload["method"] == "PUT" and upload["expires_in"] == 300
    assert parse_qs(urlsplit(upload["upload_url"]).query)["X-Amz-Expires"] == ["300"]
    book_id = book_path.split("/")[-1]
    key = database.get_book(book_id)["pending_cover_key"]
    assert key.startswith(f"covers/{book_id}/")
    assert "pending_cover_key" not in client.get(book_path).json()
    with httpx.Client(trust_env=False) as http:
        assert http.put(upload["upload_url"], content=PNG, headers=upload["headers"]).status_code == 200
        assert http.get(upload["upload_url"].split("?")[0]).status_code == 403
        confirmation = client.post(book_path + "/cover/confirm")
        assert confirmation.status_code == 200
        assert confirmation.json()["cover_key"] == key
        assert "pending_cover_key" not in database.get_book(book_id)
        download = client.get(book_path + "/cover-url").json()
        image = http.get(download["url"])
        assert image.status_code == 200 and image.content == PNG
        assert image.headers["content-type"] == "image/png"
    assert client.post(book_path + "/cover/confirm").status_code == 409


@pytest.mark.parametrize("content_type", ["image/gif", "text/plain"])
def test_unsupported_upload_type(client, book_path, content_type):
    assert client.post(book_path + "/cover/upload-url", json={"content_type": content_type}).status_code == 422


def test_missing_upload(client, book_path):
    assert client.post(book_path + "/cover/confirm").status_code == 409
    request_upload(client, book_path)
    assert client.post(book_path + "/cover/confirm").status_code == 404
    assert client.get(book_path + "/cover-url").status_code == 404


@pytest.mark.parametrize("size", [0, MAX_COVER_BYTES + 1])
def test_invalid_size(client, book_path, size):
    upload = request_upload(client, book_path)
    with httpx.Client(trust_env=False, timeout=15) as http:
        assert http.put(upload["upload_url"], headers=upload["headers"], content=b"x" * size).status_code == 200
    assert client.post(book_path + "/cover/confirm").status_code == 422
    assert client.get(book_path + "/cover-url").status_code == 404


def test_invalid_declared_object_type(client, database, book_path):
    request_upload(client, book_path)
    key = database.get_book(book_path.split("/")[-1])["pending_cover_key"]
    s3 = local_s3()
    try:
        s3.put_object(Bucket="library-covers", Key=key, Body=b"invalid", ContentType="text/plain")
    finally:
        s3.close()
    assert client.post(book_path + "/cover/confirm").status_code == 422


def test_no_client_controlled_keys(client, book_path):
    body = {"content_type": "image/png", "key": "covers/another-book/image.png"}
    assert client.post(book_path + "/cover/upload-url", json=body).status_code == 422
    assert client.post(book_path + "/cover/confirm", json={"upload_key": "anything"}).status_code == 422


def test_missing_book(client):
    path = f"/books/{uuid4()}"
    assert client.post(path + "/cover/upload-url", json={"content_type": "image/jpeg"}).status_code == 404
    assert client.post(path + "/cover/confirm").status_code == 404
    assert client.get(path + "/cover-url").status_code == 404


def test_scoped_storage_permissions():
    s3 = local_s3()
    try:
        with pytest.raises(ClientError) as error:
            s3.put_object(Bucket="library-covers", Key="outside-covers/test", Body=b"data")
        assert error.value.response["Error"]["Code"] == "AccessDenied"
    finally:
        s3.close()


def test_minio_failure_readiness(client, monkeypatch):
    def failed():
        raise EndpointConnectionError(endpoint_url="http://127.0.0.1:9000")
    monkeypatch.setattr(client.app.state.covers, "ready", failed)
    assert client.get("/ready").status_code == 503
    assert client.get("/health").status_code == 200


def test_refuse_real_s3(monkeypatch):
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://s3.amazonaws.com")
    with pytest.raises(ValueError, match="Only local"):
        local_s3()

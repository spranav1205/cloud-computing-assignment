"""Shared real-local-storage fixtures; missing emulators fail instead of skip."""
from uuid import uuid4

import pytest
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

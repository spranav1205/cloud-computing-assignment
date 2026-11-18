import json
from urllib.parse import unquote
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.catalog import CatalogBookNotFound, CatalogClient, CatalogUnavailable
from app.database import AvailabilityStore
from app.main import create_app
from app.models import Base, LoanRecord, ReservationRecord


class FakeCatalog:
    def __init__(self, copy_ids):
        self.copy_ids = copy_ids
        self.error = None

    def list_copy_ids(self, book_id):
        if self.error:
            raise self.error
        return self.copy_ids

    def ready(self):
        if self.error:
            raise self.error

    def close(self):
        return None


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'availability.db'}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_availability_deducts_loans_and_holds_but_not_waitlist(database):
    book_id = uuid4()
    copies = {uuid4(), uuid4(), uuid4(), uuid4()}
    loaned_copy = next(iter(copies))
    checked_out_reservation = uuid4()
    ready_copy = next(copy_id for copy_id in copies if copy_id != loaned_copy)
    catalog = FakeCatalog(copies)
    with Session(database) as session:
        session.add(
            LoanRecord(
                loan_id=uuid4(),
                book_id=book_id,
                copy_id=loaned_copy,
                reservation_id=checked_out_reservation,
                returned_at=None,
            )
        )
        session.add_all(
            [
                ReservationRecord(
                    reservation_id=checked_out_reservation,
                    book_id=book_id,
                    status="READY",
                    copy_id=None,
                ),
                ReservationRecord(
                    reservation_id=uuid4(),
                    book_id=book_id,
                    status="READY",
                    copy_id=ready_copy,
                ),
                ReservationRecord(
                    reservation_id=uuid4(),
                    book_id=book_id,
                    status="READY",
                    copy_id=None,
                ),
                ReservationRecord(
                    reservation_id=uuid4(),
                    book_id=book_id,
                    status="WAITLISTED",
                    copy_id=None,
                ),
            ]
        )
        session.commit()

    with TestClient(create_app(store=AvailabilityStore(database, catalog))) as client:
        response = client.get(f"/books/{book_id}/availability")

    assert response.status_code == 200
    payload = response.json()
    assert payload["book_id"] == str(book_id)
    assert payload["total_copies"] == 4
    assert payload["loaned_copies"] == 1
    assert payload["reserved_copies"] == 2
    assert payload["available_copies"] == 1
    assert len(payload["available_copy_ids"]) == 1
    assert payload["available_copy_ids"][0] not in {str(loaned_copy), str(ready_copy)}


@pytest.mark.parametrize(
    ("error", "status"),
    [(CatalogBookNotFound(), 404), (CatalogUnavailable("down"), 503)],
)
def test_catalog_errors_are_reported(database, error, status):
    catalog = FakeCatalog(set())
    catalog.error = error
    with TestClient(create_app(store=AvailabilityStore(database, catalog))) as client:
        response = client.get(f"/books/{uuid4()}/availability")
    assert response.status_code == status


def test_health_readiness_and_metrics(database):
    catalog = FakeCatalog(set())
    with TestClient(create_app(store=AvailabilityStore(database, catalog))) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200
        assert "availability_http_requests_total" in client.get("/metrics").text


def test_catalog_client_follows_copy_pagination():
    book_id = uuid4()
    first_copy_id, second_copy_id = uuid4(), uuid4()
    pages = []

    def handle(request):
        key = request.url.params.get("last_evaluated_key")
        pages.append(key)
        if key is None:
            return httpx.Response(
                200,
                json={
                    "items": [{"copy_id": str(first_copy_id)}],
                    "last_evaluated_key": {"book_id": str(book_id), "copy_id": str(uuid4())},
                },
            )
        continuation_key = json.loads(unquote(key))
        assert continuation_key["book_id"] == str(book_id)
        return httpx.Response(
            200,
            json={
                "items": [{"copy_id": str(second_copy_id)}],
                "last_evaluated_key": None,
            },
        )

    client = CatalogClient("http://catalog", httpx.Client(transport=httpx.MockTransport(handle)))
    try:
        result = client.list_copy_ids(book_id)
    finally:
        client.close()

    assert result == {first_copy_id, second_copy_id}
    assert len(pages) == 2

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote
from uuid import uuid4
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.clients import CheckoutConflict, LendingDependencies
from app.database import LendingStore
from app.main import create_app
from app.models import Base, LoanCreate
from app.notifications import LoanNotifications, notification_id


class FakeDependencies:
    def __init__(self):
        self.book_id = uuid4()
        self.cancelled = []
        self.checkout_error = None

    def validate_checkout(self, data):
        if self.checkout_error:
            raise self.checkout_error
        return self.book_id

    def cancel_reservation(self, reservation_id):
        self.cancelled.append(reservation_id)

    def ready(self):
        return None

    def close(self):
        return None


@pytest.fixture
def api(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'lending.db'}")
    Base.metadata.create_all(engine)
    dependencies = FakeDependencies()
    with TestClient(
        create_app(
            store=LendingStore(engine),
            dependencies=dependencies,
            loan_period_days=7,
            notifications=Mock(),
        )
    ) as client:
        yield client, engine, dependencies
    engine.dispose()


def create_loan(api, reservation_id=None, copy_id=None):
    client, _, dependencies = api
    payload = {
        "member_id": str(uuid4()),
        "reservation_id": str(reservation_id or uuid4()),
        "copy_id": str(copy_id or uuid4()),
    }
    return client.post("/loans", json=payload), payload, dependencies.book_id


def test_checkout_records_due_date_and_status(api):
    client, _, _ = api
    response, payload, expected_book_id = create_loan(api)

    assert response.status_code == 201
    loan = response.json()
    assert loan["book_id"] == str(expected_book_id)
    assert loan["member_id"] == payload["member_id"]
    assert loan["reservation_id"] == payload["reservation_id"]
    assert loan["status"] == "ACTIVE"
    checked_out_at = datetime.fromisoformat(loan["checked_out_at"].replace("Z", "+00:00"))
    due_at = datetime.fromisoformat(loan["due_at"].replace("Z", "+00:00"))
    assert due_at - checked_out_at == timedelta(days=7)
    assert client.get(f"/loans/{loan['loan_id']}").json() == loan


def test_same_copy_cannot_have_two_active_loans(api):
    client, _, _ = api
    copy_id = uuid4()
    assert create_loan(api, copy_id=copy_id)[0].status_code == 201

    duplicate, _, _ = create_loan(api, copy_id=copy_id)

    assert duplicate.status_code == 409


def test_return_is_idempotent_and_cancels_the_ready_reservation(api):
    client, _, dependencies = api
    response, payload, _ = create_loan(api)
    loan_id = response.json()["loan_id"]

    first = client.post(f"/loans/{loan_id}/return")
    second = client.post(f"/loans/{loan_id}/return")

    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == second.json()["status"] == "RETURNED"
    assert first.json()["returned_at"] == second.json()["returned_at"]
    assert [str(reservation_id) for reservation_id in dependencies.cancelled] == [
        payload["reservation_id"],
        payload["reservation_id"],
    ]
    assert [call.args[1] for call in client.app.state.notifications.publish.call_args_list] == ["LoanIssued", "LoanReturned"]


def test_concurrent_returns_emit_one_event_and_preserve_timestamp(api):
    client, _, _ = api
    response, _, _ = create_loan(api)
    path = f"/loans/{response.json()['loan_id']}/return"
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: client.post(path), range(4)))
    assert all(response.status_code == 200 for response in responses)
    assert len({response.json()["returned_at"] for response in responses}) == 1
    assert [call.args[1] for call in client.app.state.notifications.publish.call_args_list] == ["LoanIssued", "LoanReturned"]


@pytest.mark.parametrize("failure", ["member", "notification"])
def test_notification_failure_does_not_fail_committed_loans(api, caplog, failure):
    client, _, _ = api

    def handle(request):
        if request.url.host == "member" and failure != "member":
            return httpx.Response(200, json={"email": "stored@example.com"})
        return httpx.Response(503)

    notifications = LoanNotifications("http://member", "http://notification", httpx.Client(transport=httpx.MockTransport(handle)))
    client.app.state.notifications = notifications
    try:
        issued, _, _ = create_loan(api)
        assert issued.status_code == 201
        loan_id = issued.json()["loan_id"]
        returned = client.post(f"/loans/{loan_id}/return")
        assert returned.status_code == 200
        assert client.get(f"/loans/{loan_id}").json()["status"] == "RETURNED"
        assert caplog.text.count("notification_publish_failed") == 2
    finally:
        notifications.close()


def test_notifications_use_member_email_stable_ids_and_transition_times(api):
    client, _, _ = api
    events = []

    def handle(request):
        if request.method == "GET":
            return httpx.Response(200, json={"email": "stored@example.com"})
        event = json.loads(request.content)
        events.append(event)
        return httpx.Response(202, json={"notification_id": event["event_id"], "status": "QUEUED"})

    notifications = LoanNotifications("http://member", "http://notification", httpx.Client(transport=httpx.MockTransport(handle)))
    client.app.state.notifications = notifications
    try:
        issued, payload, _ = create_loan(api)
        loan = issued.json()
        assert issued.status_code == 201
        assert client.post("/loans", json=payload).status_code == 409
        returned = client.post(f"/loans/{loan['loan_id']}/return").json()
        assert client.post(f"/loans/{loan['loan_id']}/return").status_code == 200
        assert client.post(f"/loans/{uuid4()}/return").status_code == 404
        assert [event["event_type"] for event in events] == ["LoanIssued", "LoanReturned"]
        for event, timestamp in zip(events, [loan["checked_out_at"], returned["returned_at"]]):
            assert event["recipient"] == "stored@example.com"
            assert event["member_id"] == payload["member_id"]
            assert event["event_id"] == str(notification_id(loan["loan_id"], event["event_type"]))
            expected = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if expected.tzinfo is None:  # SQLite omits the timezone on persisted dates.
                expected = expected.replace(tzinfo=timezone.utc)
            assert datetime.fromisoformat(event["occurred_at"]) == expected
        assert events[0]["event_id"] != events[1]["event_id"]
    finally:
        notifications.close()


def test_not_ready_reservation_rejects_checkout(api):
    client, _, dependencies = api
    dependencies.checkout_error = CheckoutConflict("Reservation is not ready for checkout")

    response, _, _ = create_loan(api)

    assert response.status_code == 409
    assert client.get("/loans", params={"active_only": "true"}).json()["total"] == 0


def test_missing_loan_and_list_filters(api):
    client, _, _ = api
    assert client.get(f"/loans/{uuid4()}").status_code == 404
    created, _, _ = create_loan(api)
    assert client.get("/loans", params={"book_id": created.json()["book_id"]}).json()["total"] == 1
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    assert "lending_http_requests_total" in client.get("/metrics").text


def test_checkout_validation_follows_catalog_pagination():
    book_id = uuid4()
    copy_id = uuid4()
    member_id = uuid4()
    reservation_id = uuid4()
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.path == f"/reservations/{reservation_id}":
            return httpx.Response(
                200,
                json={
                    "reservation_id": str(reservation_id),
                    "book_id": str(book_id),
                    "member_id": str(member_id),
                    "status": "READY",
                    "copy_id": str(copy_id),
                },
            )
        if request.url.path == f"/members/{member_id}":
            return httpx.Response(200, json={"member_id": str(member_id)})
        if request.url.path == f"/books/{book_id}/copies":
            key = request.url.params.get("last_evaluated_key")
            if key is None:
                return httpx.Response(
                    200,
                    json={
                        "items": [],
                        "last_evaluated_key": {"book_id": str(book_id), "copy_id": str(uuid4())},
                    },
                )
            continuation_key = json.loads(unquote(key))
            assert continuation_key["book_id"] == str(book_id)
            return httpx.Response(
                200,
                json={"items": [{"copy_id": str(copy_id)}], "last_evaluated_key": None},
            )
        return httpx.Response(404)

    dependencies = LendingDependencies(
        "http://member",
        "http://catalog",
        "http://reservation",
        httpx.Client(transport=httpx.MockTransport(handle)),
    )
    try:
        result = dependencies.validate_checkout(
            LoanCreate(member_id=member_id, reservation_id=reservation_id, copy_id=copy_id)
        )
    finally:
        dependencies.close()

    assert result == book_id
    assert sum(request.url.path == f"/books/{book_id}/copies" for request in requests) == 2

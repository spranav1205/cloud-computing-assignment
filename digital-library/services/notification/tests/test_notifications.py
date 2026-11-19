from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from app.main import create_app
from app.models import NotificationEvent
from app.queue import InMemoryQueue, SqsQueue


def test_metrics_track_success_validation_and_queue_failure():
    queue = Mock()
    queue.publish.side_effect = RuntimeError("Queue unavailable")
    with TestClient(create_app(queue), raise_server_exceptions=False) as api:
        assert api.get("/health").status_code == 200
        assert api.post("/notifications", json={}).status_code == 422
        assert api.post("/notifications", json={
            "event_type": "LoanReturned",
            "recipient": "member@example.com",
            "subject": "Returned",
            "body": "Returned",
            "member_id": str(uuid4()),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }).status_code == 500
        response = api.get("/metrics")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain; version=0.0.4")
        samples = [s for f in text_string_to_metric_families(response.text) for s in f.samples]
        for method, route, status in [("GET", "/health", "200"), ("POST", "/notifications", "422"), ("POST", "/notifications", "500")]:
            assert any(s.name == "notification_http_requests_total" and s.labels == {
                "method": method, "route": route, "status": status,
            } and s.value == 1 for s in samples)
        assert any(s.name == "notification_http_request_duration_seconds_count" and s.labels == {
            "method": "POST", "route": "/notifications",
        } and s.value == 2 for s in samples)

    # Multiple app instances must not share counters or duplicate collectors.
    with TestClient(create_app(InMemoryQueue())) as api:
        assert 'route="/notifications"' not in api.get("/metrics").text


def test_notification_is_queued():
    queue = InMemoryQueue()
    with TestClient(create_app(queue)) as api:
        response = api.post(
            "/notifications",
            json={
                "event_type": "ReservationReady",
                "recipient": "member@example.com",
                "subject": "Reservation ready",
                "body": "Your reservation is ready",
                "member_id": str(uuid4()),
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        assert response.status_code == 202
        assert response.json()["status"] == "QUEUED"
        assert len(queue.events) == 1


def test_sqs_envelope_can_be_delivered_by_lambda(monkeypatch):
    """Exercise the producer and actual consumer together without contacting AWS."""
    queue = SqsQueue.__new__(SqsQueue)
    queue.client = Mock()
    queue.queue_url = "https://sqs.ap-south-1.amazonaws.com/111111111111/test"
    event = NotificationEvent(
        event_type="LoanIssued",
        event_id=uuid4(),
        recipient="member@example.com",
        subject="Reservation ready",
        body="Your reservation is ready",
        member_id=uuid4(),
        occurred_at=datetime.now(timezone.utc),
    )
    notification_id = queue.publish(event)
    assert notification_id == event.event_id
    message = queue.client.send_message.call_args.kwargs["MessageBody"]
    assert json.loads(message)["notification_id"] == str(notification_id)

    path = Path(__file__).resolve().parents[2] / "notification-lambda" / "handler.py"
    spec = importlib.util.spec_from_file_location("notification_lambda_handler", path)
    handler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handler)
    ses, dedupe = Mock(), Mock()
    monkeypatch.setattr(handler, "_clients", lambda: (ses, dedupe))
    monkeypatch.setenv("SES_SENDER", "sender@example.com")

    result = handler.lambda_handler({"Records": [{"messageId": "message-1", "body": message}]}, None)

    assert result == {"batchItemFailures": []}
    sent = ses.send_email.call_args.kwargs
    assert sent["Destination"] == {"ToAddresses": [str(event.recipient)]}
    assert sent["Message"]["Subject"]["Data"] == event.subject
    assert sent["Message"]["Body"]["Text"]["Data"] == event.body

    duplicate_error = type("ConditionalCheckFailedException", (Exception,), {})
    dedupe.meta.client.exceptions.ConditionalCheckFailedException = duplicate_error
    dedupe.put_item.side_effect = duplicate_error()
    assert handler.lambda_handler({"Records": [{"messageId": "retry", "body": message}]}, None) == {"batchItemFailures": []}
    assert ses.send_email.call_count == 1


def test_intake_preserves_explicit_event_id_and_accepts_loan_issued():
    queue = InMemoryQueue()
    event_id = uuid4()
    with TestClient(create_app(queue)) as api:
        event = {"event_id": str(event_id), "event_type": "LoanIssued", "recipient": "member@example.com", "body": "Loan issued", "member_id": str(uuid4()), "occurred_at": datetime.now(timezone.utc).isoformat()}
        for _ in range(2):
            response = api.post("/notifications", json=event)
            assert response.status_code == 202
            assert response.json()["notification_id"] == str(event_id)
    assert [item[0] for item in queue.events] == [event_id, event_id]

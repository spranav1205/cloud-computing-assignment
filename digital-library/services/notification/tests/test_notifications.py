from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import create_app
from app.models import NotificationEvent
from app.queue import InMemoryQueue, SqsQueue


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
        event_type="ReservationReady",
        recipient="member@example.com",
        subject="Reservation ready",
        body="Your reservation is ready",
        member_id=uuid4(),
        occurred_at=datetime.now(timezone.utc),
    )
    notification_id = queue.publish(event)
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

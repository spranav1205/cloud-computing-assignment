from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import create_app
from app.queue import InMemoryQueue


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

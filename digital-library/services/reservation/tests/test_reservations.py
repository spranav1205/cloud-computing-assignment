from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.database import ReservationStore, initialize_database
from app.main import create_app


def client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'reservation.db'}")
    initialize_database(engine)
    return TestClient(create_app(ReservationStore(engine)))


def test_fifo_promotion_after_ready_cancellation(tmp_path):
    with client(tmp_path) as api:
        book_id, first_member, second_member = uuid4(), uuid4(), uuid4()
        first = api.post("/reservations", json={"book_id": str(book_id), "member_id": str(first_member)})
        second = api.post("/reservations", json={"book_id": str(book_id), "member_id": str(second_member)})

        assert first.status_code == 201
        assert first.json()["status"] == "READY"
        assert second.json()["status"] == "WAITLISTED"

        cancelled = api.delete(f"/reservations/{first.json()['reservation_id']}")
        promoted = api.get(f"/reservations/{second.json()['reservation_id']}")
        assert cancelled.status_code == 200
        assert promoted.json()["status"] == "READY"


def test_duplicate_active_reservation_is_rejected(tmp_path):
    with client(tmp_path) as api:
        payload = {"book_id": str(uuid4()), "member_id": str(uuid4())}
        assert api.post("/reservations", json=payload).status_code == 201
        assert api.post("/reservations", json=payload).status_code == 409

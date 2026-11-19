from uuid import uuid4

from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families
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


def test_metrics_track_conflicts_and_use_route_templates(tmp_path):
    with client(tmp_path) as api:
        payload = {"book_id": str(uuid4()), "member_id": str(uuid4())}
        assert api.post("/reservations", json=payload).status_code == 201
        assert api.post("/reservations", json=payload).status_code == 409
        for _ in range(2):
            assert api.get(f"/reservations/{uuid4()}").status_code == 404
        assert api.get("/reservations/not-a-uuid").status_code == 422
        response = api.get("/metrics")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain; version=0.0.4")
        samples = [s for f in text_string_to_metric_families(response.text) for s in f.samples]
        for method, route, status, count in [
            ("POST", "/reservations", "201", 1),
            ("POST", "/reservations", "409", 1),
            ("GET", "/reservations/{reservation_id}", "404", 2),
            ("GET", "/reservations/{reservation_id}", "422", 1),
        ]:
            assert any(s.name == "reservation_http_requests_total" and s.labels == {
                "method": method, "route": route, "status": status,
            } and s.value == count for s in samples)
        assert any(s.name == "reservation_http_request_duration_seconds_count" and s.labels == {
            "method": "GET", "route": "/reservations/{reservation_id}",
        } and s.value == 3 for s in samples)

    with client(tmp_path) as api:
        assert 'route="/reservations"' not in api.get("/metrics").text


def test_member_can_list_reservations_from_backend(tmp_path):
    with client(tmp_path) as api:
        member_id = uuid4()
        book_id = uuid4()
        api.post("/reservations", json={"book_id": str(book_id), "member_id": str(member_id)})

        response = api.get("/reservations", params={"member_id": str(member_id)})

        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["member_id"] == str(member_id)


class FakeDependencies:
    def __init__(self, copy_id):
        self.copy_id = copy_id

    def validate(self, data):
        return self.copy_id

    def ready(self):
        return None


def test_dependency_allocates_copy_for_ready_reservation(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'reservation.db'}")
    initialize_database(engine)
    copy_id = uuid4()
    with TestClient(create_app(ReservationStore(engine), dependencies=FakeDependencies(copy_id))) as api:
        response = api.post("/reservations", json={"book_id": str(uuid4()), "member_id": str(uuid4())})

    assert response.status_code == 201
    assert response.json()["status"] == "READY"
    assert response.json()["copy_id"] == str(copy_id)

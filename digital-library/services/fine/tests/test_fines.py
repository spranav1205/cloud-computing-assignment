from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.fines import assess_fine
from app.main import create_app
from app.models import Base, Loan


@pytest.fixture
def api(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'loans.db'}")
    Base.metadata.create_all(engine)
    with TestClient(create_app(engine=engine, daily_fine_cents=125)) as client:
        yield client, engine
    engine.dispose()


def test_fine_uses_return_time_and_charges_partial_days_as_full_days(api):
    client, engine = api
    loan_id = uuid4()
    due_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    returned_at = due_at + timedelta(days=2, seconds=1)
    with engine.begin() as connection:
        connection.execute(
            Loan.__table__.insert().values(
                loan_id=loan_id,
                due_at=due_at,
                returned_at=returned_at,
            )
        )

    response = client.get(f"/loans/{loan_id}/fine")

    assert response.status_code == 200
    assert response.json()["overdue_days"] == 3
    assert response.json()["daily_fine_cents"] == 125
    assert response.json()["fine_amount_cents"] == 375
    assessed_at = datetime.fromisoformat(response.json()["assessed_at"].replace("Z", "+00:00"))
    assert assessed_at == returned_at


def test_fine_is_zero_when_returned_by_due_time(api):
    client, engine = api
    loan_id = uuid4()
    due_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            Loan.__table__.insert().values(
                loan_id=loan_id,
                due_at=due_at,
                returned_at=due_at,
            )
        )

    response = client.get(f"/loans/{loan_id}/fine")

    assert response.status_code == 200
    assert response.json()["overdue_days"] == 0
    assert response.json()["fine_amount_cents"] == 0


def test_missing_loan_and_invalid_id(api):
    client, _ = api
    assert client.get(f"/loans/{uuid4()}/fine").status_code == 404
    assert client.get("/loans/not-a-uuid/fine").status_code == 422


def test_health_readiness_and_metrics(api):
    client, _ = api
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}
    assert "fine_http_requests_total" in client.get("/metrics").text


def test_unreturned_loan_is_assessed_as_of_now():
    due_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
    loan = Loan(loan_id=uuid4(), due_at=due_at, returned_at=None)
    as_of = due_at + timedelta(days=1, seconds=1)

    result = assess_fine(loan, daily_fine_cents=100, as_of=as_of)

    assert result.overdue_days == 2
    assert result.fine_amount_cents == 200

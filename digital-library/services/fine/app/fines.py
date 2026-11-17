"""Fine calculation policy."""

from datetime import datetime, timezone
from math import ceil

from app.models import FineResponse, Loan

SECONDS_PER_DAY = 24 * 60 * 60


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def assess_fine(
    loan: Loan,
    daily_fine_cents: int,
    as_of: datetime | None = None,
) -> FineResponse:
    assessed_at = as_utc(loan.returned_at or as_of or datetime.now(timezone.utc))
    due_at = as_utc(loan.due_at)
    overdue_seconds = max(0, (assessed_at - due_at).total_seconds())
    overdue_days = ceil(overdue_seconds / SECONDS_PER_DAY)
    return FineResponse(
        loan_id=loan.loan_id,
        due_at=due_at,
        returned_at=as_utc(loan.returned_at) if loan.returned_at else None,
        assessed_at=assessed_at,
        overdue_days=overdue_days,
        daily_fine_cents=daily_fine_cents,
        fine_amount_cents=overdue_days * daily_fine_cents,
    )

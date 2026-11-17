"""Read-only view of the lending service's loan records."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import DateTime, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Loan(Base):
    __tablename__ = "loans"

    loan_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FineResponse(BaseModel):
    loan_id: UUID
    due_at: datetime
    returned_at: datetime | None
    assessed_at: datetime
    overdue_days: int
    daily_fine_cents: int
    fine_amount_cents: int

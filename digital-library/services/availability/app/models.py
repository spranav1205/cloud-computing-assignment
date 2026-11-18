"""Availability read model and HTTP response contract."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import DateTime, String, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LoanRecord(Base):
    __tablename__ = "loans"

    loan_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    book_id: Mapped[UUID] = mapped_column(Uuid)
    copy_id: Mapped[UUID] = mapped_column(Uuid)
    reservation_id: Mapped[UUID] = mapped_column(Uuid)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReservationRecord(Base):
    __tablename__ = "reservations"

    reservation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    book_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String)
    copy_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)


class AvailabilityResponse(BaseModel):
    book_id: UUID
    total_copies: int
    loaned_copies: int
    reserved_copies: int
    available_copies: int

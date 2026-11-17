"""Reservation persistence and HTTP contracts."""

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, Enum, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ReservationStatus(StrEnum):
    READY = "READY"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        UniqueConstraint("book_id", "member_id", "status", name="uq_active_member_book_status"),
    )

    reservation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    book_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    member_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    status: Mapped[ReservationStatus] = mapped_column(
        Enum(ReservationStatus, name="reservation_status"), default=ReservationStatus.WAITLISTED
    )
    queue_position: Mapped[int] = mapped_column(Integer)
    copy_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ReservationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    book_id: UUID
    member_id: UUID


class ReservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    reservation_id: UUID
    book_id: UUID
    member_id: UUID
    status: ReservationStatus
    queue_position: int
    copy_id: UUID | None
    created_at: datetime

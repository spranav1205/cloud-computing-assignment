"""Lending persistence model and HTTP contracts."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, Index, UniqueConstraint, Uuid, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LoanStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"


class Loan(Base):
    __tablename__ = "loans"
    __table_args__ = (
        UniqueConstraint("reservation_id", name="uq_loans_reservation"),
        Index(
            "uq_loans_active_copy",
            "copy_id",
            unique=True,
            postgresql_where=text("returned_at IS NULL"),
            sqlite_where=text("returned_at IS NULL"),
        ),
    )

    loan_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    book_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    member_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    copy_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    reservation_id: Mapped[UUID] = mapped_column(Uuid)
    checked_out_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def status(self) -> LoanStatus:
        return LoanStatus.RETURNED if self.returned_at is not None else LoanStatus.ACTIVE


class LoanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    member_id: UUID
    reservation_id: UUID
    copy_id: UUID


class LoanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    loan_id: UUID
    book_id: UUID
    member_id: UUID
    copy_id: UUID
    reservation_id: UUID
    status: LoanStatus
    checked_out_at: datetime
    due_at: datetime
    returned_at: datetime | None


class LoanPage(BaseModel):
    items: list[LoanResponse]
    total: int
    limit: int
    offset: int

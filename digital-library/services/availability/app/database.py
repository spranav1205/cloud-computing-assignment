"""Read-only availability derivation from loans and reservations."""

import os
from uuid import UUID

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.catalog import CatalogClient
from app.models import AvailabilityResponse, LoanRecord, ReservationRecord


def configured_engine() -> Engine:
    url = os.environ.get("DATABASE_URL", "sqlite:///./availability.db")
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


class AvailabilityStore:
    def __init__(self, engine: Engine, catalog: CatalogClient):
        self.engine = engine
        self.catalog = catalog

    def ready(self) -> None:
        with Session(self.engine) as session:
            session.execute(text("SELECT 1"))
            session.execute(select(LoanRecord.loan_id).limit(1))
            session.execute(select(ReservationRecord.reservation_id).limit(1))
        self.catalog.ready()

    def for_book(self, book_id: UUID) -> AvailabilityResponse:
        copies = self.catalog.list_copy_ids(book_id)
        with Session(self.engine) as session:
            loans = session.scalars(
                select(LoanRecord).where(
                    LoanRecord.book_id == book_id,
                    LoanRecord.returned_at.is_(None),
                )
            ).all()
            reservations = session.scalars(
                select(ReservationRecord).where(
                    ReservationRecord.book_id == book_id,
                    ReservationRecord.status == "READY",
                )
            ).all()

        loaned_copy_ids = copies.intersection(loan.copy_id for loan in loans)
        checked_out_reservation_ids = {loan.reservation_id for loan in loans}
        active_holds = [
            reservation for reservation in reservations
            if reservation.reservation_id not in checked_out_reservation_ids
        ]
        explicitly_reserved = {
            reservation.copy_id
            for reservation in active_holds
            if reservation.copy_id is not None and reservation.copy_id in copies
        } - loaned_copy_ids
        unassigned_holds = sum(reservation.copy_id is None for reservation in active_holds)
        unallocated_copies = copies - loaned_copy_ids - explicitly_reserved
        unassigned_reserved_count = min(unassigned_holds, len(unallocated_copies))

        return AvailabilityResponse(
            book_id=book_id,
            total_copies=len(copies),
            loaned_copies=len(loaned_copy_ids),
            reserved_copies=len(explicitly_reserved) + unassigned_reserved_count,
            available_copies=len(unallocated_copies) - unassigned_reserved_count,
        )

"""Reservation persistence operations."""

import os
from uuid import UUID

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import Reservation, ReservationCreate, ReservationStatus


class DuplicateReservationError(Exception):
    pass


def configured_engine() -> Engine:
    url = os.environ.get("DATABASE_URL", "sqlite:///./reservation.db")
    return create_engine(url, pool_pre_ping=True, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})


class ReservationStore:
    """Owns database operations while the API owns HTTP concerns."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def create(self, data: ReservationCreate, ready: bool) -> Reservation:
        with Session(self.engine) as session:
            duplicate = session.scalar(
                select(Reservation).where(
                    Reservation.book_id == data.book_id,
                    Reservation.member_id == data.member_id,
                    Reservation.status.in_([ReservationStatus.READY, ReservationStatus.WAITLISTED]),
                )
            )
            if duplicate:
                raise DuplicateReservationError
            active = session.scalar(
                select(func.count()).select_from(Reservation).where(
                    Reservation.book_id == data.book_id,
                    Reservation.status.in_([ReservationStatus.READY, ReservationStatus.WAITLISTED]),
                )
            )
            reservation = Reservation(
                book_id=data.book_id,
                member_id=data.member_id,
                status=ReservationStatus.READY if ready and active == 0 else ReservationStatus.WAITLISTED,
                queue_position=(active or 0) + 1,
            )
            session.add(reservation)
            session.commit()
            session.refresh(reservation)
            return reservation

    def get(self, reservation_id: UUID) -> Reservation | None:
        with Session(self.engine) as session:
            return session.get(Reservation, reservation_id)

    def cancel(self, reservation_id: UUID) -> Reservation | None:
        with Session(self.engine) as session:
            reservation = session.get(Reservation, reservation_id)
            if reservation is None:
                return None
            if reservation.status == ReservationStatus.CANCELLED:
                return reservation
            was_ready = reservation.status == ReservationStatus.READY
            reservation.status = ReservationStatus.CANCELLED
            if was_ready:
                next_reservation = session.scalar(
                    select(Reservation)
                    .where(
                        Reservation.book_id == reservation.book_id,
                        Reservation.status == ReservationStatus.WAITLISTED,
                    )
                    .order_by(Reservation.queue_position, Reservation.created_at)
                    .limit(1)
                )
                if next_reservation:
                    next_reservation.status = ReservationStatus.READY
            session.commit()
            session.refresh(reservation)
            return reservation


def initialize_database(engine: Engine) -> None:
    from app.models import Base

    Base.metadata.create_all(engine)

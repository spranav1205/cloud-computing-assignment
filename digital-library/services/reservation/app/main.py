"""FIFO reservation API."""

from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.coordinator import configured_coordinator
from app.database import (
    DuplicateReservationError,
    ReservationStore,
    configured_engine,
    initialize_database,
)
from app.models import ReservationCreate, ReservationResponse, ReservationStatus


def create_app(store: ReservationStore | None = None, coordinator=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if store is None:
            engine = configured_engine()
            initialize_database(engine)
            application.state.store = ReservationStore(engine)
        else:
            application.state.store = store
        application.state.coordinator = coordinator or configured_coordinator()
        yield

    app = FastAPI(title="Digital Library Reservation Service", lifespan=lifespan)

    @app.exception_handler(DuplicateReservationError)
    async def duplicate_reservation(request: Request, error: DuplicateReservationError):
        return JSONResponse(
            status_code=409,
            content={"detail": "Member already has an active reservation for this book"},
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready(request: Request):
        request.app.state.store.get(UUID(int=0))
        return {"status": "ready"}

    @app.post("/reservations", status_code=201, response_model=ReservationResponse)
    def create(data: ReservationCreate, request: Request):
        with request.app.state.coordinator.lock(str(data.book_id)):
            reservation = request.app.state.store.create(data, ready=True)
        return reservation

    @app.get("/reservations/{reservation_id}", response_model=ReservationResponse)
    def get(reservation_id: UUID, request: Request):
        reservation = request.app.state.store.get(reservation_id)
        if reservation is None:
            raise HTTPException(404, "Reservation not found")
        return reservation

    @app.delete("/reservations/{reservation_id}", response_model=ReservationResponse)
    def cancel(reservation_id: UUID, request: Request):
        existing = request.app.state.store.get(reservation_id)
        if existing is None:
            raise HTTPException(404, "Reservation not found")
        with request.app.state.coordinator.lock(str(existing.book_id)):
            return request.app.state.store.cancel(reservation_id)

    return app

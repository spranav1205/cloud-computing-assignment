"""FIFO reservation API."""

from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.coordinator import configured_coordinator
from app.dependencies import ReservationDependencies
from app.database import (
    DuplicateReservationError,
    ReservationStore,
    configured_engine,
    initialize_database,
)
from app.models import ReservationCreate, ReservationPage, ReservationResponse


def create_app(store: ReservationStore | None = None, coordinator=None, dependencies=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if store is None:
            engine = configured_engine()
            initialize_database(engine)
            application.state.store = ReservationStore(engine)
        else:
            application.state.store = store
        application.state.dependencies = (
            dependencies if dependencies is not None else ReservationDependencies.configured()
        )
        application.state.coordinator = coordinator or configured_coordinator()
        yield
        close_coordinator = getattr(application.state.coordinator, "close", None)
        if close_coordinator is not None:
            close_coordinator()
        if dependencies is None and application.state.dependencies is not None:
            application.state.dependencies.close()

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
        coordinator_ready = getattr(request.app.state.coordinator, "ready", None)
        if coordinator_ready is not None:
            coordinator_ready()
        request.app.state.store.get(UUID(int=0))
        if request.app.state.dependencies is not None:
            request.app.state.dependencies.ready()
        return {"status": "ready"}

    @app.post("/reservations", status_code=201, response_model=ReservationResponse)
    def create(data: ReservationCreate, request: Request):
        dependencies = request.app.state.dependencies
        with request.app.state.coordinator.lock(str(data.book_id)):
            copy_id = dependencies.validate(data) if dependencies is not None else None
            reservation = request.app.state.store.create(
                data, ready=dependencies is None or copy_id is not None, copy_id=copy_id
            )
        return reservation

    @app.get("/reservations", response_model=ReservationPage)
    def list_for_member(
        member_id: UUID,
        request: Request,
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        items, total = request.app.state.store.list_for_member(member_id, limit, offset)
        return {"items": items, "total": total, "limit": limit, "offset": offset}

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

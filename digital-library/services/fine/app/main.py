"""Fine Calculation REST API."""

import logging
import os
import sys
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.database import FineStore, configured_engine
from app.fines import assess_fine
from app.models import FineResponse

logger = logging.getLogger("fine")


def configured_daily_fine_cents() -> int:
    try:
        value = int(os.environ.get("FINE_PER_DAY_CENTS", "100"))
    except ValueError as error:
        raise ValueError("FINE_PER_DAY_CENTS must be a non-negative integer") from error
    if value < 0:
        raise ValueError("FINE_PER_DAY_CENTS must be a non-negative integer")
    return value


def create_app(
    engine: Engine | None = None,
    store: FineStore | None = None,
    daily_fine_cents: int | None = None,
) -> FastAPI:
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
    rate = configured_daily_fine_cents() if daily_fine_cents is None else daily_fine_cents
    if rate < 0:
        raise ValueError("daily_fine_cents must be non-negative")

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.store = store if store is not None else FineStore(
            engine if engine is not None else configured_engine()
        )
        yield
        if engine is None and store is None:
            application.state.store.engine.dispose()

    application = FastAPI(title="Digital Library Fine Calculation Service", lifespan=lifespan)
    registry = CollectorRegistry()
    requests = Counter("fine_http_requests_total", "HTTP requests", ["method", "route", "status"], registry=registry)
    durations = Histogram("fine_http_request_duration_seconds", "HTTP duration", ["method", "route"], registry=registry)

    @application.middleware("http")
    async def record_request(request: Request, call_next):
        started = perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = getattr(request.scope.get("route"), "path", "unmatched")
            elapsed = perf_counter() - started
            requests.labels(request.method, route, str(status)).inc()
            durations.labels(request.method, route).observe(elapsed)
            logger.info("method=%s route=%s status=%s duration=%.3f", request.method, route, status, elapsed)

    @application.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, error: SQLAlchemyError):
        logger.error("Fine database request failed: %s", type(error).__name__)
        return JSONResponse(status_code=503, content={"detail": "Loan database unavailable"})

    @application.get("/health")
    def health():
        return {"status": "ok"}

    @application.get("/ready")
    def ready(request: Request):
        request.app.state.store.ready()
        return {"status": "ready"}

    @application.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(registry), headers={"Content-Type": CONTENT_TYPE_LATEST})

    @application.get("/loans/{loan_id}/fine", response_model=FineResponse)
    def get_fine(loan_id: UUID, request: Request):
        loan = request.app.state.store.get_loan(loan_id)
        if loan is None:
            raise HTTPException(404, "Loan not found")
        return assess_fine(loan, rate)

    return application


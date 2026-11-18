"""Availability REST API."""

import logging
import sys
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import UUID

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.catalog import CatalogBookNotFound, CatalogClient, CatalogUnavailable
from app.database import AvailabilityStore, configured_engine
from app.models import AvailabilityResponse

logger = logging.getLogger("availability")


def create_app(
    engine: Engine | None = None,
    store: AvailabilityStore | None = None,
) -> FastAPI:
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if store is None:
            application.state.catalog = CatalogClient.configured()
            database_engine = engine if engine is not None else configured_engine()
            application.state.store = AvailabilityStore(database_engine, application.state.catalog)
        else:
            application.state.store = store
            application.state.catalog = store.catalog
        yield
        if store is None:
            application.state.catalog.close()
        if engine is None and store is None:
            application.state.store.engine.dispose()

    application = FastAPI(title="Digital Library Availability Service", lifespan=lifespan)
    registry = CollectorRegistry()
    requests = Counter(
        "availability_http_requests_total", "HTTP requests", ["method", "route", "status"], registry=registry
    )
    durations = Histogram(
        "availability_http_request_duration_seconds", "HTTP duration", ["method", "route"], registry=registry
    )

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
            durations.labels(request.method, route).observe(perf_counter() - started)
            requests.labels(request.method, route, str(status)).inc()
            logger.info("method=%s route=%s status=%s", request.method, route, status)

    @application.exception_handler(CatalogBookNotFound)
    async def missing_book(request: Request, error: CatalogBookNotFound):
        return JSONResponse(status_code=404, content={"detail": "Book not found"})

    @application.exception_handler(CatalogUnavailable)
    async def catalog_error(request: Request, error: CatalogUnavailable):
        logger.error("Availability Catalog request failed: %s", error)
        return JSONResponse(status_code=503, content={"detail": "Catalog service unavailable"})

    @application.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, error: SQLAlchemyError):
        logger.error("Availability database request failed: %s", type(error).__name__)
        return JSONResponse(status_code=503, content={"detail": "Availability data unavailable"})

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

    @application.get("/books/{book_id}/availability", response_model=AvailabilityResponse)
    def get_availability(book_id: UUID, request: Request):
        return request.app.state.store.for_book(book_id)

    return application

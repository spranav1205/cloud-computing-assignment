"""Lending REST API."""

import logging
import os
import sys
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.clients import (
    LendingDependencies,
    LendingDependencyError,
)
from app.database import (
    DuplicateLoanError,
    LendingStore,
    configured_engine,
    configured_loan_period_days,
    initialize_database,
)
from app.models import LoanCreate, LoanPage, LoanResponse

logger = logging.getLogger("lending")


def create_app(
    engine: Engine | None = None,
    store: LendingStore | None = None,
    dependencies: LendingDependencies | None = None,
    loan_period_days: int | None = None,
) -> FastAPI:
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
    period = configured_loan_period_days() if loan_period_days is None else loan_period_days
    if period < 1:
        raise ValueError("loan_period_days must be a positive integer")

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if store is None:
            database_engine = engine if engine is not None else configured_engine()
            initialize_database(database_engine)
            application.state.store = LendingStore(database_engine)
        else:
            application.state.store = store
        application.state.dependencies = dependencies if dependencies is not None else LendingDependencies.configured()
        yield
        if engine is None and store is None:
            application.state.store.engine.dispose()
        if dependencies is None:
            application.state.dependencies.close()

    application = FastAPI(title="Digital Library Lending Service", lifespan=lifespan)
    registry = CollectorRegistry()
    requests = Counter("lending_http_requests_total", "HTTP requests", ["method", "route", "status"], registry=registry)
    durations = Histogram(
        "lending_http_request_duration_seconds", "HTTP duration", ["method", "route"], registry=registry
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

    @application.exception_handler(DuplicateLoanError)
    async def duplicate_loan(request: Request, error: DuplicateLoanError):
        return JSONResponse(status_code=409, content={"detail": error.detail})

    @application.exception_handler(LendingDependencyError)
    async def dependency_error(request: Request, error: LendingDependencyError):
        if error.status_code >= 500:
            logger.error("Lending dependency request failed: %s", error.detail)
        return JSONResponse(status_code=error.status_code, content={"detail": error.detail})

    @application.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, error: SQLAlchemyError):
        logger.error("Lending database request failed: %s", type(error).__name__)
        return JSONResponse(status_code=503, content={"detail": "Lending database unavailable"})

    @application.get("/health")
    def health():
        return {"status": "ok"}

    @application.get("/ready")
    def ready(request: Request):
        request.app.state.store.ready()
        request.app.state.dependencies.ready()
        return {"status": "ready"}

    @application.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(registry), headers={"Content-Type": CONTENT_TYPE_LATEST})

    @application.post("/loans", status_code=201, response_model=LoanResponse)
    def checkout(data: LoanCreate, request: Request, response: Response):
        book_id = request.app.state.dependencies.validate_checkout(data)
        loan = request.app.state.store.create(data, book_id, period)
        response.headers["Location"] = f"/loans/{loan.loan_id}"
        return loan

    @application.get("/loans", response_model=LoanPage)
    def list_loans(
        request: Request,
        book_id: UUID | None = None,
        member_id: UUID | None = None,
        active_only: bool = False,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        loans, total = request.app.state.store.list(book_id, member_id, active_only, limit, offset)
        return {"items": loans, "total": total, "limit": limit, "offset": offset}

    @application.get("/loans/{loan_id}", response_model=LoanResponse)
    def get_loan(loan_id: UUID, request: Request):
        loan = request.app.state.store.get(loan_id)
        if loan is None:
            raise HTTPException(404, "Loan not found")
        return loan

    @application.post("/loans/{loan_id}/return", response_model=LoanResponse)
    def return_loan(loan_id: UUID, request: Request):
        loan = request.app.state.store.return_loan(loan_id)
        if loan is None:
            raise HTTPException(404, "Loan not found")
        request.app.state.dependencies.cancel_reservation(loan.reservation_id)
        return loan

    return application

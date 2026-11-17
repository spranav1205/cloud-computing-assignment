"""Member REST API. Start with: python -m uvicorn app.main:create_app --factory."""

import logging
import sys
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app import database
from app.models import MemberCreate, MemberPage, MemberResponse, MemberUpdate

logger = logging.getLogger("member")


def get_session(request: Request):
    with Session(request.app.state.engine) as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise


DbSession = Annotated[Session, Depends(get_session)]


def create_app(engine: Engine | None = None) -> FastAPI:
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.engine = engine if engine is not None else database.configured_engine()
        yield
        if engine is None:
            application.state.engine.dispose()

    application = FastAPI(title="Digital Library Member Service", lifespan=lifespan)
    registry = CollectorRegistry()
    requests = Counter("member_http_requests_total", "HTTP requests", ["method", "route", "status"], registry=registry)
    durations = Histogram("member_http_request_duration_seconds", "HTTP duration", ["method", "route"], registry=registry)

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

    @application.exception_handler(IntegrityError)
    async def integrity_error(request: Request, error: IntegrityError):
        # PostgreSQL reports the named constraint without inspecting sensitive SQL parameters.
        constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
        if constraint == "uq_members_email":
            return JSONResponse(status_code=409, content={"detail": "Email already registered"})
        return JSONResponse(status_code=500, content={"detail": "Database constraint failure"})

    @application.exception_handler(OperationalError)
    async def storage_error(request: Request, error: OperationalError):
        logger.error("Member database unavailable")
        return JSONResponse(status_code=503, content={"detail": "Database unavailable"})

    @application.get("/health")
    def health():
        return {"status": "ok"}

    @application.get("/ready")
    def ready(session: DbSession):
        session.execute(text("SELECT 1"))
        return {"status": "ready"}

    @application.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(registry), headers={"Content-Type": CONTENT_TYPE_LATEST})

    @application.post("/members", response_model=MemberResponse, status_code=201)
    def create(data: MemberCreate, response: Response, session: DbSession):
        member = database.create_member(session, data)
        response.headers["Location"] = f"/members/{member.member_id}"
        return member

    @application.get("/members", response_model=MemberPage)
    def list_all(session: DbSession, limit: Annotated[int, Query(ge=1, le=100)] = 20,
                 offset: Annotated[int, Query(ge=0)] = 0):
        return {"items": database.list_members(session, limit, offset), "limit": limit, "offset": offset}

    @application.get("/members/{member_id}", response_model=MemberResponse)
    def get_one(member_id: UUID, session: DbSession):
        member = database.get_member(session, member_id)
        if member is None:
            raise HTTPException(404, "Member not found")
        return member

    @application.patch("/members/{member_id}", response_model=MemberResponse)
    def patch(member_id: UUID, data: MemberUpdate, session: DbSession):
        member = database.get_member(session, member_id)
        if member is None:
            raise HTTPException(404, "Member not found")
        return database.update_member(session, member, data)

    return application

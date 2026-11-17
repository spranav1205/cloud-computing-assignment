"""Minimal Catalog HTTP endpoints; storage calls stay in database.py."""

import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Annotated
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST

from app.database import CatalogDatabase, local_resource
from app.models import BookCreate, BookPage, BookResponse, CopyPage, CopyResponse

logger = logging.getLogger("catalog")


def continuation_key(value: str | None, book_id: str | None = None) -> dict | None:
    if value is None:
        return None
    try:
        key = json.loads(value)
        expected = {"book_id", "copy_id"} if book_id else {"book_id"}
        if not isinstance(key, dict) or set(key) != expected:
            raise ValueError()
        for item in key.values():
            if not isinstance(item, str) or str(UUID(item)) != item:
                raise ValueError()
        if book_id and key["book_id"] != book_id:
            raise ValueError()
        return key
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, "Invalid last_evaluated_key") from None


def create_app(database: CatalogDatabase | None = None) -> FastAPI:
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")

    @asynccontextmanager
    async def lifespan(app):
        app.state.database = database if database is not None else CatalogDatabase(
            local_resource(), os.environ.get("BOOKS_TABLE", "Books"), os.environ.get("COPIES_TABLE", "Copies"))
        yield
        if database is None:
            app.state.database.books.meta.client.close()

    app = FastAPI(title="Digital Library Catalog Service", lifespan=lifespan)
    registry = CollectorRegistry()
    requests = Counter("catalog_http_requests_total", "HTTP requests", ["method", "route", "status"], registry=registry)
    durations = Histogram("catalog_http_request_duration_seconds", "HTTP duration", ["method", "route"], registry=registry)

    @app.middleware("http")
    async def metrics_logging(request: Request, call_next):
        start = perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = getattr(request.scope.get("route"), "path", "unmatched")
            duration = perf_counter() - start
            requests.labels(request.method, route, str(status)).inc()
            durations.labels(request.method, route).observe(duration)
            logger.info("method=%s route=%s status=%s duration=%.3f", request.method, route, status, duration)

    @app.exception_handler(ClientError)
    async def client_error(request, error):
        code = error.response["Error"]["Code"]
        if code == "ConditionalCheckFailedException":
            return JSONResponse(status_code=409, content={"detail": "Resource already exists"})
        logger.error("DynamoDB request failed: %s", code)
        return JSONResponse(status_code=503, content={"detail": "Catalog storage unavailable"})

    @app.exception_handler(BotoCoreError)
    async def connection_error(request, error):
        return JSONResponse(status_code=503, content={"detail": "Catalog storage unavailable"})

    def require_book(db, book_id):
        book = db.get_book(str(book_id))
        if book is None:
            raise HTTPException(404, "Book not found")
        return book

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready(request: Request):
        request.app.state.database.ready()
        return {"status": "ready"}

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(registry), headers={"Content-Type": CONTENT_TYPE_LATEST})

    @app.post("/books", status_code=201, response_model=BookResponse)
    def create(data: BookCreate, request: Request, response: Response):
        book = request.app.state.database.create_book(data)
        response.headers["Location"] = f"/books/{book['book_id']}"
        return book

    @app.get("/books", response_model=BookPage)
    def list_books(request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 20,
                   last_evaluated_key: Annotated[str | None, Query(max_length=1000)] = None):
        return request.app.state.database.list_books(limit, continuation_key(last_evaluated_key))

    @app.get("/books/{book_id}", response_model=BookResponse)
    def get_book(book_id: UUID, request: Request):
        return require_book(request.app.state.database, book_id)

    @app.post("/books/{book_id}/copies", status_code=201, response_model=CopyResponse)
    def create_copy(book_id: UUID, request: Request):
        db = request.app.state.database
        require_book(db, book_id)
        return db.create_copy(str(book_id))

    @app.get("/books/{book_id}/copies", response_model=CopyPage)
    def list_copies(book_id: UUID, request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 20,
                    last_evaluated_key: Annotated[str | None, Query(max_length=1000)] = None):
        db = request.app.state.database
        key = continuation_key(last_evaluated_key, str(book_id))
        require_book(db, book_id)
        return db.list_copies(str(book_id), limit, key)

    return app

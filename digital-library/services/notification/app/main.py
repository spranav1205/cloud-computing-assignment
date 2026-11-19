"""Event-driven notification intake API."""

import logging
import sys
from time import perf_counter

from fastapi import FastAPI, Request, Response
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST

from app.models import NotificationEvent, NotificationReceipt
from app.queue import configured_queue


def create_app(queue=None) -> FastAPI:
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
    app = FastAPI(title="Digital Library Notification Service")
    app.state.queue = queue or configured_queue()
    registry = CollectorRegistry()
    requests = Counter("notification_http_requests_total", "HTTP requests", ["method", "route", "status"], registry=registry)
    durations = Histogram("notification_http_request_duration_seconds", "HTTP duration", ["method", "route"], registry=registry)

    @app.middleware("http")
    async def record_request(request: Request, call_next):
        started = perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = getattr(request.scope.get("route"), "path", "unmatched")
            requests.labels(request.method, route, str(status)).inc()
            durations.labels(request.method, route).observe(perf_counter() - started)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        return {"status": "ready"}

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(registry), headers={"Content-Type": CONTENT_TYPE_LATEST})

    @app.post("/notifications", status_code=202, response_model=NotificationReceipt)
    def enqueue(event: NotificationEvent, request: Request):
        notification_id = request.app.state.queue.publish(event)
        return {"notification_id": notification_id, "status": "QUEUED"}

    return app

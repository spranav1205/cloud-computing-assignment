"""Event-driven notification intake API."""

import logging
import sys
from uuid import UUID

from fastapi import FastAPI, Request

from app.models import NotificationEvent, NotificationReceipt
from app.queue import configured_queue


def create_app(queue=None) -> FastAPI:
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
    app = FastAPI(title="Digital Library Notification Service")
    app.state.queue = queue or configured_queue()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        return {"status": "ready"}

    @app.post("/notifications", status_code=202, response_model=NotificationReceipt)
    def enqueue(event: NotificationEvent, request: Request):
        notification_id = request.app.state.queue.publish(event)
        return {"notification_id": notification_id, "status": "QUEUED"}

    return app

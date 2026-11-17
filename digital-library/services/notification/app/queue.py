"""Queue and delivery ports for notifications."""

import json
import logging
import os
from collections import deque
from threading import Lock
from uuid import UUID, uuid4

import boto3

from app.models import NotificationEvent

logger = logging.getLogger("notification")


class NotificationQueue:
    def publish(self, event: NotificationEvent) -> UUID:
        raise NotImplementedError


class InMemoryQueue(NotificationQueue):
    def __init__(self):
        self.events: deque[tuple[UUID, NotificationEvent]] = deque()
        self._lock = Lock()

    def publish(self, event: NotificationEvent) -> UUID:
        notification_id = uuid4()
        with self._lock:
            self.events.append((notification_id, event))
        return notification_id


class SqsQueue(NotificationQueue):
    def __init__(self):
        queue_url = os.environ["NOTIFICATION_QUEUE_URL"]
        self.client = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        self.queue_url = queue_url

    def publish(self, event: NotificationEvent) -> UUID:
        notification_id = uuid4()
        self.client.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps({"notification_id": str(notification_id), "event": event.model_dump(mode="json")}),
        )
        return notification_id


def configured_queue() -> NotificationQueue:
    return SqsQueue() if os.environ.get("NOTIFICATION_QUEUE_URL") else InMemoryQueue()


def deliver(event: NotificationEvent) -> None:
    logger.info(
        "notification_sent event_type=%s member_id=%s message=%s",
        event.event_type,
        event.member_id,
        event.message,
    )

"""Small SQS worker entrypoint; delivery is deliberately replaceable."""

import json
import logging
import os
import time

import boto3

from app.models import NotificationEvent
from app.queue import deliver

logger = logging.getLogger("notification-worker")


def run() -> None:
    client = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "ap-south-1"))
    queue_url = os.environ["NOTIFICATION_QUEUE_URL"]
    while True:
        response = client.receive_message(
            QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=20
        )
        for message in response.get("Messages", []):
            try:
                body = json.loads(message["Body"])
                event = NotificationEvent.model_validate(body["event"])
                if body.get("recipient") != str(event.recipient) or body.get("body") != event.body:
                    raise ValueError("notification envelope does not match event")
                deliver(event)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                # Leave malformed messages for the queue redrive policy.
                logger.exception("notification_message_invalid message_id=%s", message.get("MessageId"))
                continue
            except Exception:
                logger.exception("notification_delivery_failed")
                continue
            client.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
        if not response.get("Messages"):
            time.sleep(1)


if __name__ == "__main__":
    run()

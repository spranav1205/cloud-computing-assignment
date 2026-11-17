"""Small SQS worker entrypoint; delivery is deliberately replaceable."""

import json
import os
import time

import boto3

from app.models import NotificationEvent
from app.queue import deliver


def run() -> None:
    client = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    queue_url = os.environ["NOTIFICATION_QUEUE_URL"]
    while True:
        response = client.receive_message(
            QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=20
        )
        for message in response.get("Messages", []):
            body = json.loads(message["Body"])
            deliver(NotificationEvent.model_validate(body["event"]))
            client.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
        if not response.get("Messages"):
            time.sleep(1)


if __name__ == "__main__":
    run()

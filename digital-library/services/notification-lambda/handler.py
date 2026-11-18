"""AWS Lambda notification consumer for the SQS event-driven service."""

import json
import logging
import os
import time

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def _clients():
    return boto3.client("ses"), boto3.resource("dynamodb").Table(os.environ["NOTIFICATION_DEDUPE_TABLE"])


def lambda_handler(event, context):
    ses, dedupe = _clients()
    failures = []
    for record in event.get("Records", []):
        notification_id = None
        try:
            message = json.loads(record["body"])
            event = message["event"]
            recipient = message["recipient"]
            subject = message.get("subject", "Digital Library notification")
            body = message["body"]
            if recipient != str(event["recipient"]) or body != event["body"]:
                raise ValueError("notification envelope does not match event")
            notification_id = message["notification_id"]
            try:
                dedupe.put_item(
                    Item={"notification_id": notification_id, "ttl": int(time.time()) + 1209600},
                    ConditionExpression="attribute_not_exists(notification_id)",
                )
            except dedupe.meta.client.exceptions.ConditionalCheckFailedException:
                logger.info("notification_duplicate notification_id=%s", notification_id)
                continue
            ses.send_email(
                Source=os.environ["SES_SENDER"],
                Destination={"ToAddresses": [recipient]},
                Message={
                    "Subject": {"Data": subject},
                    "Body": {"Text": {"Data": body}},
                },
            )
            logger.info("notification_delivered notification_id=%s", notification_id)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            logger.exception("notification_message_invalid")
            failures.append({"itemIdentifier": record.get("messageId", "unknown")})
        except Exception:
            logger.exception("notification_delivery_failed")
            if notification_id is not None:
                dedupe.delete_item(Key={"notification_id": notification_id})
            failures.append({"itemIdentifier": record.get("messageId", "unknown")})
    return {"batchItemFailures": failures}

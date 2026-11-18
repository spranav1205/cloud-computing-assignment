"""AWS Lambda notification consumer for the SQS event-driven service."""

import json
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ses = boto3.client("ses")


def lambda_handler(event, context):
    failures = []
    for record in event.get("Records", []):
        try:
            message = json.loads(record["body"])
            recipient = message["recipient"]
            subject = message.get("subject", "Digital Library notification")
            body = message["body"]
            ses.send_email(
                Source=os.environ["SES_SENDER"],
                Destination={"ToAddresses": [recipient]},
                Message={
                    "Subject": {"Data": subject},
                    "Body": {"Text": {"Data": body}},
                },
            )
            logger.info("notification_delivered event_id=%s", message.get("event_id"))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            logger.exception("notification_message_invalid")
            failures.append({"itemIdentifier": record.get("messageId", "unknown")})
        except Exception:
            logger.exception("notification_delivery_failed")
            failures.append({"itemIdentifier": record.get("messageId", "unknown")})
    return {"batchItemFailures": failures}

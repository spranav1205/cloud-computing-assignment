"""Best-effort notifications after committed loan transitions."""

import os
from datetime import timezone
from uuid import NAMESPACE_URL, uuid5

import httpx

from app.models import Loan


def notification_id(loan_id, event_type):
    return uuid5(NAMESPACE_URL, f"digital-library/loans/{loan_id}/{event_type}")


class LoanNotifications:
    def __init__(self, member_url, notification_url, client=None):
        self.member_url = member_url.rstrip("/")
        self.notification_url = notification_url.rstrip("/")
        self.client = client or httpx.Client(timeout=2.0)

    @classmethod
    def configured(cls):
        return cls(
            os.environ.get("MEMBER_URL", "http://member:8001"),
            os.environ.get("NOTIFICATION_URL", "http://notification:8004"),
        )

    def publish(self, loan: Loan, event_type: str):
        member = self.client.get(f"{self.member_url}/members/{loan.member_id}")
        member.raise_for_status()
        occurred_at = loan.checked_out_at if event_type == "LoanIssued" else loan.returned_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        event_id = notification_id(loan.loan_id, event_type)
        event = {
            "event_id": str(event_id),
            "event_type": event_type,
            "member_id": str(loan.member_id),
            "recipient": member.json()["email"],
            "subject": "Library loan issued" if event_type == "LoanIssued" else "Library loan returned",
            "body": f"Loan {loan.loan_id} for book {loan.book_id} "
                    + (f"was issued. Due: {loan.due_at.isoformat()}." if event_type == "LoanIssued" else "was returned."),
            "occurred_at": occurred_at.isoformat(),
        }
        receipt = self.client.post(f"{self.notification_url}/notifications", json=event)
        receipt.raise_for_status()
        if receipt.status_code != 202 or receipt.json().get("notification_id") != str(event_id):
            raise ValueError("Notification service returned an invalid receipt")
        return event_id

    def close(self):
        self.client.close()

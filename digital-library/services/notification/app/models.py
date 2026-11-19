"""Notification event contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class NotificationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal[
        "ReservationReady", "AvailabilityChanged", "DueDateReminder", "LoanIssued", "LoanReturned"
    ]
    event_id: UUID | None = None
    recipient: EmailStr
    subject: str = Field(default="Digital Library notification", min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=1000)
    member_id: UUID
    occurred_at: datetime


class NotificationReceipt(BaseModel):
    notification_id: UUID
    status: Literal["QUEUED", "SENT"]

"""Notification event contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NotificationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal[
        "ReservationReady", "AvailabilityChanged", "DueDateReminder", "LoanReturned"
    ]
    member_id: UUID
    message: str = Field(min_length=1, max_length=1000)
    occurred_at: datetime


class NotificationReceipt(BaseModel):
    notification_id: UUID
    status: Literal["QUEUED", "SENT"]

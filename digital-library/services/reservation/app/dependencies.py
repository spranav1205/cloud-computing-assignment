"""Cross-service checks required before creating a reservation."""

import os

import httpx
from fastapi import HTTPException

from app.models import ReservationCreate


class ReservationDependencies:
    def __init__(self, member_url: str, availability_url: str, client: httpx.Client | None = None):
        self.member_url = member_url.rstrip("/")
        self.availability_url = availability_url.rstrip("/")
        self.client = client or httpx.Client(timeout=5.0)

    @classmethod
    def configured(cls) -> "ReservationDependencies | None":
        member_url = os.environ.get("MEMBER_URL")
        availability_url = os.environ.get("AVAILABILITY_URL")
        if not member_url or not availability_url:
            return None
        return cls(member_url, availability_url)

    def validate(self, data: ReservationCreate) -> str | None:
        self._get(f"{self.member_url}/members/{data.member_id}", "Member not found")
        availability = self._get(
            f"{self.availability_url}/books/{data.book_id}/availability",
            "Book not found",
        )
        try:
            copy_ids = availability["available_copy_ids"]
            return str(copy_ids[0]) if copy_ids else None
        except (KeyError, TypeError, IndexError) as error:
            raise HTTPException(503, "Availability service returned an invalid response") from error

    def ready(self) -> None:
        self._get(f"{self.member_url}/ready", "Member service unavailable")

    def close(self) -> None:
        self.client.close()

    def _get(self, url: str, not_found: str) -> dict:
        try:
            response = self.client.get(url)
        except httpx.RequestError as error:
            raise HTTPException(503, "Required library service unavailable") from error
        if response.status_code == 404:
            raise HTTPException(404, not_found)
        if response.is_error:
            raise HTTPException(503, "Required library service unavailable")
        try:
            payload = response.json()
        except ValueError as error:
            raise HTTPException(503, "Required library service returned invalid data") from error
        if not isinstance(payload, dict):
            raise HTTPException(503, "Required library service returned invalid data")
        return payload

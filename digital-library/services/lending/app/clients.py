"""REST checks against member, catalog, and reservation services."""

import json
import logging
import os
from uuid import UUID

import httpx

from app.models import LoanCreate

logger = logging.getLogger("lending")


class LendingDependencyError(Exception):
    status_code = 503

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class LendingDependencyNotFound(LendingDependencyError):
    status_code = 404


class CheckoutConflict(LendingDependencyError):
    status_code = 409


class LendingDependencies:
    def __init__(
        self,
        member_url: str,
        catalog_url: str,
        reservation_url: str,
        client: httpx.Client | None = None,
    ):
        self.member_url = member_url.rstrip("/")
        self.catalog_url = catalog_url.rstrip("/")
        self.reservation_url = reservation_url.rstrip("/")
        self.client = client or httpx.Client(timeout=5.0)

    @classmethod
    def configured(cls) -> "LendingDependencies":
        return cls(
            os.environ.get("MEMBER_URL", "http://member:8001"),
            os.environ.get("CATALOG_URL", "http://catalog:8002"),
            os.environ.get("RESERVATION_URL", "http://reservation:8003"),
        )

    def validate_checkout(self, data: LoanCreate) -> UUID:
        reservation = self._get(
            f"{self.reservation_url}/reservations/{data.reservation_id}",
            "Reservation not found",
        )
        if reservation.get("status") != "READY":
            raise CheckoutConflict("Reservation is not ready for checkout")
        if reservation.get("member_id") != str(data.member_id):
            raise CheckoutConflict("Reservation belongs to a different member")
        try:
            book_id = UUID(reservation["book_id"])
        except (KeyError, TypeError, ValueError) as error:
            raise LendingDependencyError("Reservation service returned an invalid reservation") from error

        self._get(f"{self.member_url}/members/{data.member_id}", "Member not found")
        self._require_copy(book_id, data.copy_id)
        return book_id

    def cancel_reservation(self, reservation_id: UUID) -> None:
        url = f"{self.reservation_url}/reservations/{reservation_id}"
        try:
            response = self.client.delete(url)
        except httpx.RequestError as error:
            raise LendingDependencyError("Reservation service unavailable") from error
        if response.status_code == 404:
            logger.warning("Reservation %s was already absent after loan return", reservation_id)
            return
        if response.is_error:
            raise LendingDependencyError("Reservation service unavailable")

    def ready(self) -> None:
        for name, url in (
            ("Member", self.member_url),
            ("Catalog", self.catalog_url),
            ("Reservation", self.reservation_url),
        ):
            try:
                response = self.client.get(f"{url}/ready")
            except httpx.RequestError as error:
                raise LendingDependencyError(f"{name} service unavailable") from error
            if response.is_error:
                raise LendingDependencyError(f"{name} service unavailable")

    def close(self) -> None:
        self.client.close()

    def _get(self, url: str, not_found: str) -> dict:
        try:
            response = self.client.get(url)
        except httpx.RequestError as error:
            raise LendingDependencyError("A required library service is unavailable") from error
        if response.status_code == 404:
            raise LendingDependencyNotFound(not_found)
        if response.is_error:
            raise LendingDependencyError("A required library service is unavailable")
        try:
            payload = response.json()
        except ValueError as error:
            raise LendingDependencyError("A library service returned an invalid response") from error
        if not isinstance(payload, dict):
            raise LendingDependencyError("A library service returned an invalid response")
        return payload

    def _require_copy(self, book_id: UUID, copy_id: UUID) -> None:
        continuation_key = None
        seen_keys: set[str] = set()
        while True:
            params: dict[str, str | int] = {"limit": 100}
            if continuation_key is not None:
                params["last_evaluated_key"] = json.dumps(continuation_key, separators=(",", ":"))
            try:
                response = self.client.get(
                    f"{self.catalog_url}/books/{book_id}/copies",
                    params=params,
                )
            except httpx.RequestError as error:
                raise LendingDependencyError("Catalog service unavailable") from error
            if response.status_code == 404:
                raise LendingDependencyNotFound("Book not found")
            if response.is_error:
                raise LendingDependencyError("Catalog service unavailable")
            try:
                page = response.json()
                if any(item.get("copy_id") == str(copy_id) for item in page["items"]):
                    return
                continuation_key = page["last_evaluated_key"]
            except (KeyError, TypeError, ValueError) as error:
                raise LendingDependencyError("Catalog returned an invalid copy list") from error
            if continuation_key is None:
                raise LendingDependencyNotFound("Copy not found for this book")
            key_token = json.dumps(continuation_key, sort_keys=True)
            if key_token in seen_keys:
                raise LendingDependencyError("Catalog returned a repeated pagination key")
            seen_keys.add(key_token)

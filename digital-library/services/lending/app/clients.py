"""REST checks against member, catalog, and reservation services."""

import json
import logging
import os
from uuid import UUID

import httpx
import grpc

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
        self.member_grpc_target = os.environ.get("MEMBER_GRPC_TARGET")
        self.member_grpc = (
            grpc.insecure_channel(self.member_grpc_target)
            if self.member_grpc_target
            else None
        )

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
        if reservation.get("copy_id") != str(data.copy_id):
            raise CheckoutConflict("Checkout copy does not match the reservation allocation")

        if self.member_grpc is not None:
            self._check_member_grpc(data.member_id, data.copy_id)
        else:
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
        if self.member_grpc is not None:
            self.member_grpc.close()

    def _check_member_grpc(self, member_id: UUID, copy_id: UUID) -> None:
        call = self.member_grpc.unary_unary(
            "/library.member.v1.MemberEligibility/CheckoutEligibility",
            request_serializer=lambda value: json.dumps(value).encode("utf-8"),
            response_deserializer=lambda value: json.loads(value.decode("utf-8")),
        )
        try:
            result = call({"member_id": str(member_id), "copy_id": str(copy_id)}, timeout=5)
        except grpc.RpcError as error:
            raise LendingDependencyError("Member gRPC service unavailable") from error
        if not result.get("eligible"):
            reason = result.get("reason_code", "NOT_ELIGIBLE")
            if reason == "MEMBER_NOT_FOUND":
                raise LendingDependencyNotFound("Member not found")
            raise CheckoutConflict("Member is not eligible for checkout")

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

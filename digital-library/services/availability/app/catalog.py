"""Read copy identities from the Catalog REST API."""

import json
import os
from uuid import UUID

import httpx


class CatalogBookNotFound(Exception):
    pass


class CatalogUnavailable(Exception):
    pass


class CatalogClient:
    def __init__(self, base_url: str, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=5.0)

    @classmethod
    def configured(cls) -> "CatalogClient":
        return cls(os.environ.get("CATALOG_URL", "http://catalog:8002"))

    def ready(self) -> None:
        try:
            response = self.client.get(f"{self.base_url}/ready")
        except httpx.RequestError as error:
            raise CatalogUnavailable("Catalog service unavailable") from error
        if response.is_error:
            raise CatalogUnavailable("Catalog service unavailable")

    def list_copy_ids(self, book_id: UUID) -> set[UUID]:
        continuation_key = None
        seen_keys: set[str] = set()
        copy_ids: set[UUID] = set()
        while True:
            params: dict[str, str | int] = {"limit": 100}
            if continuation_key is not None:
                params["last_evaluated_key"] = json.dumps(continuation_key, separators=(",", ":"))
            try:
                response = self.client.get(
                    f"{self.base_url}/books/{book_id}/copies",
                    params=params,
                )
            except httpx.RequestError as error:
                raise CatalogUnavailable("Catalog service unavailable") from error
            if response.status_code == 404:
                raise CatalogBookNotFound
            if response.is_error:
                raise CatalogUnavailable("Catalog service returned an error")
            try:
                page = response.json()
                copy_ids.update(UUID(item["copy_id"]) for item in page["items"])
                continuation_key = page["last_evaluated_key"]
            except (KeyError, TypeError, ValueError) as error:
                raise CatalogUnavailable("Catalog returned an invalid copy list") from error
            if continuation_key is None:
                return copy_ids
            key_token = json.dumps(continuation_key, sort_keys=True)
            if key_token in seen_keys:
                raise CatalogUnavailable("Catalog returned a repeated pagination key")
            seen_keys.add(key_token)

    def close(self) -> None:
        self.client.close()

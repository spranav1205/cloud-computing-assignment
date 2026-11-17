"""Catalog request validation; no availability or lending attributes."""

import re
from typing import Literal
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BookCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=300)
    author: str = Field(min_length=1, max_length=200)
    isbn: str | None = None

    @field_validator("isbn")
    @classmethod
    def basic_isbn(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.replace("-", "").replace(" ", "").upper()
        if not re.fullmatch(r"(?:[0-9]{13}|[0-9]{9}[0-9X])", value):
            raise ValueError("ISBN must have 10 or 13 characters in ISBN format")
        return value


class BookResponse(BaseModel):
    book_id: UUID
    title: str
    author: str
    isbn: str | None = None
    cover_key: str | None = None
    created_at: datetime


class CopyResponse(BaseModel):
    copy_id: UUID
    book_id: UUID


class BookPage(BaseModel):
    items: list[BookResponse]
    last_evaluated_key: dict[str, str] | None


class CopyPage(BaseModel):
    items: list[CopyResponse]
    last_evaluated_key: dict[str, str] | None


class CoverUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content_type: Literal["image/jpeg", "image/png"]


class CoverConfirm(BaseModel):
    # Empty/absent body only: keys are always loaded from the book, never the client.
    model_config = ConfigDict(extra="forbid")

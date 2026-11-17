"""Member persistence model and public request/response contracts."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from sqlalchemy import DateTime, String, UniqueConstraint, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Member(Base):
    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("email", name="uq_members_email"),)

    member_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(254))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class MemberInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("name", mode="before", check_fields=False)
    @classmethod
    def trim_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("email", mode="after", check_fields=False)
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 254:
            raise ValueError("Email must be at most 254 characters")
        return value.lower() if value is not None else value


class MemberCreate(MemberInput):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr


class MemberUpdate(MemberInput):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = None

    @model_validator(mode="after")
    def require_changes(self) -> "MemberUpdate":
        if not self.model_fields_set:
            raise ValueError("Provide name or email")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Updated fields cannot be null")
        return self


class MemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    member_id: UUID
    name: str
    email: str
    created_at: datetime


class MemberPage(BaseModel):
    items: list[MemberResponse]
    limit: int
    offset: int

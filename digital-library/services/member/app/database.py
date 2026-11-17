"""Small SQLAlchemy queries; PostgreSQL enforces email uniqueness."""

import os
from uuid import UUID

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from app.models import Member, MemberCreate, MemberUpdate


def configured_engine() -> Engine:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("Set DATABASE_URL to a local PostgreSQL connection URL")
    if not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("DATABASE_URL must use postgresql+psycopg://")
    mode = os.environ.get("APP_ENV", "local")
    if mode not in {"local", "aws"}:
        raise RuntimeError("APP_ENV must be local or aws")
    if mode == "aws":
        query = make_url(url).query
        if query.get("sslmode") != "verify-full" or not query.get("sslrootcert"):
            raise RuntimeError("AWS database connections require sslmode=verify-full and sslrootcert")
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})


def create_member(session: Session, data: MemberCreate) -> Member:
    member = Member(**data.model_dump())
    session.add(member)
    session.commit()
    session.refresh(member)
    return member


def list_members(session: Session, limit: int, offset: int) -> list[Member]:
    query = select(Member).order_by(Member.created_at, Member.member_id)
    return list(session.scalars(query.limit(limit).offset(offset)))


def get_member(session: Session, member_id: UUID) -> Member | None:
    return session.get(Member, member_id)


def update_member(session: Session, member: Member, data: MemberUpdate) -> Member:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(member, field, value)
    session.commit()
    session.refresh(member)
    return member

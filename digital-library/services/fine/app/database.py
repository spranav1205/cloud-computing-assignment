"""Read-only database access for fine assessment."""

import os
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import Loan


def configured_engine() -> Engine:
    url = os.environ.get("DATABASE_URL", "sqlite:///./fine.db")
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


class FineStore:
    def __init__(self, engine: Engine):
        self.engine = engine

    def ready(self) -> None:
        with Session(self.engine) as session:
            session.execute(text("SELECT 1"))

    def get_loan(self, loan_id: UUID) -> Loan | None:
        with Session(self.engine) as session:
            return session.get(Loan, loan_id)

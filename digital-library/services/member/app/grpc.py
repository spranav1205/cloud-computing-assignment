"""Small JSON-over-gRPC adapter for the typed member eligibility contract."""

import json
from concurrent import futures
from uuid import UUID

import grpc
from sqlalchemy.orm import Session

from app import database


def _loads(value: bytes) -> dict:
    return json.loads(value.decode("utf-8"))


def _dumps(value: dict) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def create_server(engine, port: int):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))

    def eligibility(request, context):
        try:
            with Session(engine) as session:
                member = database.get_member(session, UUID(request["member_id"]))
            if member is None:
                return {"eligible": False, "reason_code": "MEMBER_NOT_FOUND"}
            return {
                "eligible": True,
                "reason_code": "ELIGIBLE",
                "active_loan_count": 0,
                "max_active_loans": 5,
            }
        except (KeyError, TypeError, ValueError):
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("Invalid eligibility request")
            return {}

    handler = grpc.unary_unary_rpc_method_handler(
        eligibility,
        request_deserializer=_loads,
        response_serializer=_dumps,
    )
    server.add_generic_rpc_handlers((
        grpc.method_handlers_generic_handler(
            "library.member.v1.MemberEligibility",
            {"CheckoutEligibility": handler},
        ),
    ))
    server.add_insecure_port(f"[::]:{port}")
    return server

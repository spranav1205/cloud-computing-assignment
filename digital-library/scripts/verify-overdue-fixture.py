"""Run inside the deployed Fine container; use only an isolated temporary DB.

PowerShell from repository root:
  Get-Content digital-library/scripts/verify-overdue-fixture.py -Raw |
    kubectl --kubeconfig digital-library/.local/recovery-kubeconfig -n library exec -i deployment/fine -- python -

This exercises deployed code over loopback HTTP, not the public ingress or RDS.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import time
from urllib.error import HTTPError
from urllib.request import urlopen
from uuid import uuid4

from sqlalchemy import create_engine
import uvicorn

import app.main
from app.main import configured_daily_fine_cents, create_app
from app.models import Base, Loan


def main():
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, force=True)
    report = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "scope": "deployed Fine code, isolated SQLite, loopback HTTP; no production DB access",
        "source_sha256": hashlib.sha256(Path(app.main.__file__).read_bytes()).hexdigest(),
        "cases": [],
    }
    rate = configured_daily_fine_cents()
    assert rate > 0, "Positive fine demonstration requires a positive configured rate"
    with TemporaryDirectory(prefix="fine-fixture-") as directory:
        engine = create_engine(f"sqlite:///{directory}/fixture.db", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        due = datetime(2026, 1, 1, tzinfo=timezone.utc)
        cases = [
            ("returned_partial_day", due, due + timedelta(days=2, seconds=1), 3),
            ("active_overdue", datetime.now(timezone.utc) - timedelta(days=2, minutes=1), None, 3),
            ("returned_on_time", due, due, 0),
        ]
        fixtures = []
        with engine.begin() as connection:
            for name, due_at, returned_at, expected_days in cases:
                loan_id = uuid4()
                connection.execute(Loan.__table__.insert().values(
                    loan_id=loan_id, due_at=due_at, returned_at=returned_at,
                ))
                fixtures.append((name, loan_id, expected_days))

        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_app(engine=engine), log_level="error", access_log=False))
        thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 15
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError("Isolated fixture HTTP server failed to start")
                time.sleep(0.05)
            for name, loan_id, expected_days in fixtures:
                with urlopen(f"http://127.0.0.1:{port}/loans/{loan_id}/fine", timeout=10) as response:
                    result = json.load(response)
                    assert response.status == 200
                assert result["overdue_days"] == expected_days, result
                assert result["daily_fine_cents"] == rate, result
                assert result["fine_amount_cents"] == expected_days * rate, result
                report["cases"].append({"name": name, "http_status": 200, "response": result, "passed": True})
            try:
                urlopen(f"http://127.0.0.1:{port}/loans/{uuid4()}/fine", timeout=10)
            except HTTPError as error:
                assert error.code == 404
                report["cases"].append({"name": "missing_loan", "http_status": error.code, "passed": True})
            else:
                raise AssertionError("Missing loan must return 404")
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            listener.close()
            engine.dispose()
            assert not thread.is_alive(), "Fixture server did not stop"
    report["temporary_database_removed"] = not Path(directory).exists()
    assert report["temporary_database_removed"]
    report["status"] = "PASS"
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

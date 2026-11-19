"""Live seven-service smoke test. Python standard library only; leaves demo records.

Defaults match Compose or the port forwards opened by deploy_aws.py test.
Never sends a notification to a real recipient unless explicitly configured.
"""

import argparse
import base64
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4


SERVICES = {"member": 8001, "catalog": 8002, "reservation": 8003,
            "notification": 8004, "fine": 8005, "lending": 8006, "availability": 8007}
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1sAAAAASUVORK5CYII=")
STATE_DIR = Path(__file__).resolve().parents[1] / ".local" / "smoke"


class SmokeFailure(RuntimeError):
    pass


def require(condition, message):
    # Unlike assert, checks remain enabled under python -O.
    if not condition:
        raise SmokeFailure(message)


def request(method, url, expected=200, body=None, headers=None, raw=False):
    data = body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None
    headers = dict(headers or {})
    if body is not None and not isinstance(body, bytes):
        headers.setdefault("Content-Type", "application/json")
    try:
        with urlopen(Request(url, data=data, headers=headers, method=method), timeout=20) as response:
            status, payload = response.status, response.read()
    except HTTPError as error:
        status, payload = error.code, error.read()
    except (URLError, TimeoutError, OSError):
        raise SmokeFailure(f"{method} {urlsplit(url).path}: connection failed") from None
    # Do not print signed URL query strings, credentials, or response bodies.
    require(status == expected, f"{method} {urlsplit(url).path}: expected HTTP {expected}, got {status}")
    if raw:
        return payload
    try:
        return json.loads(payload) if payload else None
    except ValueError:
        raise SmokeFailure(f"{method} {urlsplit(url).path}: expected JSON") from None


def eventually(check, description, timeout=30):
    deadline = time.monotonic() + timeout
    while True:
        try:
            result = check()
            if result:
                return result
        except SmokeFailure:
            pass
        if time.monotonic() >= deadline:
            raise SmokeFailure(f"Timed out waiting for {description}")
        time.sleep(1)


def run(urls, recipient="success@simulator.amazonses.com", frontend_url=None):
    run_id = uuid4().hex
    records = {"run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat(),
               "status": "RUNNING", "checks": []}
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    report = STATE_DIR / f"{run_id}.json"

    def passed(description):
        print(f"PASS {description}", flush=True)
        records["checks"].append(description)

    def api(service, path, method="GET", body=None, expected=200, raw=False):
        return request(method, urls[service].rstrip("/") + path, expected, body, raw=raw)

    try:
        for service in SERVICES:
            eventually(lambda s=service: api(s, "/health"), f"{service} health")
            eventually(lambda s=service: api(s, "/ready"), f"{service} readiness")
        passed("all seven services are healthy and ready")

        members = []
        for number in range(2):
            body = {"name": f"Smoke {number}", "email": f"smoke-{run_id}-{number}@example.com"}
            member = api("member", "/members", "POST", body, 201)
            members.append(member["member_id"])
            api("member", "/members", "POST", body, 409)
        records["member_ids"] = members
        member_path = f"/members/{members[0]}"
        api("member", member_path, "PATCH", {"name": "Smoke Updated"})
        require(api("member", member_path)["name"] == "Smoke Updated", "Member update was not persisted")
        require(bool(api("member", "/members?limit=1&offset=0")["items"]), "Member pagination empty")
        passed("member create/read/update/pagination and duplicate rejection")

        book = api("catalog", "/books", "POST", {"title": f"Smoke {run_id}", "author": "Deployment Test"}, 201)
        book_id = records["book_id"] = book["book_id"]
        book_path = f"/books/{book_id}"
        copy = api("catalog", book_path + "/copies", "POST", expected=201)
        copy_id = records["copy_id"] = copy["copy_id"]
        eventually(lambda: any(item["copy_id"] == copy_id for item in api("catalog", book_path + "/copies")["items"]), "DynamoDB copy index")
        api("catalog", "/books?limit=1")
        upload = api("catalog", book_path + "/cover/upload-url", "POST", {"content_type": "image/png"})
        request("PUT", upload["upload_url"], body=PNG, headers=upload["headers"], raw=True)
        records["cover_key"] = api("catalog", book_path + "/cover/confirm", "POST")["cover_key"]
        signed = api("catalog", book_path + "/cover-url")["url"]
        require(request("GET", signed, raw=True) == PNG, "Cover download differs from the upload")
        request("GET", signed.split("?", 1)[0], expected=403, raw=True)
        passed("catalog, copy index, signed cover upload/download and denied unsigned access")

        availability_path = book_path + "/availability"
        require(api("availability", availability_path)["available_copies"] == 1, "New copy must be available")
        reservations = [api("reservation", "/reservations", "POST", {"book_id": book_id, "member_id": person}, 201)
                        for person in members]
        records["reservation_ids"] = [item["reservation_id"] for item in reservations]
        require([item["status"] for item in reservations] == ["READY", "WAITLISTED"], "Reservation FIFO states are incorrect")
        require(api("availability", availability_path)["available_copies"] == 0, "Ready reservation did not hold its copy")
        api("reservation", "/reservations", "POST", {"book_id": book_id, "member_id": members[0]}, 409)
        passed("ready reservation, FIFO waiter, duplicate rejection and held availability")

        loan_body = {"member_id": members[0], "reservation_id": reservations[0]["reservation_id"], "copy_id": copy_id}
        loan = api("lending", "/loans", "POST", loan_body, 201)
        loan_id = records["loan_id"] = loan["loan_id"]
        loan_path = f"/loans/{loan_id}"
        require(api("lending", loan_path)["status"] == "ACTIVE", "Checkout was not persisted")
        require(api("availability", availability_path)["loaned_copies"] == 1, "Loan did not reduce availability")
        require(api("fine", loan_path + "/fine")["fine_amount_cents"] == 0, "A new loan must have no fine")
        returned = api("lending", loan_path + "/return", "POST")
        require(returned["status"] == "RETURNED", "Loan was not returned")
        api("lending", loan_path + "/return", "POST")
        promoted_path = f"/reservations/{reservations[1]['reservation_id']}"
        require(api("reservation", promoted_path)["status"] == "READY", "Next waiter was not promoted")
        api("reservation", promoted_path, "DELETE")
        require(api("availability", availability_path)["available_copies"] == 1, "Returned copy was not released")
        passed("checkout, active-loan availability, zero fine, idempotent return and FIFO promotion")

        receipt = api("notification", "/notifications", "POST", {
            "event_type": "LoanReturned", "recipient": recipient, "subject": f"Smoke {run_id}",
            "body": f"Deployment test {run_id} completed.", "member_id": members[0],
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }, 202)
        require(receipt["status"] == "QUEUED", "Notification was not queued")
        records["notification_id"] = receipt["notification_id"]
        passed("notification intake accepted the event (delivery checked separately in AWS mode)")
        for service in ("member", "catalog", "lending", "availability", "fine", "reservation", "notification"):
            require(b"_http_requests_total" in api(service, "/metrics", raw=True), f"{service} request metrics missing")
        passed("Prometheus metrics are exposed")
        if frontend_url:
            root = frontend_url.rstrip("/")
            require(b"<html" in request("GET", root + "/", raw=True).lower(), "Frontend HTML missing")
            request("GET", root + "/health")
            person = request("GET", root + f"/api/member/members/{members[0]}")
            require(person["member_id"] == members[0], "Frontend proxy routed to the wrong member")
            passed("frontend HTML, health and API proxy")
        records["status"] = "PASS"
        return records
    except Exception as error:
        records["status"] = "FAIL"
        records["error_type"] = type(error).__name__
        raise
    finally:
        records["finished_at"] = datetime.now(timezone.utc).isoformat()
        report.write_text(json.dumps(records, indent=2), encoding="utf-8")
        print(f"Report: {report}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for service, port in SERVICES.items():
        parser.add_argument(f"--{service}-url", default=f"http://127.0.0.1:{port}")
    parser.add_argument("--frontend-url")
    parser.add_argument("--notification-recipient", default="success@simulator.amazonses.com")
    args = parser.parse_args()
    try:
        run({name: getattr(args, name + "_url") for name in SERVICES}, args.notification_recipient, args.frontend_url)
    except (SmokeFailure, KeyError, ValueError) as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    print("All live API checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Bounded public AWS checkout/return and Lambda/SES duplicate audit.

Uses the SES success simulator only. Creates a labeled book/copy/hold/loan;
returns the loan and cancels the hold. Member/book/copy records remain.
Requires AWS CLI with the existing default profile and CloudWatch read access.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, uuid4, uuid5


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--profile", default="default")
    parser.add_argument("--region", default="ap-south-1")
    parser.add_argument("--report", default=".local/loan-notifications-verification.json")
    args = parser.parse_args()
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "requests": [], "assertions": [], "cleanup_warnings": []}
    start_ms = int(time.time() * 1000) - 5000
    run = uuid4().hex
    recipient = "success@simulator.amazonses.com"
    loan = hold = None

    def verify(name, condition):
        report["assertions"].append({"name": name, "passed": bool(condition)})
        if not condition:
            raise AssertionError(name)
        print("PASS " + name, flush=True)

    def api(route, path, method="GET", body=None, expected=200):
        data = json.dumps(body).encode() if body is not None else None
        request = Request(args.base_url.rstrip("/") + f"/api/{route}" + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=30) as response:
                status, content = response.status, response.read()
        except HTTPError as error:
            status, content = error.code, error.read()
        report["requests"].append({"method": method, "route": route, "path": path, "expected": expected, "actual": status})
        assert status == expected, f"{route} {method} {path}: expected {expected}, got {status}"
        return json.loads(content)

    def lambda_logs():
        command = ["aws", "logs", "filter-log-events", "--log-group-name", "/aws/lambda/digital-library-dev-notification", "--start-time", str(start_ms), "--profile", args.profile, "--region", args.region, "--output", "json", "--no-cli-pager"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=45, check=True)
        return json.loads(result.stdout)["events"]

    try:
        member = None
        offset = 0
        while member is None:
            page = api("member", f"/members?limit=100&offset={offset}")
            member = next((item for item in page["items"] if item["email"].lower() == recipient), None)
            offset += len(page["items"])
            if member is not None or len(page["items"]) < page["limit"]:
                break
        if member is None:
            member = api("member", "/members", "POST", {"name": "SES Simulator Notification Audit", "email": recipient}, 201)
        report["member_id"] = member["member_id"]
        report["recipient"] = recipient
        book = api("catalog", "/books", "POST", {"title": f"Loan notification audit {run}", "author": "AWS verification"}, 201)
        copy = api("catalog", f"/books/{book['book_id']}/copies", "POST", expected=201)
        deadline = time.monotonic() + 30
        while not api("catalog", f"/books/{book['book_id']}/copies")["items"]:
            assert time.monotonic() < deadline, "Copy GSI visibility timeout"
            time.sleep(1)
        hold = api("reservations", "/reservations", "POST", {"book_id": book["book_id"], "member_id": member["member_id"]}, 201)
        payload = {"member_id": member["member_id"], "reservation_id": hold["reservation_id"], "copy_id": copy["copy_id"]}
        loan = api("loans", "/loans", "POST", payload, 201)
        report["loan_id"] = loan["loan_id"]
        report["book_id"] = book["book_id"]
        verify("checkout succeeded with ACTIVE status", loan["status"] == "ACTIVE")
        api("loans", "/loans", "POST", payload, 409)
        with ThreadPoolExecutor(max_workers=4) as pool:
            returns = list(pool.map(lambda _: api("loans", f"/loans/{loan['loan_id']}/return", "POST"), range(4)))
        verify("four concurrent returns are idempotent", all(item["status"] == "RETURNED" for item in returns) and len({item["returned_at"] for item in returns}) == 1)
        verify("return releases reservation and copy", api("reservations", f"/reservations/{hold['reservation_id']}")["status"] == "CANCELLED" and api("availability", f"/books/{book['book_id']}/availability")["available_copies"] == 1)
        ids = {kind: str(uuid5(NAMESPACE_URL, f"digital-library/loans/{loan['loan_id']}/{kind}")) for kind in ("LoanIssued", "LoanReturned")}
        report["notification_ids"] = ids
        deadline = time.monotonic() + 90
        while True:
            events = lambda_logs()
            delivered = {kind: [event for event in events if "notification_delivered" in event["message"] and event_id in event["message"]] for kind, event_id in ids.items()}
            if all(delivered.values()):
                break
            assert time.monotonic() < deadline, "Automatic Lambda/SES delivery timeout"
            time.sleep(3)
        verify("automatic LoanIssued and LoanReturned reached SES without explicit POST", all(len(items) == 1 for items in delivered.values()))
        # Only after both automatic deliveries, replay their IDs to test deduplication.
        for kind, event_id in ids.items():
            timestamp = loan["checked_out_at"] if kind == "LoanIssued" else returns[0]["returned_at"]
            receipt = api("notifications", "/notifications", "POST", {"event_id": event_id, "event_type": kind, "recipient": recipient, "member_id": member["member_id"], "body": f"Duplicate audit for loan {loan['loan_id']}", "occurred_at": timestamp}, 202)
            verify(f"{kind} replay preserves stable notification ID", receipt["notification_id"] == event_id)
        deadline = time.monotonic() + 90
        while True:
            events = lambda_logs()
            duplicate = {kind: [event for event in events if "notification_duplicate" in event["message"] and event_id in event["message"]] for kind, event_id in ids.items()}
            if all(duplicate.values()):
                break
            assert time.monotonic() < deadline, "Lambda duplicate suppression timeout"
            time.sleep(3)
        for kind, event_id in ids.items():
            verify(f"{kind} delivered once; replay suppressed", sum("notification_delivered" in item["message"] and event_id in item["message"] for item in events) == 1)
        report["lambda_evidence"] = [event for event in events if any(event_id in event["message"] for event_id in ids.values())]
        report["status"] = "PASS"
    except Exception as error:
        report["status"] = "FAIL"
        report["failure"] = str(error)
        print("FAIL " + str(error), flush=True)
    finally:
        for route, path, method in ([('loans', f"/loans/{loan['loan_id']}/return", 'POST')] if loan else []) + ([('reservations', f"/reservations/{hold['reservation_id']}", 'DELETE')] if hold else []):
            try:
                api(route, path, method)
            except Exception as error:
                report["cleanup_warnings"].append(str(error))
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        output = Path(args.report)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"RESULT {report['status']}; {len(report['requests'])} HTTP requests; {len(report['assertions'])} assertions", flush=True)
    return 0 if report["status"] == "PASS" and not report["cleanup_warnings"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

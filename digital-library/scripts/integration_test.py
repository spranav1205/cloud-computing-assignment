"""Exercise both Compose APIs; --verify checks the same records after a restart."""

import argparse
import base64
import json
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

import httpx

STATE_FILE = Path(__file__).resolve().parents[1] / ".local" / "integration.json"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1sAAAAASUVORK5CYII=")


def verify_records(member, catalog, records):
    assert member.get("/ready").status_code == 200
    assert catalog.get("/ready").status_code == 200
    person = member.get(records["member_path"])
    assert person.status_code == 200 and person.json()["name"] == "Integration Updated"
    book = catalog.get(records["book_path"])
    assert book.status_code == 200 and book.json()["cover_key"] == records["cover_key"]
    deadline = monotonic() + 5
    while True:
        copies = catalog.get(records["book_path"] + "/copies")
        assert copies.status_code == 200
        if records["copy"] in copies.json()["items"]:
            break
        assert monotonic() < deadline, "Copy did not appear in the GSI"
        sleep(0.1)
    download = catalog.get(records["book_path"] + "/cover-url")
    assert download.status_code == 200
    image = catalog.get(download.json()["url"])
    assert image.status_code == 200 and image.content == PNG
    assert catalog.get(download.json()["url"].split("?")[0]).status_code == 403
    for client in (member, catalog):
        assert client.get("/metrics").status_code == 200


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", help="Recheck saved records after restarting APIs")
    args = parser.parse_args()
    with httpx.Client(base_url="http://127.0.0.1:8001", trust_env=False, timeout=10) as member, \
         httpx.Client(base_url="http://127.0.0.1:8002", trust_env=False, timeout=10) as catalog:
        if args.verify:
            verify_records(member, catalog, json.loads(STATE_FILE.read_text()))
            print("Integration persistence check passed for the saved member, book, copy, and cover.")
            return
        body = {"name": "Integration Member", "email": f"integration-{uuid4().hex}@example.com"}
        created = member.post("/members", json=body)
        assert created.status_code == 201
        member_path = created.headers["location"]
        assert member.get(member_path).status_code == 200
        assert member.patch(member_path, json={"name": "Integration Updated"}).status_code == 200
        assert member.post("/members", json=body).status_code == 409
        assert member.get("/members", params={"limit": 1, "offset": 0}).status_code == 200
        created = catalog.post("/books", json={"title": "Integration Book", "author": "Local Author"})
        assert created.status_code == 201
        book_path = created.headers["location"]
        assert catalog.get("/books", params={"limit": 1}).status_code == 200
        copy = catalog.post(book_path + "/copies")
        assert copy.status_code == 201
        upload = catalog.post(book_path + "/cover/upload-url", json={"content_type": "image/png"})
        assert upload.status_code == 200
        signed = upload.json()
        assert catalog.put(signed["upload_url"], content=PNG, headers=signed["headers"]).status_code == 200
        confirmed = catalog.post(book_path + "/cover/confirm")
        assert confirmed.status_code == 200
        records = {"member_path": member_path, "book_path": book_path, "copy": copy.json(),
                   "cover_key": confirmed.json()["cover_key"]}
        verify_records(member, catalog, records)
        STATE_FILE.parent.mkdir(exist_ok=True)
        STATE_FILE.write_text(json.dumps(records, indent=2))
        print("Full local integration passed: member CRUD/paging/duplicate, book/copy, private cover upload/download, probes/metrics.")


if __name__ == "__main__":
    main()

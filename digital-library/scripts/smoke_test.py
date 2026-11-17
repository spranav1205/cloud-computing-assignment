"""HTTP smoke checks against running local APIs; leaves sample records for review."""
import argparse
from uuid import uuid4

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("service", choices=["member", "catalog"])
args = parser.parse_args()
port = 8001 if args.service == "member" else 8002
with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10, trust_env=False) as client:
    assert client.get("/ready").status_code == 200
    if args.service == "member":
        body = {"name": "Smoke Member", "email": f"smoke-{uuid4().hex}@example.com"}
        created = client.post("/members", json=body)
        assert created.status_code == 201, created.text
        path = created.headers["location"]
        assert client.get(path).json()["email"] == body["email"]
        assert client.patch(path, json={"name": "Updated Member"}).json()["name"] == "Updated Member"
        page = client.get("/members", params={"limit": 1, "offset": 0})
        assert page.status_code == 200 and len(page.json()["items"]) == 1
        assert client.post("/members", json=body).status_code == 409
        print("Member smoke passed: create 201, read/update/list 200, duplicate 409.")
    else:
        created = client.post("/books", json={"title": "Smoke Book", "author": "Local Author"})
        assert created.status_code == 201, created.text
        path = created.headers["location"]
        assert client.get(path).json()["title"] == "Smoke Book"
        assert client.get("/books", params={"limit": 1}).status_code == 200
        copy = client.post(f"{path}/copies")
        assert copy.status_code == 201, copy.text
        copies = client.get(f"{path}/copies")
        assert copies.status_code == 200 and copy.json() in copies.json()["items"]
        print("Catalog smoke passed: create book/copy 201, fetch/list 200.")

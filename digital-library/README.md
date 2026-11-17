# Digital Library: Member and Catalog checkpoints

Checkpoints 2 and 3 implement Member and Catalog books/copies. Covers, full Compose
integration, Terraform, Dockerfiles, and Kubernetes remain for later checkpoints.
No AWS credentials, AWS calls, or cloud resources are needed for these steps.

Member uses FastAPI, SQLAlchemy, and PostgreSQL. Routes and HTTP handling are in
`services/member/app/main.py`, validation and the table model are in `models.py`,
and queries are in `database.py`. Email is trimmed, validated, and lowercased.
PostgreSQL's named unique constraint enforces email identity; violations return 409.
IDs are generated server-side and creation times use UTC. Listing uses limit/offset.

The revised minimal design permits simple initialization instead of Alembic.
`init_db.py` creates the local table explicitly, preserving an existing table. It
does not migrate an existing schema. Schema changes will need an explicit migration
if the model changes later. API startup never creates tables.

## Local setup (PowerShell)

Prerequisites: Python 3.12+ and Docker Desktop with a running Linux-container engine.
Run these from the repository root. The PostgreSQL password below is a local example.
The port is bound to loopback only. The named volume preserves local records.

```powershell
docker compose -f .\digital-library\compose.yaml up -d --wait postgres dynamodb
docker compose -f .\digital-library\compose.yaml exec -T postgres pg_isready -U library -d library
```

Compose reuses its existing containers and PostgreSQL volume. These commands
replace the previous standalone `docker run` instructions. If you previously made
a standalone container occupying port 5432, stop it before starting Compose.

```powershell
Set-Location .\digital-library\services\member
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:DATABASE_URL = 'postgresql+psycopg://library:local-password@127.0.0.1:5432/library'
.\.venv\Scripts\python.exe init_db.py
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8001
```

Keep that terminal running. Open http://127.0.0.1:8001/docs for interactive OpenAPI
documentation, or use these commands in a second PowerShell terminal:

```powershell
$base = 'http://127.0.0.1:8001'
Invoke-RestMethod "$base/health"
Invoke-RestMethod "$base/ready"
$memberBody = @{name = 'Ada Lovelace'; email = 'ada@example.com'} | ConvertTo-Json
$member = Invoke-RestMethod "$base/members" -Method Post -ContentType 'application/json' -Body $memberBody
$member
Invoke-RestMethod "$base/members/$($member.member_id)"
Invoke-RestMethod "$base/members?limit=2&offset=0"
$patchBody = @{name = 'Ada Byron'} | ConvertTo-Json
Invoke-RestMethod "$base/members/$($member.member_id)" -Method Patch -ContentType 'application/json' -Body $patchBody
curl.exe -i http://127.0.0.1:8001/metrics
```

The create returns 201 with a Location header; fetch/list/update return 200. Repeat
the create to see 409. Invalid email or empty name returns 422. A valid but unknown
UUID returns 404. An empty PATCH or explicit null is rejected. IDs and timestamps
cannot be edited. `/health` remains independent of the database; `/ready` checks
database connectivity and returns 503 if it is unavailable. Missing schema is a
setup error: run the initialization command before trying member operations.

Optional curl checks (the interactive docs are convenient for JSON bodies on Windows):

```powershell
curl.exe -i 'http://127.0.0.1:8001/members?limit=2&offset=0'
curl.exe -i http://127.0.0.1:8001/members/00000000-0000-0000-0000-000000000000
```

## Automated tests

From `digital-library/services/member`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The default run uses SQLite as a lightweight HTTP/database test double. It verifies
create/read/update, paging, validation, missing records, metrics, and an injected
database outage. It does **not** establish PostgreSQL-specific correctness.
The PostgreSQL test skips unless explicitly configured. To run it locally:

```powershell
docker compose -f ..\..\compose.yaml exec -T postgres createdb -U library member_test
$env:TEST_DATABASE_URL = 'postgresql+psycopg://library:local-password@127.0.0.1:5432/member_test'
.\.venv\Scripts\python.exe -m pytest -q -m integration
```

Run `createdb` only once. Integration tests accept only loopback hosts and the
dedicated database name `member_test`. They clear its members table before/after
the test: do not store demonstration data there. They verify PostgreSQL persistence,
UTC timestamps, normalized duplicate emails on create/update, and rollback after
a rejected update. Never point the tests at RDS or use actual AWS credentials.

To check persistence manually, restart the API and fetch the previously created
member ID. You can restart the Compose `postgres` service as well; its named volume persists.
From `digital-library`, use `docker compose stop` to stop the local databases.

## Verification recorded for this checkpoint

On this workstation (Python 3.15), **20 Member tests passed with no skips**, including
the real PostgreSQL integration test. Schema initialization and the live HTTP smoke
test passed: create 201, read/update/pagination 200, duplicate email 409. PostgreSQL
runs in the local Compose container with dummy development credentials.

Metrics use route templates rather than member IDs, and application logs go to
stdout. No monitoring stack or authentication system is included. No other service
owns or modifies Member's records directly.

## Catalog (checkpoint 3)

Catalog implements book creation/listing/lookup and copy creation/listing. It owns
identities only, with no reservation, loan, or availability logic. `app/models.py`
validates text/optional ISBN format; `app/database.py` contains DynamoDB operations;
`app/main.py` provides HTTP routes, metrics, probes, and error handling. IDs are
server-generated UUIDs and inserts use conditional writes. Books have UTC creation
timestamps. ISBN metadata is not unique and has no check-digit validation.

From the repository root, with Compose already started:

```powershell
Set-Location .\digital-library\services\catalog
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:DYNAMODB_ENDPOINT_URL = 'http://127.0.0.1:8000'
.\.venv\Scripts\python.exe init_db.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8002
```

The initializer creates `Books` and `Copies`, with a `book_id-index` GSI on Copies.
It reuses tables that exist. SDK credentials are explicitly dummy; only loopback or
the Compose `dynamodb` host is accepted. There is no AWS mode in this checkpoint.
Tests use isolated temporary tables on DynamoDB Local and delete only those tables
afterward. If DynamoDB Local is unavailable, the tests fail instead of skipping.

In another terminal:

```powershell
$base = 'http://127.0.0.1:8002'
Invoke-RestMethod "$base/ready"
$body = @{title = 'The C Programming Language'; author = 'Kernighan and Ritchie'; isbn = '9780131103627'} | ConvertTo-Json
$book = Invoke-RestMethod "$base/books" -Method Post -ContentType 'application/json' -Body $body
Invoke-RestMethod "$base/books/$($book.book_id)"
Invoke-RestMethod "$base/books?limit=2"
Invoke-RestMethod "$base/books/$($book.book_id)/copies" -Method Post
Invoke-RestMethod "$base/books/$($book.book_id)/copies"
```

List responses contain `items` and `last_evaluated_key`. Send a non-null returned
key as URL-encoded JSON using the `last_evaluated_key` query parameter for the next
page. Book lists use native Scan pagination with no guaranteed order or search.
Copy lists use the GSI Query and can briefly lag writes. The create response gives
the new copy identity immediately. There are no search engines or additional stores.

The minimal Compose DynamoDB service is in-memory: data survives API restarts but
is lost when the DynamoDB container restarts. PostgreSQL uses a persistent named
volume. Do not use `docker compose down -v` if you want to retain Member data.

**Verification:** 16 Catalog tests passed with no skips, covering real DynamoDB
book/copy persistence and pagination, validation, missing records, probe/metrics
endpoints, and a simulated storage outage. The live Catalog HTTP smoke test passed.
Both suites emit a non-failing upstream Starlette/httpx deprecation warning.
Full API-container Compose integration remains checkpoint 5; these API processes
run locally against containerized databases. Covers remain checkpoint 4.

## Repeatable live smoke tests

With both APIs running, from `digital-library`:

```powershell
.\services\member\.venv\Scripts\python.exe scripts/smoke_test.py member
.\services\catalog\.venv\Scripts\python.exe scripts/smoke_test.py catalog
```

These scripts exercise actual HTTP endpoints and leave uniquely identified sample
records for manual review. API docs are at http://127.0.0.1:8001/docs and
http://127.0.0.1:8002/docs. No AWS operations were performed.

# Digital Library: Member and Catalog checkpoints

Checkpoints 2-5 implement Member, Catalog books/copies, private book covers, and
full local Docker Compose integration. Checkpoint 6 adds Terraform definitions
with offline validation only; see [infra/README.md](infra/README.md) for resources,
security decisions, costs, test commands, and team integration outputs.
Checkpoint 7 adds deployment Dockerfiles, locally verified packaged images, and
schema-validated Kubernetes manifests; see [k8s/README.md](k8s/README.md) for exact
commands and the Member 3 GitOps handoff. No cloud deployment has occurred.
No AWS credentials, AWS calls, or cloud resources are needed for these steps.

AWS testing is being prepared separately in [AWS_TESTING.md](AWS_TESTING.md).
Start with its user-run read-only checks; a real plan/apply has not been executed.

Member uses FastAPI, SQLAlchemy, and PostgreSQL. Routes and HTTP handling are in
`services/member/app/main.py`, validation and the table model are in `models.py`,
and queries are in `database.py`. Email is trimmed, validated, and lowercased.
PostgreSQL's named unique constraint enforces email identity; violations return 409.
IDs are generated server-side and creation times use UTC. Listing uses limit/offset.

The revised minimal design permits simple initialization instead of Alembic.
`init_db.py` creates the local table explicitly, preserving an existing table. It
does not migrate an existing schema. Schema changes will need an explicit migration
if the model changes later. API startup never creates tables.

## Start the full local stack (checkpoint 5)

From the repository root, with Docker Desktop running:

```powershell
Set-Location .\digital-library
docker compose up --build -d --wait --wait-timeout 600
docker compose ps
```

This runs both APIs, PostgreSQL, DynamoDB Local, and MinIO. One-shot initialization
jobs install the development dependencies into named Python environment volumes,
initialize the Member table and Catalog tables, and configure private cover storage.
The APIs start only after their initialization jobs succeed. The first run needs
internet access to download images/dependencies and build the approved MinIO
sources; subsequent starts reuse Docker caches. No AWS access is needed.

API code is mounted read-only into standard Python 3.12 development containers.
Production service Dockerfiles remain checkpoint 7. Stop any manually started API
processes on ports 8001/8002 before starting Compose. Initialization jobs exiting
with status 0 is expected. To inspect problems, run `docker compose logs member-init
catalog-init minio-init member catalog`.

Open http://127.0.0.1:8001/docs for Member or http://127.0.0.1:8002/docs for Catalog.
Readiness checks are at `/ready`; liveness checks are at `/health`. All published
ports bind to loopback. Catalog uses `http://minio:9000` internally and signs URLs
for `http://127.0.0.1:9000`, which the host can reach. Signed URLs cannot be changed
after signing. Override neither host with a real AWS endpoint.

### Tests and integration verification

From `digital-library`, create the dedicated test database once (it may already
exist from checkpoint 2):

```powershell
docker compose exec -T postgres createdb -U library member_test
docker compose exec -T -e TEST_DATABASE_URL=postgresql+psycopg://library:local-password@postgres:5432/member_test member /venv/bin/python -m pytest -q -p no:cacheprovider
docker compose exec -T -e S3_PUBLIC_ENDPOINT_URL=http://minio:9000 catalog /venv/bin/python -m pytest -q -p no:cacheprovider
```

The Catalog test override signs URLs reachable inside the container running the
tests. It does not change the running API's host-facing URLs. The Member integration
test only accepts loopback or the Compose `postgres` host and the dedicated
`member_test` database; it clears that database's members table, not demonstration
records in `library`.

To verify the entire stack from the host, install the small smoke-test dependency
in a local virtual environment if the Catalog environment does not already exist:

```powershell
python -m venv services/catalog/.venv
./services/catalog/.venv/Scripts/python.exe -m pip install -r services/catalog/requirements-dev.txt
./services/catalog/.venv/Scripts/python.exe scripts/integration_test.py
docker compose restart member catalog
docker compose up -d --wait --no-deps member catalog
./services/catalog/.venv/Scripts/python.exe scripts/integration_test.py --verify
```

The integration script creates a member, reads/updates it, checks pagination and
duplicate-email rejection, creates a book/copy, uploads and confirms a cover, and
checks signed download, private access, metrics, and readiness. The two services
remain independent; it does not invent a reservation or loan linking them. It saves
only test resource identifiers in ignored `.local/integration.json` for verification
after API restarts. It leaves sample records for manual inspection.

For a manual recovery check, run `docker compose stop postgres`, then use
`curl.exe -i http://127.0.0.1:8001/ready` (503), `/health` (200), and Catalog's
`/ready` on port 8002 (200). Restore with `docker compose up -d --wait postgres`
and run the integration script with `--verify` again. Use `docker compose stop`
to stop the full stack without removing its volumes. DynamoDB Local remains
in-memory: API restarts retain records, but restarting its container loses books
and copies. PostgreSQL and MinIO use persistent volumes. Do not use `down -v` to
retain that data.

**Checkpoint 5 verification:** all 48 service tests passed inside the Python 3.12
Compose containers (20 Member, 28 Catalog), with zero skips. The complete host-to-
container integration workflow passed, as did verification of the same records
after restarting both API containers. A real local PostgreSQL outage produced
Member readiness 503, Member health 200, and Catalog readiness 200. After restoring
PostgreSQL, the saved-record verification passed again. Both API containers are
healthy. The existing non-failing Starlette/httpx deprecation warning remains.

AWS testing is checkpoint 8, after checkpoint 6's offline Terraform checks and
checkpoint 7's packaging/GitOps preparation. Before any real-account plan or cloud
operation, review the proposed resources, region, sizing, and expected costs and
obtain explicit approval for that particular operation. Nothing in this local
checkpoint authorizes AWS access, deployment, scaling, or teardown.

## Optional host-process setup (PowerShell)

These earlier checkpoint commands are useful for debugging one API on the host.
Do not run a host API and its Compose API on the same port at the same time.

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

Run `createdb` only once. Integration tests accept only local/Compose hosts and the
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

**Checkpoint 3 verification:** 16 Catalog tests passed with no skips, covering real DynamoDB
book/copy persistence and pagination, validation, missing records, probe/metrics
endpoints, and a simulated storage outage. The live Catalog HTTP smoke test passed.
Both suites emit a non-failing upstream Starlette/httpx deprecation warning.
The commands in this section run host API processes for debugging. The default
full-stack workflow at the top of this document runs the APIs in Compose.

## Book covers (checkpoint 4)

From `digital-library`, build and initialize private local MinIO:

```powershell
docker compose build minio minio-init
docker compose up -d minio
docker compose run --rm minio-init
```

The official MinIO image pulls were unavailable on this workstation. With explicit
approval, the Dockerfile under `scripts/minio` builds the server and client from
pinned commits in the official [MinIO](https://github.com/minio/minio) and
[MinIO client](https://github.com/minio/mc) repositories. The first build downloads
Go dependencies and takes longer than pulling an image; later builds use Docker's
cache. These are local dependency images, not the service packaging checkpoint.

The initializer creates `library-covers`, disables anonymous access, and creates
a dummy development user with only bucket-metadata access and GetObject/PutObject
on `covers/*` (see `scripts/minio-policy.json`). Catalog uses that restricted user,
not the MinIO administrator. Root credentials in Compose are dummy local values.
Ports are loopback-only. MinIO persists objects in the `minio-data` named volume.
The initializer is safe to rerun with this configuration.

Restart Catalog after pulling these code changes. From `services/catalog`:

```powershell
$env:S3_ENDPOINT_URL = 'http://127.0.0.1:9000'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8002
```

Readiness now checks MinIO as well as both DynamoDB tables, so initialize MinIO
before running the Catalog suite or requesting `/ready`. No test skips unavailable
local storage. The SDK rejects nonlocal S3 endpoints and uses only explicit dummy
credentials. Use the default loopback endpoint for signed URLs consumed on the host.

Manual upload in a second PowerShell terminal (replace the image path):

```powershell
$base = 'http://127.0.0.1:8002'
$book = Invoke-RestMethod "$base/books" -Method Post -ContentType 'application/json' -Body '{"title":"Cover example","author":"Local Author"}'
$path = "$base/books/$($book.book_id)"
$upload = Invoke-RestMethod "$path/cover/upload-url" -Method Post -ContentType 'application/json' -Body '{"content_type":"image/png"}'
curl.exe --fail --request PUT --header 'Content-Type: image/png' --upload-file 'C:\path\to\cover.png' $upload.upload_url
Invoke-RestMethod "$path/cover/confirm" -Method Post
$download = Invoke-RestMethod "$path/cover-url"
curl.exe --fail --output downloaded-cover.png $download.url
```

For JPEG, request `image/jpeg` and upload with that same header. URLs expire after
300 seconds. The upload endpoint chooses a new UUID key and stores one internal
`pending_cover_key` on the book. Confirmation accepts no key; it checks that pending
object with HEAD and saves only its key as `cover_key`. New upload requests replace
the pending key; a confirmed cover remains accessible until its replacement is
confirmed. Missing uploaded object/cover/book returns 404; no pending upload returns
409; unsupported content type, zero size, or size over **5,000,000 bytes** returns 422.

This is the agreed simple workflow: declared MIME type is checked without decoding
the image. Oversized uploads can reach MinIO but cannot be confirmed. A signed PUT
can be reused until expiry; there is no staging, object copy, concurrency handling,
or automatic cleanup. Unconfirmed/replaced covers and test objects remain in this
local bucket. S3 upload keys cannot be supplied through the public API; public book
responses never expose the pending key or persist a signed URL.

The cover smoke script performs a real tiny-PNG upload, confirmation, download,
and denial of an unsigned download. From `digital-library`:

```powershell
.\services\catalog\.venv\Scripts\python.exe scripts/smoke_test.py covers
```

**Checkpoint 4 verification:** the official-source MinIO server/client images built
successfully and initialization created the private bucket and restricted user.
All **28 Catalog tests passed with zero skips**, including actual presigned HTTP
uploads/downloads, private access, size/type validation, missing objects, rejection
of client-supplied keys, restricted object permissions, and MinIO readiness failure.
The live cover and book/copy smoke scripts passed. The Member regression suite also
passed all **20 tests**, including PostgreSQL integration. Compilation and dependency
checks passed. The existing non-failing Starlette/httpx warning remains. No AWS
credentials or AWS endpoints were used.

## Repeatable live smoke tests

With both APIs running, from `digital-library`:

```powershell
.\services\member\.venv\Scripts\python.exe scripts/smoke_test.py member
.\services\catalog\.venv\Scripts\python.exe scripts/smoke_test.py catalog
```

These scripts exercise actual HTTP endpoints and leave uniquely identified sample
records for manual review. API docs are at http://127.0.0.1:8001/docs and
http://127.0.0.1:8002/docs. No AWS operations were performed.

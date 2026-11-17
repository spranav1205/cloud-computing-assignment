# Digital Library Microservices

Member manages member identities in PostgreSQL. Catalog manages books and copy
identities in DynamoDB and private cover images in S3-compatible storage. Both
expose REST APIs, OpenAPI docs, `/health`, `/ready`, `/metrics`, and stdout logs.
Neither service manages reservations, loans, fines, or availability.

Shantnu's services are included as separate components: Fine Calculation reads
the Lending service's loan records and Usage Analytics processes Kafka events
with a Flink job. See [Usage Analytics](services/usage-analytics/README.md) for
the event contract and EMR submission steps.

Implementation and packaging were tested locally. The user-generated saved AWS
plan has been inspected, but the agent has not provisioned resources. See
[AWS testing](AWS_TESTING.md) before considering an apply.

| Document | Purpose |
| --- | --- |
| [Design](DESIGN.md) | Agreed minimal scope and ownership |
| [Infrastructure](infra/README.md) | Terraform resources, security, costs, offline checks |
| [Packaging and GitOps](k8s/README.md) | Image builds, manifest validation, Member 3 handoff |
| [AWS testing](AWS_TESTING.md) | Cloud plan review and $20 testing/$20 demo allocation |

## Start locally

Prerequisites: Docker Desktop with Linux containers. Python 3.12+ is needed only
for host-side tests/debugging. From the repository root:

```powershell
Set-Location .\digital-library
docker compose up --build -d --wait --wait-timeout 600
docker compose ps
```

This starts the Member, Catalog, Reservation, Fine Calculation, and Notification APIs, PostgreSQL,
DynamoDB Local, and MinIO. Separate initialization
jobs install development dependencies into named Python volumes, initialize tables,
and configure a private cover bucket and restricted MinIO user. Exit code 0 for
these jobs is expected. API startup itself does not create tables. Initialization
preserves existing tables but does not migrate an existing schema.

The first run downloads public images/dependencies and builds MinIO from approved,
pinned official sources. Subsequent runs reuse Docker caches. No AWS credentials
are needed: local SDK clients use dummy credentials and reject remote emulator
endpoints. Published ports bind to loopback. Stop host API processes on ports
8001/8002 before starting their Compose replacements.

| Service | Local address |
| --- | --- |
| Member API / docs | http://127.0.0.1:8001/docs |
| Catalog API / docs | http://127.0.0.1:8002/docs |
| Reservation API / docs | http://127.0.0.1:8003/docs |
| Notification API / docs | http://127.0.0.1:8004/docs |
| Fine Calculation API / docs | http://127.0.0.1:8005/docs |
| PostgreSQL | 127.0.0.1:5432 |
| DynamoDB Local | http://127.0.0.1:8000 |
| MinIO S3 / console | http://127.0.0.1:9000 / http://127.0.0.1:9001 |

For startup problems, inspect `docker compose logs member-init catalog-init minio-init member catalog reservation notification`.
To use packaged non-root images with read-only filesystems and no source mounts:

```powershell
docker compose -f compose.yaml -f compose.packaged.yaml up --build -d --wait --wait-timeout 600 member catalog
```

Use `docker compose stop` to stop local containers without removing volumes.
PostgreSQL and MinIO persist data in named volumes. DynamoDB Local is in-memory:
API restarts preserve records, but restarting its container loses books/copies.
Avoid `docker compose down -v` if you want to retain volume data.

Reservation uses PostgreSQL and an in-process lock by default. Set
`ZOOKEEPER_HOSTS` in the Compose environment when running the distributed-lock
demo. Notification uses an in-memory queue locally; set `NOTIFICATION_QUEUE_URL`
and `AWS_REGION` only when connecting it to an approved SQS queue.
Fine Calculation reads the `loans` table without creating or migrating it; it
returns 404 until a Lending service has created the requested loan. Its default
rate is 100 cents per overdue day and can be changed with `FINE_PER_DAY_CENTS`.

## Tests

Use the default development Compose setup for tests. Create the dedicated
PostgreSQL test database once (omit `createdb` if it already exists):

```powershell
docker compose up -d --wait member catalog
docker compose exec -T postgres createdb -U library member_test
docker compose exec -T -e TEST_DATABASE_URL=postgresql+psycopg://library:local-password@postgres:5432/member_test member /venv/bin/python -m pytest -q -p no:cacheprovider
docker compose exec -T -e S3_PUBLIC_ENDPOINT_URL=http://minio:9000 catalog /venv/bin/python -m pytest -q -p no:cacheprovider
```

Member tests cover HTTP behavior and actual PostgreSQL uniqueness/rollback. They
clear only the test database's members table, not demonstration records in `library`.
The PostgreSQL integration test skips if its explicit URL is omitted. Catalog
tests require DynamoDB Local and MinIO, create/delete isolated test tables, and
never skip missing storage. Cover test objects remain locally. Cloud configuration
tests mock SDK factories without AWS calls.

One integration script covers the complete member/book/copy/cover workflow:

```powershell
python -m venv services/catalog/.venv
./services/catalog/.venv/Scripts/python.exe -m pip install -r services/catalog/requirements-dev.txt
./services/catalog/.venv/Scripts/python.exe scripts/integration_test.py
```

It checks create/read/update/pagination, duplicate-email rejection, book/copy
identities, signed uploads, confirmation/download, private access, readiness, and
metrics. It leaves sample records and stores identifiers in ignored
`.local/integration.json`. Recheck the same records after API restarts:

```powershell
docker compose restart member catalog
docker compose up -d --wait --no-deps member catalog
./services/catalog/.venv/Scripts/python.exe scripts/integration_test.py --verify
```

For packaged containers, use both Compose files in those Docker commands. To test
recovery, stop local PostgreSQL: Member `/ready` returns 503 while `/health` remains
200; Catalog stays ready. Restore with `docker compose up -d --wait postgres` and
rerun `--verify`.

## REST contracts and manual checks

Member supports `POST /members`, `GET /members?limit=20&offset=0`,
`GET /members/{id}`, and `PATCH /members/{id}`. It generates UUIDs and UTC timestamps,
normalizes email to lowercase, and relies on PostgreSQL's unique constraint.
Invalid input/empty or null updates return 422, missing members 404, and duplicate
emails 409. Limits range from 1 to 100; offsets must be nonnegative.

Catalog supports `POST /books`, `GET /books`, `GET /books/{id}`,
`POST /books/{id}/copies`, and `GET /books/{id}/copies`. ISBN is optional metadata
with basic format validation. Book lists use Scan with no guaranteed order or
search; copy lists use an eventually consistent GSI Query. Lists return `items`
and `last_evaluated_key`; send a non-null key as URL-encoded JSON in the same query
parameter to fetch the next page.

Reservation supports `POST /reservations`, `GET /reservations/{id}`, and
`DELETE /reservations/{id}`. The first active reservation for a book is `READY`;
later requests are FIFO `WAITLISTED`. Cancelling a ready reservation promotes the
oldest waiter while a per-book coordinator prevents concurrent allocation. Local
mode uses an in-process lock; set `ZOOKEEPER_HOSTS` to use ZooKeeper locks.

Fine Calculation supports `GET /loans/{id}/fine`. It assesses the loan through
its return timestamp, or the current UTC time if it remains open. Any partial
overdue day is charged as a full day. The response expresses money in integer
cents and includes the rate and overdue-day count.

Notification supports `POST /notifications` for reservation, availability, due-date,
and return events. Without `NOTIFICATION_QUEUE_URL`, local mode queues in memory;
with that variable it publishes to SQS. The worker consumes SQS messages and logs
delivery to stdout, leaving email/SMS integration to the notification provider.

Use `/docs` for interactive requests, or run these PowerShell examples:

```powershell
$member = Invoke-RestMethod 'http://127.0.0.1:8001/members' -Method Post -ContentType 'application/json' -Body '{"name":"Ada Lovelace","email":"ada@example.com"}'
Invoke-RestMethod "http://127.0.0.1:8001/members/$($member.member_id)"
Invoke-RestMethod 'http://127.0.0.1:8001/members?limit=2&offset=0'
Invoke-RestMethod "http://127.0.0.1:8001/members/$($member.member_id)" -Method Patch -ContentType 'application/json' -Body '{"name":"Ada Byron"}'
$book = Invoke-RestMethod 'http://127.0.0.1:8002/books' -Method Post -ContentType 'application/json' -Body '{"title":"Example Book","author":"Example Author"}'
Invoke-RestMethod "http://127.0.0.1:8002/books/$($book.book_id)/copies" -Method Post
```

For a cover, replace the image path and use that book:

```powershell
$path = "http://127.0.0.1:8002/books/$($book.book_id)"
$upload = Invoke-RestMethod "$path/cover/upload-url" -Method Post -ContentType 'application/json' -Body '{"content_type":"image/png"}'
curl.exe --fail --request PUT --header 'Content-Type: image/png' --upload-file 'C:\path\to\cover.png' $upload.upload_url
Invoke-RestMethod "$path/cover/confirm" -Method Post
$download = Invoke-RestMethod "$path/cover-url"
curl.exe --fail --output downloaded-cover.png $download.url
```

JPEG uploads use `image/jpeg` for both request and upload headers. URLs last
300 seconds. The server stores one internal pending key per book; confirmation
accepts no client key. It checks existence, declared MIME type, and actual length
of 1-5,000,000 bytes. Oversized objects can reach storage but cannot be confirmed.
Images are not decoded. There is no staging, copying, concurrency framework, or
automatic cleanup. Old/unconfirmed covers remain stored.

## Verification and cloud deployment

The existing Member/Catalog checkpoint recorded **55 service tests**, **5 offline
Terraform tests**, and packaged-image integration. For Shantnu's services,
**5 Fine tests**, **2 Flink tests**, strict validation of **16 Kubernetes
resources**, and Docker Compose configuration validation passed. The Flink job
builds as a shaded jar; a live Kafka/EMR run has not been performed and no cloud
resources were provisioned. Real EKS/IRSA/RDS connectivity and GitOps
reconciliation remain unverified.

AWS mode is explicit (`APP_ENV=aws`); local mode is the default. Cloud prerequisites,
image publication, RDS TLS/Secret delivery, and Member 3's GitOps handoff are in
[k8s/README.md](k8s/README.md). Provisioning, scaling, and teardown each require
separate approval. Preserve the $20 demo reserve; a saved plan is not deployment
approval.

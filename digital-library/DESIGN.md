# Digital Library: Microservices Design

This document records the agreed service boundaries and implementation notes.
The current task division assigns Member and Catalog to Pranav; Reservation and
Notification to Nishant; Lending and Availability to Neha; and Usage Analytics
and Fine Calculation to Shantnu. This implementation includes all assigned
service deliverables.

## Scope

Member and Catalog remain scoped to their assigned services and infrastructure.
Lending owns the authoritative `loans` table and coordinates checkout/return
with Member, Catalog, and Reservation APIs. Availability is a read-only
projection of Catalog copies, active loans, and ready reservations. Usage
Analytics consumes lending/reservation events, while Fine Calculation reads
Lending's `loans` table. Neither of those services owns loan, reservation, or
catalog records.

Where the starter design conflicts with the agreed task division, use the current assignment: **Member records in PostgreSQL; books and copies in DynamoDB; covers in S3**. Other services access these through APIs.

## Stack and structure

- Python + FastAPI for Member, Catalog, Reservation, Lending, Availability,
  Notification, and Fine Calculation. Usage Analytics is a Java 17 Flink job
  with a Kafka connector.
- PostgreSQL for members, reservations, and loans (SQLAlchemy is sufficient).
- DynamoDB for books and copies (boto3).
- S3 for book-cover objects; MinIO for local testing.
- Terraform for assigned AWS resources; Docker and Kubernetes for deployment.
- Local development with Docker Compose: PostgreSQL, DynamoDB Local, MinIO, and
  the HTTP APIs. Usage Analytics is submitted separately to the managed Flink
  cluster; see its [job guide](services/usage-analytics/README.md).

## Shantnu's service contracts

- **Fine Calculation:** `GET /loans/{id}/fine` reads `loan_id`, `due_at`, and
  `returned_at` from the Lending-owned `loans` table. It does not create or
  migrate that table. The daily rate defaults to 100 cents and is configurable.
- **Usage Analytics:** consumes reservation and loan events from Kafka and
  publishes per-book one-minute event-time aggregates to a separate results
  topic. Its event and output schemas are in the
  [job guide](services/usage-analytics/README.md).

## Neha's service contracts

- **Lending:** `POST /loans` checks that the reservation is READY and belongs to
  the member, verifies the member and that the copy belongs to the reserved
  book, then records an active loan with a configurable due date. `GET /loans`
  and `GET /loans/{id}` expose loan records. `POST /loans/{id}/return` records
  the return time and cancels the reservation, allowing Reservation to promote
  the next waiter. The default loan period is 14 days.
- **Availability:** `GET /books/{id}/availability` obtains copy identities from
  Catalog and reads active loans and READY reservations from PostgreSQL. It
  excludes a READY reservation already associated with an active loan, so the
  checkout hold is not counted twice. Availability does not own or modify these
  records.

Keep the code small: routes, data models, and database access. Split files only when they become difficult to maintain. Do not build a generic repository framework, shared application framework, or unnecessary abstractions.

## Proposed layout

```text
digital-library/
├── DESIGN.md
├── README.md
├── .env.example
├── compose.yaml
├── services/
│   ├── member/
│   │   ├── app/
│   │   │   ├── main.py          # FastAPI routes and health/metrics
│   │   │   ├── models.py        # Member model and request schemas
│   │   │   └── database.py      # PostgreSQL connection and queries
│   │   ├── tests/
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   └── catalog/
│       ├── app/
│       │   ├── main.py          # FastAPI routes and health/metrics
│       │   ├── models.py        # Book/copy request schemas
│       │   ├── database.py      # DynamoDB operations
│       │   └── covers.py        # S3 presigned URLs
│       ├── tests/
│       ├── requirements.txt
│       └── Dockerfile
├── scripts/
│   └── init_local.py            # Local DynamoDB tables and MinIO bucket
├── infra/
│   ├── main.tf                  # Terraform resources/modules
│   ├── variables.tf
│   └── outputs.tf
└── k8s/
    ├── member.yaml             # Deployment and Service
    └── catalog.yaml            # Deployment and Service
```

This is a **suggested structure**, not a requirement to create every file immediately. Prefer a small number of understandable files; split them when necessary. PostgreSQL schema setup can use a simple migration or initialization script. Use Terraform modules only if the assignment or team integration needs them.

## Member Service

**Table:** `members(member_id UUID PRIMARY KEY, name, email UNIQUE, created_at)`.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| POST | `/members` | Create member |
| GET | `/members` | List members |
| GET | `/members/{id}` | Retrieve member |
| PATCH | `/members/{id}` | Update name/email |

Use basic input validation; reject invalid requests and duplicate emails. Return 404 for missing members. There is no member deletion, borrowing eligibility, or loan management in this service.

## Catalog Service

**DynamoDB tables:**

- `Books`: `book_id` (partition key), `title`, `author`, optional `isbn` and `cover_key`.
- `Copies`: `copy_id` (partition key), `book_id` (attribute); GSI on `book_id` to list copies of a book.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| POST | `/books` | Add book |
| GET | `/books` | List books |
| GET | `/books/{id}` | Retrieve book |
| POST | `/books/{id}/copies` | Add physical copy |
| GET | `/books/{id}/copies` | List copies |

Server generates IDs. Validate required fields and ensure the parent book exists before adding a copy. Basic DynamoDB Scan/Query operations are sufficient; no search engine or sophisticated pagination system is needed. Catalog stores **copy identities**, not availability or loan state.

### Book covers

Store covers in a private S3 bucket (MinIO locally) and store only the object key on the book. Provide a simple way to upload a cover and retrieve its URL. Prefer presigned upload/download URLs so images do not pass through the API. Check JPEG/PNG content type and a reasonable maximum size. Do not implement upload staging, background cleanup, or complex object lifecycle logic.

## Common requirements

- REST JSON APIs with basic HTTP status codes.
- `/health` for Kubernetes health checks and `/metrics` for scraping by the monitoring team.
- Log to stdout. Cloud deployment forwards logs through Fluent Bit to CloudWatch
  and deploys Prometheus/Grafana through Argo CD.
- Basic automated tests of essential endpoints and data persistence.
- No authentication system unless explicitly required by the assignment or team integration contract.

## Local development and testing

Use Docker Compose to run PostgreSQL, DynamoDB Local, MinIO, and both APIs. Initialize local tables and bucket using a local-only script. Test normal member, book, copy, and cover workflows locally; provide a few curl examples.

**Do not contact AWS during local development.** Use dummy credentials only for the emulators. Do not use AWS SDK calls against real AWS endpoints for tests.

## Infrastructure and deployment

Terraform should define only the AWS components assigned to this member:

- VPC, subnets, routing, security groups.
- EKS cluster and node group.
- RDS PostgreSQL for Member.
- DynamoDB tables and S3 bucket for Catalog.
- Required IAM permissions for service access.

Use simple, secure defaults: private database and bucket, no credentials committed to Git. Coordinate shared cluster networking and deployment interfaces with other members rather than implementing their services.

Provide Dockerfiles and Kubernetes Deployments, ClusterIP Services, environment
configuration, health probes, two HPAs, an ALB Ingress, and GitOps manifests.
The cloud notification implementation is the Lambda under
`services/notification-lambda`; the local Notification API remains a Compose
adapter for development.

## Implementation checkpoints

1. **Design:** Agree on scope and APIs. Stop for review.
2. **Member:** Implement and test locally. Stop for review.
3. **Catalog:** Implement books and copies; test locally. Stop for review.
4. **Covers:** Implement and test with MinIO. Stop for review.
5. **Local integration:** Docker Compose and end-to-end local smoke tests. Stop for review.
6. **Terraform:** Write and statically validate infrastructure configuration only. Stop for review.
7. **Packaging:** Dockerfiles, Kubernetes manifests, and deployment instructions. Stop for review.

**AWS safety rule:** Never run `terraform apply`, provision or delete cloud resources, deploy to EKS, or perform real-account infrastructure operations without explicit approval for that particular action. Approval of a checkpoint is not permission to incur AWS charges.

**Guiding principle:** Implement what the assignment asks, verify that it works, and avoid production-grade features that add complexity without helping the demonstration.

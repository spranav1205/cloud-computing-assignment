# Checkpoint 1: Minimal Member and Catalog Design

**Status:** Design only. Do not implement until approved.

## Scope

Implement only the Member and Catalog services and infrastructure assigned to this team member. Other services (loans, reservations, fines, notifications, analytics), ArgoCD, autoscaling, and monitoring infrastructure belong to other members and are out of scope.

Where the starter design conflicts with the agreed task division, use the current assignment: **Member records in PostgreSQL; books and copies in DynamoDB; covers in S3**. Other services access these through APIs.

## Stack and structure

- Python + FastAPI for both services.
- PostgreSQL for members (SQLAlchemy is sufficient).
- DynamoDB for books and copies (boto3).
- S3 for book-cover objects; MinIO for local testing.
- Terraform for assigned AWS resources; Docker and Kubernetes for deployment.
- Local development with Docker Compose: PostgreSQL, DynamoDB Local, MinIO, and the two APIs.

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
- Log to stdout; do not add a monitoring stack.
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

Provide Dockerfiles and minimal Kubernetes Deployments, ClusterIP Services, environment configuration, and health probes for Member and Catalog. Leave ArgoCD, HPA, and monitoring stack deployment to the responsible team members.

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

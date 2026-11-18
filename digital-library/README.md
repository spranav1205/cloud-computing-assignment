# Digital Library

Digital Library lets readers browse books, manage memberships, reserve copies,
borrow and return books, check availability, and receive notifications.

The backend has **eight microservices**: seven HTTP APIs and one Flink
stream-processing job. A separate web frontend provides the reader interface.
See [ARCHITECTURE_DESIGN.md](ARCHITECTURE_DESIGN.md) for diagrams and details.

## Services

| Service | What it does | Interface |
| --- | --- | --- |
| Member | Manages reader accounts and checkout eligibility. | REST and gRPC |
| Catalog | Manages books, copy identities, and cover images. | REST |
| Reservation | Creates and queues copy reservations. | REST |
| Lending | Checks out and returns copies; tracks loans and due dates. | REST |
| Availability | Reports copy and book availability. | REST |
| Fine Calculation | Calculates and records overdue fines. | REST |
| Notification | Accepts notification requests and queues delivery. | REST; SQS/Lambda in AWS |
| Usage Analytics | Aggregates reservation and loan activity in one-minute windows. | Kafka and Flink |

The frontend is a web application, not an additional backend microservice.

## Documentation

| Document | What it covers |
| --- | --- |
| [Architecture design](ARCHITECTURE_DESIGN.md) | System and cloud diagrams, responsibilities, connections, and design rationale |
| [AWS testing and safety](AWS_TESTING.md) | Cloud testing constraints, costs, and approval notes |
| [Infrastructure guide](infra/README.md) | Terraform resources, networking, data stores, and AWS prerequisites |
| [Kubernetes and GitOps guide](k8s/README.md) | Container images, Kubernetes manifests, Argo CD, and deployment handoff |
| [Usage Analytics guide](services/usage-analytics/README.md) | Flink event format, aggregation, build, and EMR submission |

## Run locally

Prerequisites: Docker Desktop with Linux containers. Node.js 18 or newer is
needed only for the frontend.

From the repository root:

```sh
cd digital-library
docker compose up --build -d --wait --wait-timeout 600
docker compose ps
```

Compose starts the seven HTTP APIs, PostgreSQL, DynamoDB Local, and MinIO. It
does not start the frontend, Kafka, or the Flink job. To run the frontend, open
a second terminal in `digital-library` and run:

```sh
node frontend/server.js
```

Open the frontend at [http://127.0.0.1:4173](http://127.0.0.1:4173). The
frontend proxies API requests to the local services.

| API | Interactive docs |
| --- | --- |
| Member | [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs) |
| Catalog | [http://127.0.0.1:8002/docs](http://127.0.0.1:8002/docs) |
| Reservation | [http://127.0.0.1:8003/docs](http://127.0.0.1:8003/docs) |
| Notification | [http://127.0.0.1:8004/docs](http://127.0.0.1:8004/docs) |
| Fine Calculation | [http://127.0.0.1:8005/docs](http://127.0.0.1:8005/docs) |
| Lending | [http://127.0.0.1:8006/docs](http://127.0.0.1:8006/docs) |
| Availability | [http://127.0.0.1:8007/docs](http://127.0.0.1:8007/docs) |

To stop the local containers without deleting their data:

```sh
docker compose stop
```

PostgreSQL and MinIO data persist in Docker volumes. DynamoDB Local is
in-memory, so restarting its container clears books and copies. Avoid
`docker compose down -v` if you want to keep persistent volume data.

## Try a reservation

1. In the Member docs, create a reader.
2. In the Catalog docs, create a book and add a copy.
3. In the Reservation docs, create a reservation using the reader and book IDs.
4. Create another reader and reserve the same book to see the waiting queue.

Use the `/api/v1` routes for the architecture contracts. A reservation request
requires an `Idempotency-Key` header. The first request for an available copy
should be `READY`; the next should be `WAITING`.

## Tests

With the local APIs running, run the end-to-end API smoke test from the
`digital-library` directory:

```sh
python3 scripts/smoke_test.py
```

It exercises the seven APIs and leaves small demo records. Unit tests are in
each service's `tests` directory. For example, from `digital-library`:

```sh
cd services/lending
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q
```

Catalog tests require DynamoDB Local and MinIO. The Usage Analytics tests use
Maven; see its guide for the build command.

## Cloud deployment

Terraform describes the AWS infrastructure. Kubernetes manifests describe the
EKS services, autoscalers, ingress, and platform components. Argo CD is intended
to reconcile those manifests from Git. The Flink job is submitted to EMR
separately.

**The repository documentation says AWS resources have not been deployed.**
Read the [AWS testing and safety guide](AWS_TESTING.md) and
[infrastructure guide](infra/README.md) before any cloud operation. Review
[Kubernetes and GitOps](k8s/README.md) for image and cluster prerequisites.

## Assignment implementation map

| Requirement | Project components |
| --- | --- |
| Infrastructure as Code | Terraform under `infra/` |
| Serverless and service communication | Notification SQS/Lambda; REST and Member-Lending gRPC; Kafka topics are configured, but API event producers are not yet connected |
| Managed Kubernetes, autoscaling, and load testing | EKS configuration, Catalog and Reservation HPAs, and `scripts/k6/reservation-load.js` |
| GitOps deployment | Argo CD Applications and Git-tracked Kustomize manifests |
| Flink stream processing | Flink job under `services/usage-analytics/`, Kafka topics, and EMR configuration; live event flow has not been verified |
| Domain concept | Reservation queue coordination with ZooKeeper in the Kubernetes configuration |
| Cloud storage | RDS PostgreSQL, DynamoDB, and S3 |
| Observability | Prometheus/Grafana configuration and Fluent Bit forwarding to CloudWatch |

The frontend currently has a Kubernetes `ClusterIP` service, but the Ingress
does not route `/` to it. Also, the analytics event envelope and Flink input
fields need alignment before service events can be processed. These details are
documented in [ARCHITECTURE_DESIGN.md](ARCHITECTURE_DESIGN.md).

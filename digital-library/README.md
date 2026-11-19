# Digital Library

The application is deployed on AWS in `ap-south-1`. It has seven REST APIs, a
Member gRPC endpoint, a web frontend, and a separate Kafka/Flink analytics job.
RDS PostgreSQL, DynamoDB and private S3 provide the three storage products.

## Final terminal demo

From the repository root:

```powershell
python demo.py
```

Press **Enter** before each demo and each regular HTTP request. It prints the
actual JSON response and HTTP status. Regular API requests run sequentially;
Flink and the sustained HPA load test each run as an explicitly started step.
Type **q** at a prompt to finish and clean up created loans/holds. Ctrl+C also
runs cleanup. Flink and autoscaling take several minutes; they do not provision
new instances or change HPA limits.

| Step | Demonstrates |
|---|---|
| 1. REST APIs and private S3 | All 23 business endpoints, validation, FIFO holds, checkout/return and byte-for-byte private cover storage |
| 2. Member gRPC and ZooKeeper | Real eligibility RPCs and the reservation lock path |
| 3. Positive overdue fines | Deployed Fine code over loopback HTTP using temporary SQLite; production loan dates remain untouched |
| 4. Automatic email delivery | Checkout/return and explicit intake through SQS, Lambda and SES; duplicate-ID suppression |
| 5. Prometheus | Seven healthy scrape targets, request rates, latency, CPU and HPA metrics |
| 6. Kafka and Flink | Exact one-minute window counts/distinct members on existing EMR, completed checkpoint and test-job cleanup |
| 7. Autoscaling | Both HPAs scale 1 -> 2 -> 1 under sustained read-only HTTP load, while Argo CD remains Synced/Healthy |

Other ways to run it:

```powershell
python demo.py --list
python demo.py --sections api,grpc,fine,notifications,metrics
python demo.py --sections metrics,flink,hpa
python demo.py --auto
```

`--auto` skips Enter prompts. Notifications requires `api` earlier in the same
run because it uses that run's loan and event IDs. A failed demo is recorded and
the next section still waits for Enter. An early quit is marked STOPPED, never
as a complete PASS; cleanup failures still give a failing exit code.

Prerequisites are Python 3.10+, AWS CLI with the existing `default` profile,
`kubectl`, the running deployment, and these local files:

- `digital-library/.local/deployed-url.txt` (or supply `--base-url`).
- `digital-library/.local/recovery-kubeconfig` (or supply `--kubeconfig`).
- `digital-library/services/usage-analytics/target/usage-analytics-1.0.0.jar` for
  the Flink step; see its [build instructions](services/usage-analytics/README.md).

No extra Python packages are needed for `demo.py`. It locates the project from
its own path, so it also works when launched by absolute path from another
terminal directory. Results go to `digital-library/.local/demo-report.json` and
`digital-library/.local/demo-runs/RUN_ID/`. Previous full-audit evidence remains
in `.local/final-api-audit.json`. Local config/results are ignored by Git; the
standalone `demo.py` is tracked and does not import the ignored audit script.

The underlying full audit passed **146 functional HTTP checks, 37,956 load
requests and 79 assertions** on 19 November 2026. See
[FINAL_VERIFICATION.md](FINAL_VERIFICATION.md) for evidence and the detailed CLI guide.

## Services and behavior

| Service | Responsibility |
|---|---|
| Member | Register/get/update/list members; answer gRPC checkout eligibility |
| Catalog | Books, physical copies, private cover uploads/downloads |
| Reservation | READY/WAITLISTED FIFO holds, cancellation and promotion |
| Lending | Checkout, due dates, idempotent returns and automatic loan notifications |
| Availability | Derive copy availability from Catalog, reservations and loans |
| Fine | Read loan timestamps and calculate fines; does not modify loans |
| Notification | Queue explicit/automatic events through SQS -> Lambda -> SES |
| Usage Analytics | Kafka input -> one-minute Flink aggregates -> Kafka results |

The frontend proxies `/api/...` to internal routes such as `/members`, `/books`,
`/reservations` and `/loans`. The deployed app does not require an Idempotency-Key
header. Reservations use READY and WAITLISTED states.

`LoanIssued` and `LoanReturned` notifications use the member's stored email,
with a stable UUIDv5 per loan/event pair. Repeated or concurrent returns emit one
return event. Intake accepts optional `event_id`; older explicit requests without
it keep random IDs. The existing Lambda/DynamoDB consumer suppresses repeated IDs
within its retention window. Publishing is best-effort after commit: failures are
logged and do not fail the committed loan operation. There is no durable outbox;
crashes or failed publishes can lose events. Tests use labeled SES simulator
addresses, not real recipients. SES sender/recipient restrictions still apply.

Flink uses isolated synthetic Kafka fixtures. Lending/Reservation do not yet
publish Kafka domain events automatically. The checkpoint evidence includes one
completed and one failed attempt; zero-failure checkpointing/recovery is not
asserted. HPA load uses read-only `/health` traffic and proves scaling, not
business-endpoint capacity.

## Deployment and limits

API changes deploy through Argo CD from `deploy/deploy-20261118203335`.
Publishing to `main` alone does not deploy. Initial platform bootstrap and some
monitoring applies were direct, so strict end-to-end GitOps remains a caveat.

Compute remains **one t3.xlarge EKS worker + one m5.xlarge EMR primary = 8 vCPUs**.
Catalog/Reservation HPAs range from one to two pods; they do not add workers.
Preserve RDS, DynamoDB and S3. The real bucket
`replace-with-globally-unique-library-cover-bucket` is intentionally retained.
AWS resources remain running and consuming credits. Infrastructure changes need
a fresh reviewed Terraform plan; earlier full plans proposed an unrelated EMR
replacement. Demo cleanup does not destroy infrastructure or retained records.

## Local development and tests

From `digital-library`, Docker Desktop with Linux containers can run the seven
APIs and PostgreSQL/DynamoDB/MinIO emulators:

```powershell
docker compose up --build -d --wait --wait-timeout 600
python scripts/smoke_test.py
```

Run `node frontend/server.js` separately for the local frontend. Local Compose
does not start Kafka/Flink. Service unit tests live under each service's `tests/`.
Presenter-control tests run from the repository root without AWS:

```powershell
python -m unittest discover -s tests -v
```

## Essential documentation

| Document | Purpose |
|---|---|
| [Verification](FINAL_VERIFICATION.md) | Assignment evidence, CLI checks and remaining caveats |
| [Architecture](ARCHITECTURE_DESIGN.md) | Service and cloud diagrams/design |
| [Monitoring](MONITORING.md) | Prometheus/Grafana access and credential retrieval |
| [Infrastructure](infra/README.md) | Terraform resources, state and limits |
| [Kubernetes/GitOps](k8s/README.md) | Image publication, database bootstrap, Secrets and deployment |
| [Usage Analytics](services/usage-analytics/README.md) | Event contract, build and EMR submission |

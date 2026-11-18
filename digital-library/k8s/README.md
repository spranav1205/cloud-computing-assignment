# Final Kubernetes packaging and GitOps handoff

For the current image/config preparation and database bootstrap procedure, see
[AWS runtime setup](../AWS_SETUP.md). Member now has a schema init container;
older checkpoint notes below about initialization refer to the local API images.

These files are reviewable deployment inputs, not a deployment. No image was
published, no Kubernetes cluster was contacted, and no AWS plan or operation ran.
Argo CD owns the application sync; HPAs, ingress, platform services, and
observability resources are included in the repository as GitOps inputs.

## Build and test the packaged images locally

From `digital-library`, with the checkpoint 5 dependencies already configured:

```powershell
docker compose -f compose.yaml -f compose.packaged.yaml up --build -d --wait --wait-timeout 300 member catalog
./services/catalog/.venv/Scripts/python.exe scripts/integration_test.py
```

The override builds `library-member:checkpoint7` and `library-catalog:checkpoint7`
from their service Dockerfiles. It removes source/virtualenv mounts, uses the
dependencies baked into the images, runs UID/GID 10001, and sets a read-only root
filesystem with writable `/tmp`. No development/test dependencies are in either
image. Explicit initialization remains separate from API startup. Default Compose
still provides the previous development setup; omit the override to return to it.
Build contexts exclude virtual environments, tests, caches, and `.env` files.

For standalone builds, use `docker build -t library-member:checkpoint7
services/member` and the equivalent Catalog path from `digital-library`. These are
local image tags, not registry paths. Image publication is deferred until the
account/registry, costs, and cloud operation are explicitly approved.

## Local manifest validation

Run these PowerShell commands from `digital-library`:

```powershell
New-Item -ItemType Directory -Force .local | Out-Null
kubectl kustomize k8s -o .local/rendered-k8s.yaml
$workspacePath = (Get-Location).Path
docker run --rm --volume "${workspacePath}:/workspace:ro" --workdir /workspace python:3.12-slim sh -ec 'pip install --disable-pip-version-check -q -r scripts/requirements-validation.txt && python scripts/validate_k8s.py .local/rendered-k8s.yaml'
```

`kubectl kustomize` only renders local files. The Python validator uses bundled
Kubernetes 1.35.0 schemas and strict unknown-field checks. It validates all twenty
resources, with no skips or cluster access. Choose the schema version matching the
approved EKS version when that decision is made. This is syntax/schema validation,
not an EKS runtime test. Do not run `kubectl apply`, even as a server-side dry run,
against the final cluster during this checkpoint.

## What Member 3 receives

The AWS database name is `digitallibrary` (RDS rejects `library` as an initial
database name). Use Terraform's `member_database.database_name` output when
constructing every cloud database connection URL. Local Compose keeps `library`.

| Item | Contract |
| --- | --- |
| GitOps source path | `digital-library/k8s`, plain Kustomize; team supplies repository URL/revision |
| Namespace | `library` |
| Workloads | `member`, `catalog`, `reservation`, `lending`, `availability`, `notification`, and `fine`, one replica each, ClusterIP only |
| Service addresses | `member.library.svc.cluster.local:80`, `catalog.library.svc.cluster.local:80`, `reservation.library.svc.cluster.local:80`, `lending.library.svc.cluster.local:80`, `availability.library.svc.cluster.local:80`, `notification.library.svc.cluster.local:80`, `fine.library.svc.cluster.local:80` |
| Runtime ports | Member 8001, Catalog 8002, Reservation 8003, Notification 8004, Fine 8005, Lending 8006, Availability 8007; named `http` ports |
| Probes | `/health` for startup/liveness, `/ready` for storage readiness |
| Monitoring handoff | `/metrics`, scrape annotations, stdout logs; Member 4 owns collection |
| Catalog IAM | Service account `library/catalog`, IRSA annotation from Terraform `catalog.role_arn` |
| Member secret | Existing `member-database` Secret, key `DATABASE_URL`; no credentials in Git |
| Reservation secret | Existing `reservation-database` Secret, key `url`; no credentials in Git |
| RDS CA | Existing `rds-ca` ConfigMap with public certificate key `global-bundle.pem` |

All Deployments specify requests/limits, non-root execution, a read-only root
filesystem, dropped Linux capabilities, no privilege escalation, and a temporary
volume. Member has no mounted Kubernetes service-account token. Catalog keeps
service-account identity for IRSA and disables EC2 metadata credential fallback.
Reservation and Notification use the same hardened pod defaults. Notification
uses the optional `notification-config` ConfigMap; provide `NOTIFICATION_QUEUE_URL`
for SQS mode, otherwise it intentionally uses its in-memory local adapter.
Fine reads the shared lending database using the externally managed
`fine-database` Secret (`url` key); grant its database user read-only access to
the `loans` table. The URL must use `sslmode=verify-full` and
`sslrootcert=/etc/rds-ca/global-bundle.pem`; the pod mounts the existing `rds-ca`
ConfigMap. Set `FINE_PER_DAY_CENTS` to the agreed daily rate before sync.
Lending uses the externally managed `lending-database` Secret (`url` key) and
requires permission to create and maintain the `loans` table. Availability uses
the `availability-database` Secret (`url` key) with read-only access to `loans`
and `reservations`; both mount the same `rds-ca` ConfigMap and require verified
TLS URLs with `sslmode=verify-full` and
`sslrootcert=/etc/rds-ca/global-bundle.pem`. Lending's `/ready` endpoint also
checks Member, Catalog, and Reservation service readiness. Its Kubernetes
service URLs and the Availability Catalog URL are configured in the manifests.
The final Kustomize tree includes two HPAs, the ALB ingress, Kafka, ZooKeeper,
metrics-server, Prometheus/Grafana, and Fluent Bit. Usage Analytics runs as a
Flink job on the managed EMR cluster, not as an EKS deployment. Notification
uses the Terraform-managed Lambda/SQS path in cloud mode; its local API remains
available only for Compose development.

Before the first approved sync, Member 3 must review/replace:

1. Image references with approved registry references pinned to the built
   image digest. The placeholder local tags are not pullable from EKS.
2. Catalog's placeholder IRSA role ARN, bucket name, region, and table names using
   the approved Terraform outputs. Do not include static AWS keys.
3. The externally managed `member-database` Secret containing a restricted user's
   connection URL. It must use `postgresql+psycopg://`, `sslmode=verify-full`, and
   `sslrootcert=/etc/rds-ca/global-bundle.pem`. URL-encode special characters in
   the credentials. Never use the RDS master user as the API user.
4. The public RDS CA bundle in `rds-ca`, obtained from the official
   [RDS certificate documentation](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.SSL.html).
   It is public certificate data, not a password. No CA/secret resource is silently
   created by these manifests; missing prerequisites intentionally prevent startup.
5. The namespace, network/ingress agreement, GitOps repository/revision, secret
   delivery, and controlled database-user/schema initialization. Local initializer
   scripts explicitly refuse AWS mode or nonlocal database initialization. Database
   bootstrap is a checkpoint 8 operation, not an API startup side effect.

The submitted configuration is a handoff for review; no messages were sent to team
members and no GitOps sync was performed. Actual coordination/approval remains
necessary before publishing/syncing.

## Explicit runtime modes

`APP_ENV` defaults to `local`. Existing local PostgreSQL/DynamoDB/MinIO workflows
retain their dummy credentials and endpoint restrictions. Cloud mode is enabled
only with `APP_ENV=aws` in the Kubernetes ConfigMaps:

- Catalog requires `AWS_REGION` and `COVERS_BUCKET`, uses table-name configuration,
  and obtains temporary credentials through the SDK's default chain/IRSA. Emulator
  endpoint variables must be absent in cloud mode. Cloud factories were tested
  using mocks; no real AWS SDK requests were executed.
- Member requires a verified TLS PostgreSQL connection with an explicit CA path
  in cloud mode. Constructing its engine in a unit test opens no database connection.

Do not start these cloud-mode manifests on EKS without checkpoint 8 approval.
Local image verification uses the Compose emulator configuration, not these
cloud-mode ConfigMaps.

## Results and remaining verification

Both production-dependency images built and ran healthy locally. The end-to-end
Member + Catalog + private-cover workflow passed against the packaged images.
All **55 service tests** passed (22 Member, 33 Catalog), zero skipped; cloud
configuration tests mocked SDK construction. The earlier **16 Kubernetes
resources** passed strict bundled schema validation; rerun validation after
including Lending and Availability. The revised Terraform configuration validated
and all **3 mock-provider tests** passed. The existing upstream Starlette/httpx
deprecation warning remains non-failing.

Kubernetes scheduling, IRSA tokens, real RDS TLS, image pulls, EKS network access,
and ArgoCD reconciliation require later approved environment testing. They are not
claimed as verified by Docker or schema checks. Kubernetes is not installed or
deployed locally by this checkpoint.

The two Argo CD Application resources in `../argocd/` track the application
Kustomize path and the platform Kustomize path. Bootstrap those Applications
through the approved Argo CD installation path; after bootstrap, changes are
made by Git commits and Argo reconciliation rather than direct workload
commands.

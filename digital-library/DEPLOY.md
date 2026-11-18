# Build, publish, deploy, verify

Follow [the current AWS runtime setup](AWS_SETUP.md) before the first cloud sync;
it supersedes historical credential/state and deployment-prerequisite notes below.

Use the tools already in the repository for their own jobs:

1. Terraform provisions AWS resources, including the ECR repositories.
2. CI tests the source, builds the container images, and publishes them to ECR.
3. An image update is committed to the Kubernetes manifests in Git.
4. Argo CD reconciles those manifests onto EKS.
5. A smoke test verifies the running services.

Infrastructure changes normally have their own reviewed Terraform plan/apply
job. They do not run on every application image build. Our existing
`.github/workflows/ci.yml` runs tests and validation; image publishing and
manifest updates are the missing CI/CD stages. No new Python deployment
orchestrator is needed.

## Publish images from your terminal

Start Docker Desktop with Linux containers. Review/apply Terraform first so
`terraform -chdir=infra output -json image_repositories` returns the registry
URLs. The new repositories are declared in `infra/ecr.tf` and have
immutable tags. The image script does not apply infrastructure or deploy pods.

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\digital-library\scripts\publish-images.ps1 -Profile default
```

The script checks the active account against the Terraform outputs, logs into
ECR, builds and pushes seven API images plus the frontend for `linux/amd64`, and
records their digests in ignored `digital-library/.local/images-TAG.json`.
The default tag combines the Git commit and a UTC timestamp. You can set `-Tag`
explicitly, but an existing immutable ECR tag cannot be overwritten. Commit
source changes before publishing so artifacts have a clear source revision.
The script stops on the first failed command and does not print AWS credentials.

Update `image:` references in `digital-library/k8s/*.yaml` with those published
references, commit/push the manifest changes, and let the existing Argo CD
Applications reconcile. The frontend Dockerfile and Deployment are included.
It exposes a ClusterIP Service; route `/` to it through the team's ingress setup
or use `kubectl -n library port-forward service/frontend 4173:80` for the demo.
The frontend proxies its `/api/...` requests to the Kubernetes services.

Notification Lambda is deployed from its ZIP by Terraform, not from an ECR
image. Usage Analytics is built as a shaded Flink jar and submitted to EMR; see
`services/usage-analytics/README.md`. Publishing API images alone does not launch
that job.

## Prerequisites still needed before the first full AWS run

The ignored `infra/terraform.tfvars` still needs a real administrator `/32`, an
intentional unique bucket name, a real administrator ARN, and `ses_sender`.
Read-only checks on 18 November 2026 found the `default` profile and IAM user
`arn:aws:iam::380560899065:user/terraform-emr`; the old `library-test` profile and
`library-deployer` identity in the checkpoint examples did not exist.
EKS 1.35 was in Mumbai standard support. There are no verified Mumbai SES
identities. Verify a sender email in SES before testing actual delivery.

The Kubernetes manifests also need their real Catalog/Fluent Bit IRSA role
annotations and storage configuration, RDS users/schema, TLS CA ConfigMap, and
the database Secrets described in `k8s/README.md`. SQS mode for the Notification
API requires its queue URL and a service-account role with `sqs:SendMessage`;
the Lambda's consumer role does not give the API permission to publish. The
team's ingress controller/Argo CD bootstrap and Grafana Secret must exist too.

These are explicit setup/configuration steps; this helper does not silently
create application users, secrets, Git branches, or additional clusters.
The full platform is larger than the original Member/Catalog-only footprint;
review worker capacity for Kafka, three ZooKeeper pods, Argo CD and monitoring
before expecting everything to fit on a `t3.medium`.

The account reported **Paid plan and $65.30 remaining credits**, rather than
Free plan. EKS, NAT, RDS, EMR and load balancers can charge while idle. Check
Mumbai pricing and use a short attended test window. Stopping pods does not
stop those AWS charges. Preserve Terraform state and plan cleanup before leaving
resources running. See [EKS pricing](https://aws.amazon.com/eks/pricing/) and
[EMR pricing](https://aws.amazon.com/emr/pricing/).

## Run the seven-service smoke test

For a local test, from `digital-library`:

```powershell
docker compose up --build -d --wait --wait-timeout 600
python scripts/smoke_test.py
```

For AWS, stop Compose first to free ports 8001-8007, open temporary port forwards
for the seven Services to those ports, then run the same script. Service names
are `member`, `catalog`, `reservation`, `notification`, `fine`, `lending`, and
`availability`; each Service exposes port 80. For example, keep this running in
another terminal while testing Member:

```powershell
kubectl -n library port-forward service/member 8001:80
```

Each service URL is also configurable with `--member-url`, `--catalog-url`, etc.
Include `--frontend-url http://127.0.0.1:4173` to test the frontend and its API
proxy. The script requires only Python's standard library and exits nonzero on
failure. Reports and created record IDs go to ignored `.local/smoke/`.

Checks cover health/readiness, Member CRUD and duplicate rejection, books/copies,
DynamoDB index visibility, signed cover upload/download and denied unsigned
access, FIFO reservations, availability before/during/after a loan, checkout,
zero fine for a new loan, idempotent return, waiter promotion, notification
intake, and metrics. Each run returns its loan and cancels its active holds;
it leaves small demo member/book/copy/cover records. The default notification
recipient is AWS's SES simulator, not a real person's inbox.

An accepted notification proves intake only. Verify Lambda/SES delivery in
CloudWatch separately. This API script does not claim to test Flink, autoscaling,
GitOps reconciliation, or fault recovery. Those need their own runtime evidence;
use the existing Flink instructions and `scripts/k6/reservation-load.js`.

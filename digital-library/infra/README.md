# AWS infrastructure

Terraform owns the deployed AWS infrastructure in `ap-south-1`. Kubernetes/Helm
bootstrap and application deployment are separate from this Terraform root.
Current evidence is in [FINAL_VERIFICATION.md](../FINAL_VERIFICATION.md); run the
interactive demonstration with `python demo.py` from the repository root.

## Resource ownership

| Files | Resources |
|---|---|
| `main.tf`, `variables.tf` | Providers, validated inputs, naming and tags |
| `network.tf` | VPC, public/private/database subnets across two AZs, routing, NAT and gateway endpoints |
| `eks.tf` | EKS, access entry, node roles and fixed one-node managed group |
| `storage.tf` | Private RDS PostgreSQL, DynamoDB Books/Copies and notification-deduplication tables, private S3 |
| `catalog_iam.tf` | Catalog IRSA and scoped DynamoDB/S3 permissions |
| `messaging.tf` | SQS/DLQ, Lambda, API publisher role, SES delivery permissions |
| `streaming.tf` | EMR/Flink primary, private Kafka connectivity and checkpoint/log permissions |
| `ecr.tf` | Existing API/frontend ECR repositories |
| `outputs.tf` | Network, EKS, database, catalog, messaging, analytics and image identifiers |
| `tests/offline.tftest.hcl` | Mock-provider tests without AWS calls |

The cluster uses one `t3.xlarge` EKS worker and one `m5.xlarge` EMR primary,
**8/8 vCPUs**. No core node group or replacement-instance headroom is available
alongside them. HPAs add pods only and stay within the existing worker.

Preserve the three storage products: RDS PostgreSQL, DynamoDB and S3. The bucket
`replace-with-globally-unique-library-cover-bucket` is real and intentionally
retained. Do not rename it as a placeholder fix. It stores private covers and
analytics artifacts/checkpoints/logs under separate prefixes.

## State and configuration

Local Terraform state already exists and must be preserved. Do not treat a
fresh clone or empty state as permission to recreate the environment. State,
plans, `.terraform/`, `.tfvars`, credentials and secrets remain ignored. Keep
`.terraform.lock.hcl` tracked. Required local inputs include account ID,
administrator IAM user/role ARN, supported EKS version, administrator egress CIDR,
intentional bucket name and SES sender. See `variables.tf` for validation/defaults.

Use a fresh plan for an infrastructure change and inspect its full effects;
earlier full plans proposed an unrelated EMR replacement. Do not reuse old saved
plans. Resource protection, snapshots and retained data require deliberate
handling. Demo cleanup does not destroy infrastructure or remove persistent data.
AWS resources remain running and consuming credits; stopping pods does not stop
EKS, NAT, RDS, EMR or load-balancer charges.

## Storage and identity

PostgreSQL is private/encrypted and uses shared database `digitallibrary`.
Bootstrap restricted service users and supply verified-TLS URLs and the public
RDS CA through the Kubernetes contracts in [k8s/README.md](../k8s/README.md).
Catalog's IRSA role is scoped to book/copy operations and private `covers/*`
objects. Notification has a separate scoped SQS publisher role. Lambda consumes
SQS, uses DynamoDB notification-ID deduplication and calls SES. EMR's role can
read/write its approved artifact/checkpoint/log prefixes in the existing bucket.

S3 blocks public access, disables ACL-based ownership and uses encryption and a
TLS-only policy. RDS and applicable DynamoDB tables use deletion protection;
RDS requires a final snapshot on deletion. Terraform does not embed credentials.

## Local validation and deployment

From `digital-library/infra`:

```powershell
terraform fmt -check -recursive
terraform init -backend=false -input=false
terraform validate -no-color
terraform test '-filter=tests\offline.tftest.hcl' -no-color
```

The tests use mocked providers and are not proof of a real deployment. The live
demo separately tests actual services, storage, streaming and autoscaling.
Application/image preparation, database bootstrap and Argo CD deployment are
covered in [k8s/README.md](../k8s/README.md). Image publishing does not run a
Terraform apply or launch the Flink job.

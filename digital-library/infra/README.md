# Checkpoint 6: Terraform proposal, not a deployment

This directory defines only the agreed shared AWS resources. No AWS plan, apply,
deployment, scaling, teardown, or account discovery is authorized by this checkpoint.
The configuration has no AWS data sources and no Kubernetes/Helm provider that
could deploy workloads. A real-account plan still requires separate approval.

## Files and proposed resources

| File | Responsibility |
| --- | --- |
| `main.tf`, `variables.tf` | Provider/version requirements, tags, naming, validated inputs |
| `network.tf` | VPC, two AZs, public/private/database subnets, routing, one NAT, S3/DynamoDB gateway endpoints |
| `eks.tf` | EKS control plane, administrator access entry, node role, one managed node group |
| `storage.tf` | Private PostgreSQL, Books/Copies tables with copy GSI, private cover bucket |
| `catalog_iam.tf` | Catalog's service-account trust and resource-scoped storage permissions |
| `outputs.tf` | Nonsecret resource identifiers for the team |
| `tests/offline.tftest.hcl` | Mock-provider tests that do not contact AWS |

This is one flat root configuration, following the revised minimal design. The
files separate concerns without introducing a module framework for a single
environment. The team can add coordinated resources in separate files or extract
modules later; no other member's infrastructure is implemented here.

### Network and compute

- Region example/default: `ap-south-1`; exactly two explicitly chosen AZs.
- VPC: `10.20.0.0/16`. Two public, two private-worker, and two isolated database
  subnets. Confirm CIDR compatibility with the team before deployment.
- One NAT gateway in the first public subnet serves both worker subnets. This is
  a small development setup with an AZ dependency and possible cross-AZ traffic
  costs, not a highly available network. Database subnets have no internet route.
- Gateway endpoints route worker S3/DynamoDB access inside AWS. Other traffic,
  including image downloads and identity endpoints, can use NAT.
- EKS API has private access for nodes and public access restricted to explicit
  administrator IPv4 CIDRs (/24 or narrower, preferably an egress /32). It is not
  open to the internet. This is an administrative API, not the application ingress.
- One on-demand `t3.medium` worker is desired, with group bounds 1-1, encrypted
  20 GiB gp3 root disk, no SSH key, and IMDSv2 required with hop limit 1. The bound
  does not install an autoscaler. One worker is not sized for every team's Kafka,
  ZooKeeper, Flink, and monitoring workloads; coordinate sizing before deployment.
- An explicit Kubernetes version and existing administrator IAM user or role ARN
  (`cluster_admin_principal_arn`) are required. Root/STS session ARNs cannot be used
  as that access-entry principal. IAM users and roles are both supported by
  [EKS access entries](https://docs.aws.amazon.com/eks/latest/userguide/creating-access-entries.html).
  The creator is not silently granted administrator access. Managed EKS bootstrap
  networking/DNS components are used; no ArgoCD, HPA, monitoring stack, ingress
  controller, application workloads, or custom platform add-ons are installed.

### Storage and permissions

- Member gets a single-AZ RDS PostgreSQL 16 instance (`db.t4g.micro`, 20 GiB gp3),
  encrypted storage, one-day backup retention, and no public endpoint. Port 5432
  accepts only the EKS cluster/node security group. This simple group also covers
  other workloads on the nodes; database credentials/SQL permissions must isolate
  Member data. It is not per-pod network isolation.
- RDS manages the master password in Secrets Manager. Only the secret ARN is
  exposed; Terraform never reads the password value. Before deployment, coordinate
  a controlled bootstrap of a restricted Member database user/schema and delivery
  of its connection secret to Kubernetes. The API must not use `library_admin`.
- Books and Copies use small provisioned capacity and encrypted storage. Each table
  and the copy GSI has 5 RCUs and 5 WCUs (15 of each in total), without autoscaling.
  These values can throttle higher loads and share any eligible account allowance
  with other DynamoDB usage. Copies has the
  `book_id-index` GSI with all attributes projected. No loan/availability fields or
  other members' data stores are introduced.
- S3 blocks all public access, disables ACL-based ownership, encrypts with SSE-S3,
  and denies non-TLS requests. Objects are not automatically deleted on teardown.
  Browser CORS, versioning, replication, lifecycle cleanup, and custom KMS keys
  are not added to this MVP. Command-line presigned uploads need no CORS policy.
- Catalog's IRSA trust accepts only the `catalog` service account in namespace
  `library`, with audience `sts.amazonaws.com`. Its policy allows the book
  operations, copy insertion/readiness, copy-GSI Query, bucket metadata/listing,
  and GetObject/PutObject under `covers/*`. It has no object-delete, database-admin,
  infrastructure, or other-bucket permissions. `ListBucket` also lets S3 report a
  missing object as 404 during confirmation.
- Member has no storage IAM role: it uses PostgreSQL credentials. EKS control plane
  and node roles use AWS's standard EKS/ECR/CNI managed policies. The CNI policy
  remains on the node role for this minimal setup; it is not Catalog's role.
  IMDS restrictions limit ordinary pods' access to node credentials. Separate
  CNI identity and per-pod network isolation can be coordinated if needed later.

RDS and both DynamoDB tables default to deletion protection. RDS also requires a
final snapshot on deletion. The fixed example final snapshot name may need a new
unique value before a separately approved teardown if that name already exists.
Removing protection, deleting resources, and deleting retained snapshots/objects
each remain separately approved cloud operations. Nothing automatically destroys
resources after a demonstration.

## Safe local checks

From `digital-library/infra`, with Terraform 1.9+ installed:

```powershell
terraform fmt -check -recursive
terraform init -backend=false -input=false
terraform validate -no-color
terraform test '-filter=tests\offline.tftest.hcl' -no-color
```

Initialization downloads only the public provider package and verifies its
signature/checksums; it does not access an AWS account or initialize remote state.
After downloading, validation and the mock-provider tests work locally. The test
file explicitly replaces the AWS provider with `mock_provider "aws"` in every run.
Its internal test plans are mocked, not real AWS plans. Tests check private and
encrypted storage, PostgreSQL ingress, bucket public-access protection, metadata
settings, deletion protection, and rejected administrator/account/CIDR inputs.
Do not remove the mock or run an unapproved real-account `terraform plan`.

Commit `.terraform.lock.hcl` to preserve provider selection/checksums. Do not commit
`.terraform/`, Terraform state, plan files, real `.tfvars` files, credentials, or
crash logs. These checks require neither actual nor dummy AWS credentials.

The single local configuration file is ignored `terraform.tfvars`; the redundant
example file was removed by the user. Required inputs are:

| Input | Value to supply locally |
| --- | --- |
| `aws_account_id` | Intended account's 12-digit ID, matching the active profile |
| `cluster_admin_principal_arn` | Existing IAM user/role ARN in that account |
| `kubernetes_version` | Regionally available standard-support version; 1.35 was confirmed |
| `eks_public_access_cidrs` | Actual administrator egress IPv4 CIDR, usually `/32` |
| `cover_bucket_name` | Intentional globally unique lowercase bucket name |

Region/AZ defaults are Mumbai (`ap-south-1`, AZs `a` and `b`); keep overrides in
the same local file if the team selects another region. See `variables.tf` for
all defaults and validation rules. No AWS keys or database passwords belong there.

No backend is configured. Before any approved deployment, agree with the team on
encrypted remote state, state locking, access controls, and ownership. Creating
the backend's resources is also a separate, explicitly approved operation. Do not
treat the absence of a configured backend as permission to create local cloud state.

**Recorded verification:** Terraform 1.16.2 with AWS provider 6.73.0 passed
formatting, validation, and **5 mock-provider tests**, including IAM-user acceptance
and wrong-account/root rejection. The Windows CLI requires the backslash test-file
filter above; confirm that the summary reports five tests rather than zero.
The user later generated a real saved plan, which was inspected locally during
cleanup. Its 48 additions and remaining placeholder inputs are documented in
`../AWS_TESTING.md`. The agent has run no AWS plan, apply, or deployment.

## Handoff and deployment decisions

Outputs provide VPC/subnet IDs, EKS endpoint/CA/security group/OIDC identifiers,
RDS endpoint and master secret ARN, DynamoDB table names, cover bucket, and Catalog
role ARN. Member 3 can use the namespace/service-account contract for GitOps during
packaging. Other members can propose additional resources against the same VPC and
cluster. There are no Lambda, SQS, Kafka, ZooKeeper, EMR, Flink, HPA, or monitoring
resources in this root configuration.

Static checks cannot establish that a region/account supports a Kubernetes version,
instance size, AZ, quota, or globally unique bucket name. They cannot verify actual
IAM access, node bootstrap, cluster networking, database connectivity, or billing.
Review those in checkpoint 8 before an explicitly approved real-account plan.

Checkpoint 7 adds an explicit, mock-tested AWS configuration path and Kubernetes
handoff in `../k8s/README.md`. Local mode still defaults to emulator endpoints and
dummy credentials. Real table/bucket/role values, RDS CA/TLS settings, a restricted
database user, Secret delivery, and actual cloud connectivity remain deployment
prerequisites. No application is ready to deploy merely because Terraform validates.

## Potential costs to review before AWS approval

These files create nothing until an approved operation, but the proposed stack is
not free when running. Rates below were checked on 2026-11-17; recheck before use.

| Component | Billing to include in the deployment estimate |
| --- | --- |
| EKS | AWS lists $0.10/cluster-hour in standard support and $0.60 in extended support. At the standard rate, 24 hours is $2.40 for the control plane alone, excluding all other resources. [EKS pricing](https://aws.amazon.com/eks/pricing/) |
| Worker | EC2 instance time plus its 20 GiB gp3 disk; bursting may add CPU-credit charges. [EC2 pricing](https://aws.amazon.com/ec2/pricing/on-demand/), [EBS pricing](https://aws.amazon.com/ebs/pricing/) |
| NAT and IP | NAT gateway hours/data processing, possible cross-AZ transfer, and its public IPv4 address. AWS lists $0.005/IP-hour, in addition to NAT charges. [VPC pricing](https://aws.amazon.com/vpc/pricing/) |
| PostgreSQL | Instance time, allocated database storage, backup/snapshot storage as applicable, and potential CPU credits. [RDS PostgreSQL pricing](https://aws.amazon.com/rds/postgresql/pricing/) |
| Database secret | The RDS-managed secret and Secrets Manager API use. [Secrets Manager pricing](https://aws.amazon.com/secrets-manager/pricing/) |
| DynamoDB | Provisioned read/write capacity and stored data; the 15 RCU/15 WCU total must share any eligible 25 RCU/25 WCU allowance with other account usage. [DynamoDB pricing](https://aws.amazon.com/dynamodb/pricing/) |
| S3 | Object storage, requests, and applicable outbound transfer; unconfirmed/replaced covers still occupy space. [S3 pricing](https://aws.amazon.com/s3/pricing/) |

The total requires agreed runtime, region, traffic, database/node sizing, support
version, retention, and the other members' contributions. Use a current estimate
for those inputs before seeking deployment approval. This is not a total-price
quote or a promise of free-tier eligibility. Retained volumes, snapshots, objects,
secrets, or addresses can continue to cost money after application workloads stop.

## User's trial-credit constraint

The user reports a **Free plan with roughly $40 remaining: at most $20 for testing,
with $20 reserved for the demonstration**. This is a spending limit, not permission
to use that amount or to provision anything. No AWS credits were consumed by local
validation or packaging. The account creation date and exact eligibility were not
provided, and this work did not inspect the AWS account.

The sizing now caps the worker group at one node, uses Standard EC2 CPU credits
instead of Unlimited (bursts may be throttled instead of incurring surplus-credit
charges), and provisions 5 RCU/5 WCU per table/index. The small single-AZ database,
20 GiB volumes, one NAT, no load balancer, and no other members' resources remain.
The chosen RDS class is not a guarantee of legacy Free Tier eligibility; RDS CPU
credits, Secrets Manager, NAT/IP, EKS, data transfer, and retained data can still
consume credits or incur charges under the applicable plan.

AWS's [Free Tier FAQ](https://aws.amazon.com/free/free-tier-faqs/) distinguishes
Free/Paid plans and credit availability; do not equate a Free plan with zero-cost
EKS infrastructure. [DynamoDB pricing](https://aws.amazon.com/dynamodb/pricing/)
lists a provisioned 25 RCU/25 WCU allowance for eligible Standard tables. Eligibility,
other account usage, restrictions, and credit expiry must be checked before use.
Do not automatically upgrade the user's account or change the agreed architecture.

Before checkpoint 8, verify the live credit balance/eligibility with permission,
estimate the **entire** regional stack and other team usage, agree on a short test
window and specific teardown operations, and obtain separate cloud-operation
approval. Include retained snapshot/secret/object/IP costs in that estimate. A
billing alert or Terraform capacity bound is not a hard dollar cap and billing
data may lag. Do not leave EKS/NAT/RDS running unattended. If the full assignment
cannot fit the testing budget while preserving the demo reserve, pause and agree
on scope/timing rather than spending the reserve or promising free deployment.

# Checkpoint 8: user-run AWS testing, one approved step at a time

Status: preflight preparation only. No real Terraform plan, AWS deployment,
image publication, or account inspection has been performed by the agent.

Budget: approximately $40 in credits reported by the user. Testing may consume
**at most $20**; preserve **$20 for the demo**. That limit is not a spending target.
Do not run the stack unattended or upgrade the Free account plan automatically.

## 1. Read-only account and regional checks

Run these in your own PowerShell terminal. They do not create resources or retrieve
secret values. Select an existing non-root development profile; never share access
keys, session tokens, credentials files, or secret values in chat.

```powershell
aws configure list-profiles
$env:AWS_PROFILE = 'YOUR_EXISTING_PROFILE'
aws sts get-caller-identity --no-cli-pager
aws eks describe-cluster-versions --region ap-south-1 --version-status STANDARD_SUPPORT --query 'clusterVersions[].clusterVersion' --output json --no-cli-pager
```

Stop if the identity ends with `:root`. If no profile is configured or login has
expired, report that error so authentication can be set up without sharing keys.
The region is the existing Mumbai example; confirm if the team chose another.
The Kubernetes version in `terraform.tfvars.example` is only a placeholder until
the regional support check succeeds. Standard support matters for cost: AWS lists
EKS at $0.10/cluster-hour in standard support, versus $0.60 in extended support.
[Official EKS pricing](https://aws.amazon.com/eks/pricing/).

Also confirm the current credit balance/expiry and Free-plan service availability
in your Billing console. No billing or account credentials need to be shared.
Before deployment, identify the existing team administrator IAM role and whether
Member 3's ArgoCD and image registry are ready. The cluster is shared infrastructure;
do not create a duplicate of an existing team cluster or platform.

## 2. Make the proposed test concrete before provisioning

Copy `infra/terraform.tfvars.example` to the ignored `infra/terraform.tfvars` and
fill in the selected account, existing administrator role, region/AZs, supported
Kubernetes version, actual administrator egress CIDR, and globally unique bucket.
These files need no AWS secret keys or database password. Do not paste credentials
into Terraform files or commit real variable files.

Agree on state ownership/location before any apply. Review the whole stack in
the AWS Pricing Calculator for the actual region: one EKS control plane, one
`t3.medium` worker, one `db.t4g.micro`, both 20 GiB volumes, NAT gateway/public IPv4,
RDS-managed secret, DynamoDB capacity/GSI/storage, S3, transfer, and registry storage
if using ECR. Include the other team members' account usage and any retained data.
The EKS charge alone is not a total estimate. See `infra/README.md` for sources.

Use an initial short test window (for example two hours) only after its complete
estimated cost fits comfortably within the remaining testing allocation. Reserve
time/cost for provisioning, diagnosis, and cleanup. Confirm the exact resources
to remove afterward and the owner responsible for doing so. Stopping pods does
not stop EKS/NAT/database charges; retained snapshots/secrets/objects can also cost
money. Billing updates/alerts may lag and do not enforce a hard dollar cap.

## 3. Real Terraform plan: separate review, no apply

After step 1/2 and explicit approval to inspect a real-account plan, run this
yourself from `digital-library/infra` with the intended AWS profile selected:

```powershell
terraform init -backend=false -input=false
terraform plan -input=false -var-file='terraform.tfvars' -out='review.tfplan'
```

The plan can access AWS APIs using your credentials, but does not provision the
planned resources. Do not run `apply` yet. Share the final resource-change counts
and relevant errors, not credentials or the raw plan file (which may contain
sensitive values). Stop on any unexpected modifications/deletions of existing
resources. The expected initial configuration primarily adds new resources.

Only after reviewing the concrete plan, complete cost estimate, and cleanup
responsibility should an individual apply operation be explicitly authorized.
The previous mock-provider test plans were not this real AWS plan.

## 4. Deployment and cloud verification after their individual approvals

Remaining tasks are publishing the two images to the agreed registry, bootstrapping
the restricted database user/schema, supplying the RDS CA and Kubernetes Secret,
replacing manifest placeholders using Terraform outputs, and Member 3's GitOps
sync. These are not authorized merely by approving a Terraform plan. Do not bypass
the GitOps agreement with a manual deployment to the final cluster.

After an approved deployment, use authorized local port forwards for the Member
and Catalog ClusterIP Services on ports 8001 and 8002. Then the existing
`scripts/integration_test.py` exercises both real services, including a direct
presigned S3 upload, confirmation, signed download, and denied unsigned access.
It leaves test records/objects. Cloud URLs must refer to real S3; do not rewrite
signed URLs. Review the observed health/readiness, application logs, IAM denials,
and test results before declaring AWS testing complete.

At the end of the approved window, obtain explicit approval for the agreed cleanup
operations. Deletion protection and retained snapshots/objects require conscious
handling; do not silently disable protection, empty a bucket, or destroy resources.

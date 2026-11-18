# AWS runtime setup

Current review: 19 November 2026. Read-only STS succeeds for account
`380560899065`; providers are initialized and local Terraform state exists.
Historical credential, saved-plan, and placeholder findings in checkpoint docs
do not describe the current environment. Compute recovery completed successfully:
Terraform added 2 resources, changed 0 and destroyed 0 on the final restore apply.
EKS has one Ready worker and EMR is ready to run steps. Terraform explicitly selects Mumbai; the CLI's
default region does not override it. Use `--region ap-south-1` for AWS CLI calls.

1. Infrastructure is provisioned, including the Notification API publishing role.
   Its permission is limited to `sqs:SendMessage` on the application queue.
   Preserve the local Terraform state. Generate a fresh plan for any future
   infrastructure change; do not reuse the old recovery plans.
2. Publish the eight images with `scripts/publish-images.ps1`, then run the local
   preparation helper from the repository root:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\digital-library\scripts\configure-aws.ps1 -ImagesFile .\digital-library\.local\images-TAG.json
   ```

   It reads Terraform outputs, validates repository/digest matches, and updates
   the tracked images, Catalog storage/IRSA, Notification queue/IRSA, and Fluent
   Bit IRSA settings. Both Member containers receive the same image digest.
   Review and commit the diff for Argo CD. This helper only edits local files.
3. Using an administrator connection from **inside the VPC**, run
   `scripts/bootstrap-database.sql` through interactive `psql -f` connected to
   `digitallibrary`. It creates five application roles and prompts for passwords
   without echoing them. This is a one-time bootstrap for a fresh database.
   Owners receive table-creation permission; Availability/Fine receive the
   required read access. Member's init container creates its table; Lending and
   Reservation already initialize theirs. API pods never need the RDS master user.
4. Before sync, create namespace `library`, ConfigMap `rds-ca` with the official
   public RDS certificate under key `global-bundle.pem`, and these Secrets using
   the team's secret-delivery mechanism:

   | Secret | Key | PostgreSQL role |
   | --- | --- | --- |
   | `member-database` | `DATABASE_URL` | `library_member` |
   | `reservation-database` | `url` | `library_reservation` |
   | `lending-database` | `url` | `library_lending` |
   | `availability-database` | `url` | `library_availability` |
   | `fine-database` | `url` | `library_fine` |

   All URLs must use the **same** database and this format:
   `postgresql+psycopg://ROLE:URL_ENCODED_PASSWORD@RDS_HOST:5432/digitallibrary?sslmode=verify-full&sslrootcert=/etc/rds-ca/global-bundle.pem`.
   Do not put passwords in Git or command-line arguments. Availability reads both
   loans and reservations, so separate empty databases will not work.
5. Bootstrap Argo CD and the AWS Load Balancer Controller, then sync the platform
   and application. The ALB wildcard rules are intentionally ordered so
   `/books/BOOK_ID/availability` reaches Availability before the general Catalog
   pattern. `/*` reaches the frontend, including its existing `/api/...` proxy.
   For a demo without an ALB, port-forward `service/frontend` from `4173:80`.
6. Run the existing smoke test through service port-forwards. SES sender
   verification is required to test actual email delivery.

The local `terraform.tfvars` now selects one `t3.xlarge` EKS worker (4 vCPUs,
16 GiB), paired with one `m5.xlarge` EMR primary (4 vCPUs, 16 GiB) and no core
group. This totals the verified Mumbai quota of 8 Standard On-Demand vCPUs.
Catalog and Reservation HPA ranges are 1-2 replicas. HPA does not add workers.
No other Standard On-Demand instances or temporary replacement capacity fit
alongside both nodes. The node group spans both private AZs; EMR uses the first.

The old two-node EMR cluster and failed worker group were removed during the
approved recovery. Their replacements are now running within the 8-vCPU quota.
EMR termination protection is enabled on the new cluster; storage is retained.
The worker depends on EMR so future creation waits for EMR to finish first.
Read-only Kubernetes verification confirmed the worker and baseline networking/
DNS pods are healthy. Application workloads have not been deployed yet.
The apply log is `.local/compute-restore-apply.txt` under `infra`; the workspace
kubeconfig is `.local/recovery-kubeconfig` under `digital-library`.

No Kafka publisher was added to Lending/Reservation. Analytics needs a manually
submitted job and separately supplied events. Its documented topics now match
the existing `.v1` topics. If reservation cancellation fails after a loan return,
retry the existing return endpoint; it retries cancellation even for an already
returned loan. Distributed transaction handling is outside this minimal change.

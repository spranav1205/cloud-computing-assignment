# AWS monitoring

Verified on 19 November 2026 against the running EKS deployment:

- Prometheus is Ready and its operator reports reconciliation successful.
- Member, Catalog, Lending, Availability, Fine, Reservation and Notification all
  have healthy scrape targets.
- Real application request counters and latency histograms are present for all
  seven services, including the two newly deployed metrics endpoints.
- Grafana can query Prometheus, and all five live dashboard queries validate.
- The existing EKS worker and EMR instance remain the only compute instances;
  monitoring adds pods on the existing worker, not EC2 instances.

The local forwards opened during verification are:

- Grafana dashboard: http://localhost:13000/d/library-services-live
- Prometheus: http://localhost:19090

Grafana username is `admin`. Retrieve its password in your own PowerShell terminal
from the repository root (the password is not stored in this document):

```powershell
$grafanaSecret = kubectl --kubeconfig digital-library/.local/recovery-kubeconfig -n observability get secret grafana-admin -o json | ConvertFrom-Json
[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($grafanaSecret.data.'admin-password'))
```

If the local forwards have stopped, run each command in a separate terminal:

```powershell
kubectl --kubeconfig digital-library/.local/recovery-kubeconfig -n observability port-forward service/library-observability-grafana 13000:80 --address 127.0.0.1
```

```powershell
kubectl --kubeconfig digital-library/.local/recovery-kubeconfig -n observability port-forward service/library-observability-kube-prometheus 19090:9090 --address 127.0.0.1
```

`k8s/platform/library-monitoring.yaml` contains the seven-service PodMonitor and
dashboard. The queries match the services' actual prefixed metric names.
Reservation and Notification now expose `/metrics`, following the other services'
per-app Counter/Histogram implementation with `prometheus-client==0.21.1`.
Their eight service tests passed, including error counting and route templates.

The CRDs were installed with server-side apply. The operator was restarted after
CRD installation because it had started before the required CRDs existed.
`ServerSideApply=true` is included in the local observability Application input
to avoid oversized last-applied annotations during future installations.

The metrics follow-up's two API images were deployed through Argo CD at revision
`d82c552529327125b18d45ed6b4e13b76d512a23` on
`deploy/deploy-20261118203335`. Only Reservation and Notification were rebuilt for
that change. A later automatic-notification update rebuilds Lending/Notification;
its audit also confirms seven healthy targets and Argo CD Synced/Healthy.
The PodMonitor and dashboard were directly applied
using the existing monitoring workflow; they are also saved on that branch.
This does not remove the strict GitOps caveat for platform resources.

The configuration reload took about three minutes after the monitor update.
Verification subsequently confirmed seven healthy targets, all seven public
metrics endpoints, and all five queries through Grafana's Prometheus datasource.
Current evidence is `.local/metrics-verification.json`; the original five-service
baseline remains in `.local/monitoring-verification.json`.
Monitoring storage is ephemeral for this demo; no additional disk or storage
service was provisioned.

## Live autoscaling audit

The complete `.local/final-api-audit.py` now checks seven real scrape targets,
finite request/latency series, CPU and HPA metrics. The successful complete run
passed 146 functional HTTP checks, 37,956 load requests and 79 assertions.
Catalog and Reservation both scaled 1 → 2 → 1; Prometheus recorded their load,
extra scraped replicas and HPA desired-replica history. Argo CD stayed
Synced/Healthy during scale-out.

The first load trial exposed a conflict with Git's fixed `replicas: 1`.
Deployment revision `e51d8c1` removes that field from the two HPA-managed
Deployments so the HPAs own replica counts. The correction was deployed through
Argo CD; targets, requests and min/max replica settings were not changed.

The test uses read-only `/health` requests and waits for automatic scale-down
after the existing 180-second stabilization window. It does not prove business
API capacity. Full evidence is in `.local/final-api-audit.json` under `prometheus`
and `autoscaling`; see [DEMO_AUDIT.md](DEMO_AUDIT.md) for the command and bounds.

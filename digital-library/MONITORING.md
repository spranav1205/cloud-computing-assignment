# AWS monitoring

Verified on 19 November 2026 against the running EKS deployment:

- Prometheus is Ready and its operator reports reconciliation successful.
- Member, Catalog, Lending, Availability and Fine all have healthy scrape targets.
- Real application request counters are present for all five services.
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

`k8s/platform/library-monitoring.yaml` contains the PodMonitor and dashboard.
The queries match the services' actual prefixed metric names. Reservation and
Notification have no `/metrics` endpoint; no service functionality was added.

The CRDs were installed with server-side apply. The operator was restarted after
CRD installation because it had started before the required CRDs existed.
`ServerSideApply=true` is included in the local observability Application input
to avoid oversized last-applied annotations during future installations.

The PodMonitor and dashboard are applied to the cluster. Monitoring source changes
are local only; no further Git push was made after the request to stop Git work.
Verification output is recorded in `.local/monitoring-verification.json`.
Monitoring storage is ephemeral for this demo; no additional disk or storage
service was provisioned.

# One-command AWS demonstration

Verified on 19 November 2026: **146 functional HTTP checks, 37,956 load requests
and 79 assertions passed**. All seven sections passed and cleanup reported no
warnings. Both HPAs scaled **1 → 2 → 1** with Argo CD Synced/Healthy throughout
the observed scale-out. Flink produced both exact window results and completed a
checkpoint before its test application was stopped.
The Flink snapshot also records one failed checkpoint attempt alongside the
completed checkpoint. The audit requires successful persistence, not zero failed
attempts or fault-recovery proof; both counters remain in the evidence.

The complete local runner is `.local/final-api-audit.py`. It contains the API,
notification, gRPC, ZooKeeper, isolated fine, Prometheus, Flink and autoscaling
checks. It uses Python's standard library, AWS CLI and kubectl. Run from the
repository root in your normal PowerShell terminal with the existing AWS profile:

```powershell
python digital-library/.local/final-api-audit.py
if ($LASTEXITCODE -ne 0) { throw 'AWS demonstration failed; inspect the JSON report' }
```

The existing kubeconfig and deployed URL are read from `.local`. The analytics
jar must exist at `services/usage-analytics/target/usage-analytics-1.0.0.jar`; it was
built and unit-tested before the live demonstration. Rebuild it after changing
analytics source. No additional Python packages are needed by the runner.

To repeat only the platform demonstrations:

```powershell
python digital-library/.local/final-api-audit.py --sections metrics,flink,hpa
if ($LASTEXITCODE -ne 0) { throw 'Platform demonstration failed' }
```

## What the runner proves

| Section | Actual checks |
|---|---|
| `api` | All 23 implemented REST business endpoints, validation/conflicts, pagination, FIFO coordination and private S3 byte upload/download/access rejection. Test emails use labeled SES simulator addresses. |
| `grpc` | Member eligibility and unknown-member gRPC responses from Lending, plus a real ZooKeeper connection and reservation lock path. |
| `fine` | Deployed Fine code through loopback HTTP with isolated temporary SQLite; positive overdue and on-time results; no production loan dates changed. |
| `notifications` | Actual Lambda/SES delivery for automatic checkout/return and explicit intake, followed by stable-ID replay suppression. Requires `api` in the same run. |
| `metrics` | Seven healthy real Prometheus scrape targets; finite counters, RPS, latency histograms/p95, CPU and HPA replica series. |
| `flink` | Submits the repository jar to the existing EMR/YARN primary. Injects isolated Kafka fixtures, advances event-time watermarks, checks exact one-minute window counts and distinct members for two books, and requires a RUNNING job with a completed checkpoint. |
| `hpa` | Starts at one replica for Catalog/Reservation, sends sustained rate-capped read-only HTTP requests, requires CPU above target and two ready replicas held for a minute, verifies Prometheus sees load and extra replicas, and checks Argo CD stays Synced/Healthy. Stops load and waits for both HPAs to return to one; retains the Prometheus replica time series. |

## Bounds and evidence

The HPA test leaves min/max replicas at 1/2 and CPU targets at 60%. It sends
`GET /health` traffic through the public frontend proxy, starting at up to 80 RPS
per service and increasing to a ceiling of 160 RPS per service. The default load
budget is four minutes; after observed scale-out it can stop once two replicas
have remained ready for a minute and at least 150 seconds of load have elapsed.
It then waits up to seven minutes for the existing 180-second stabilization
window and metrics/controller delay. It never injects CPU processes or manually
scales Deployments. This proves the scaling mechanism, not business API capacity.

Flink runs on the existing single `m5.xlarge`; EKS stays on its single
`t3.xlarge`. The Flink application is stopped in cleanup. Labeled Kafka input and
result topics and S3 artifacts/checkpoints remain so the results can be inspected.
This is an isolated stream-processing demonstration. Lending/Reservation still
do not automatically publish Kafka domain events.

Current results are saved to `.local/final-api-audit.json`; each run also keeps
its own report, EMR step inputs and diagnostic logs in `.local/audit-runs/RUN_ID/`.
Load requests are aggregated with counts, error rates and bounded latency samples
instead of producing hundreds of thousands of individual JSON entries. Individual
functional HTTP checks retain their expected/actual status codes. A failed section
or cleanup produces exit code 1; independent sections still run and report their
own result.

The runner and evidence are intentionally in the ignored `.local` directory.
Preserve that directory for the demonstration; a fresh clone will not contain it.
AWS infrastructure remains running and consuming credits after the audit.

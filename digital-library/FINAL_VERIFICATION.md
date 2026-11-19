# AWS verification and one-service-at-a-time CLI tests

**19 November 2026.** Tests use the deployed AWS app, not Compose or mocks.
For the final presentation, run `python demo.py` from the repository root. It
contains the same live test functions as the audit below and waits for Enter
before each of seven sections. Type `q` to finish safely; `--auto` skips prompts.
New presentation results use `.local/demo-report.json` and `demo-runs/`; the
original complete audit and its evidence remain available separately.

The complete `.local/final-api-audit.py` now passed **146 functional HTTP checks,
37,956 read-only load requests and 79 assertions**, across API, gRPC/ZooKeeper,
fine, notification, Prometheus, Flink and HPA sections. Both HPAs scaled **1 → 2 → 1**;
Argo CD stayed Synced/Healthy while scaled out. Flink produced exact one-minute
window results for two fixture books and completed a checkpoint on the existing
EMR primary. The audit stopped its Flink application and HTTP load; cleanup passed.
See [interactive demo instructions](README.md#final-terminal-demo) for the one-command demonstration and bounds.
The Flink snapshot records one completed and one failed checkpoint attempt;
zero-failure checkpointing and failure recovery are not asserted.

Post-metrics baseline audit: **144 HTTP requests and 37 assertions passed**, including all **23
implemented REST business endpoints**, validation, pagination, private covers,
loan return, and five concurrent reservations. Usage Analytics is now demonstrated
with isolated Kafka fixtures; Lending/Reservation still have no Kafka publisher.
The original audit made no service/deployment changes. The subsequent metrics
follow-up updates only Reservation/Notification images and the monitoring manifest.
Test calls create labeled demo records; loans are returned and
holds canceled. Member/book/copy/cover records remain because deletion APIs do not exist.

Follow-up verification also passed eight Reservation/Notification service tests,
seven real Prometheus scrape targets, and five Grafana datasource queries. Argo CD
was Synced/Healthy at metrics revision `d82c552` on `deploy/deploy-20261118203335`.
All **13 exact PowerShell blocks below were executed sequentially** against AWS
in one session, including the isolated overdue fixture. The original audit had
35 assertions; the two additional assertions require Reservation/Notification metrics.

The subsequent automatic-notification deployment at `2bc68e7` passed **18 public
HTTP requests and 8 assertions**, plus 14 Lending/Notification container tests.
Checkout and first return now automatically publish `LoanIssued`/`LoanReturned`
to the member's stored email. Both reached the SES simulator before any explicit
notification POST; replaying their stable IDs produced duplicate-suppression logs
and no second delivery. Four concurrent returns produced one return event and
one return timestamp. Argo CD was Synced/Healthy and all seven scrape targets
remained up. See [notification behavior](README.md#services-and-behavior) for policy and reproduction.
The 144-request audit and 13-block CLI run above predate this notification change;
the targeted 18-request audit validates the changed flows. The subsequent complete
146-check/79-assertion audit above also reruns those capabilities in one file.

## Mandatory requirements a–h

| Requirement | Verdict | Evidence / remaining gap |
|---|---|---|
| a. IaC | Core infrastructure verified | Terraform state owns VPC/subnets/routes, EKS, RDS, DynamoDB, S3, IAM, Lambda/SQS and EMR. ALB is controller-created from the Ingress manifest; Helm/Kubernetes bootstrap is separate from Terraform. |
| b. REST + gRPC + queues/serverless | Verified | Real REST calls; Member eligibility gRPC tested from Lending; explicit and automatic checkout/return events → SQS → Lambda → SES simulator delivery confirmed in CloudWatch. |
| c. Managed K8s + two HPAs + load proof | Verified bounded demonstration | Both HPAs scaled 1 → 2 ready replicas under sustained read-only HTTP load and returned to 1 after load stopped. Targets stayed at 60%, min/max 1/2. Prometheus observed rates, CPU and replicas. This tests scaling, not business-endpoint capacity. |
| d. GitOps, no direct service apply | Partial under the strict wording | API Deployments are Argo CD Synced/Healthy. Initial Kafka/ZooKeeper bootstrap and later monitoring resources were directly applied, so do not claim the entire Kubernetes deployment followed a no-`kubectl apply` process. |
| e. Flink consuming Kafka, windowed output | Verified isolated pipeline; publisher integration remains | Real jar ran on existing EMR/YARN, consumed synthetic Kafka input on labeled 3-partition topics, emitted two exact one-minute aggregates with distinct-member counts, and completed a checkpoint. The audit stops its job afterward. Lending/Reservation still have no automatic Kafka publisher; default `.v1` topics are not the fixture topics. |
| f. ZooKeeper concept | Functional evidence verified | Three ZooKeeper pods, configured remote locking, live lock-path read, and five parallel reservation calls produced one READY + four WAITLISTED with FIFO positions/promotion. Cross-replica coordination and failure recovery were not tested. |
| g. Three cloud storage products | Verified | Actual RDS PostgreSQL member/loan/reservation flows; DynamoDB books/copies/GSI; private S3 cover PUT/GET and unsigned 403. |
| h. Observability | Operational | Prometheus/Grafana and real RPS/error/latency/cluster queries work; CloudWatch contains aggregated service log streams. All seven APIs expose metrics after the Reservation/Notification follow-up. |

Stream processing and sustained-load HPA scaling are now demonstrated. Remaining
integration caveats include missing Lending/Reservation Kafka publishers and the
strict GitOps distinction for historical bootstrap/monitoring direct applies.
These bounded tests do not establish fault recovery or business API capacity.

## API/service coverage

| Service | Verified live | Limitation |
|---|---|---|
| Member | All four business endpoints; generated UUID/timestamp, unique email, validation, 404, pagination, no DELETE | None found in tested flows |
| Catalog | All five book/copy endpoints and three cover endpoints; ISBN validation, pagination/GSI, missing-book rejection | Cover API works; the frontend uses styled artwork and has no cover-upload UI. Bucket has no CORS configuration for a future direct browser upload. |
| Reservation | Create/list/get/cancel, duplicate rejection, FIFO/promotion, five concurrent calls; metrics added in follow-up | No multi-replica/failover test |
| Lending | Issue/list/get/return, conflict checks, four concurrent idempotent returns, real gRPC dependency; automatic notifications | Notifications are best-effort after commit; see below. |
| Availability | Before hold, during loan, after return/cancellation; missing/invalid book IDs | Derived state, not a separate write API |
| Fine | Active/returned loan assessment, zero fine, missing/invalid IDs; isolated deployed-code overdue HTTP fixture passed | **A positive overdue fine remains untested through the public ingress.** The isolated fixture runs the deployed code in the existing AWS Fine pod against temporary SQLite, with active/returned overdue loans producing 300 cents. Production RDS loan dates are untouched. |
| Notification | Valid/invalid event POST, metrics, automatic checkout/return delivery, stable-ID replay suppression | Best-effort publishing; no durable outbox. SES recipient restrictions still apply. |
| Usage Analytics | Real EMR/YARN Flink job, input/output offsets, exact window counts and distinct members, completed checkpoint | No REST API by design. Uses isolated synthetic Kafka topics; domain publishers remain absent. Test application is stopped in cleanup. |

## Run the CLI examples

Use **PowerShell from the repository root**, keeping the same terminal so IDs
remain available. Run blocks in order; read-only calls can then be repeated one
at a time. Prerequisites: the running AWS app, `kubectl`, AWS CLI with the existing
account/profile, and `digital-library/.local/recovery-kubeconfig` for cluster checks.
The `/api/...` prefixes below are the frontend proxy; internal service paths
remain `/members`, `/books`, `/reservations`, etc.

### 1. Shared setup and HTTP helpers

```powershell
$ErrorActionPreference = 'Stop'
$Base = 'http://k8s-library-libraryp-5f1873da46-800951354.ap-south-1.elb.amazonaws.com'
$Routes = @{member='member';catalog='catalog';reservation='reservations';lending='loans';availability='availability';fine='fine';notification='notifications'}
$Run = [Guid]::NewGuid().ToString('N')
$Unknown = [Guid]::NewGuid().ToString()
$Kube = 'digital-library/.local/recovery-kubeconfig'
function Api([string]$Service, [string]$Path, [string]$Method='GET', $Body=$null) {
    $request = @{Uri=($Base + '/api/' + $Routes[$Service] + $Path);Method=$Method;TimeoutSec=30}
    if ($null -ne $Body) { $request.ContentType='application/json'; $request.Body=$Body | ConvertTo-Json -Depth 8 -Compress }
    Invoke-RestMethod @request
}
function Expect([string]$Service, [string]$Path, [int]$Expected, [string]$Method='GET', $Body=$null) {
    $request = @{Uri=($Base + '/api/' + $Routes[$Service] + $Path);Method=$Method;TimeoutSec=30;UseBasicParsing=$true}
    if ($null -ne $Body) { $request.ContentType='application/json'; $request.Body=$Body | ConvertTo-Json -Depth 8 -Compress }
    try { $code = [int](Invoke-WebRequest @request).StatusCode }
    catch { if (!$_.Exception.Response) { throw }; $code = [int]$_.Exception.Response.StatusCode }
    if ($code -ne $Expected) { throw "$Service $Method $Path expected $Expected, received $code" }
    "PASS $Service $Method $Path -> $code"
}
```

### 2. Member — register, get, update, list

POST returns 201; GET/PATCH return 200. The two members are needed for FIFO tests.

```powershell
$Member = Api member '/members' POST @{name='CLI Member';email="cli-$Run@example.com"}
$SecondMember = Api member '/members' POST @{name='CLI Waiter';email="waiter-$Run@example.com"}
Api member "/members/$($Member.member_id)"
Api member "/members/$($Member.member_id)" PATCH @{name='CLI Updated';email="updated-$Run@example.com"}
Api member '/members?limit=1&offset=0'
Api member '/members?limit=1&offset=1'
Expect member "/members/$Unknown" 404
Expect member '/members' 422 POST @{name=' ';email='invalid'}
Expect member '/members' 409 POST @{name='Duplicate';email="updated-$Run@example.com"}
Expect member "/members/$($Member.member_id)" 405 DELETE
```

### 3. Catalog — books, physical copies and pagination

Creation returns 201. Copy-GSI reads are eventually consistent; retry the copy
list after a second if a just-created copy has not appeared yet.

```powershell
$Book = Api catalog '/books' POST @{title="CLI Book $Run";author='API Demo';isbn='9780132350884'}
$Copy = Api catalog "/books/$($Book.book_id)/copies" POST
Api catalog "/books/$($Book.book_id)"
$BookPage = Api catalog '/books?limit=1'
$BookPage
if ($BookPage.last_evaluated_key) {
    $token = [Uri]::EscapeDataString(($BookPage.last_evaluated_key | ConvertTo-Json -Compress))
    Api catalog "/books?limit=1&last_evaluated_key=$token"
}
Api catalog "/books/$($Book.book_id)/copies?limit=1"
Expect catalog "/books/$Unknown" 404
Expect catalog "/books/$Unknown/copies" 404 POST
Expect catalog '/books?limit=0' 422
```

### 4. Covers — actual private S3 upload and download

All three cover API calls and signed PUT/GET return 200. The final comparison
must be `True`; the unsigned request must print `403`. Signed URLs are temporary
credentials: use them immediately and do not paste them into shared logs.

```powershell
$Upload = Api catalog "/books/$($Book.book_id)/cover/upload-url" POST @{content_type='image/png'}
$PngBase64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1sAAAAASUVORK5CYII='
$Png = [Convert]::FromBase64String($PngBase64)
$UploadHeaders = @{}
$Upload.headers.PSObject.Properties | Where-Object Name -ne 'Content-Type' | ForEach-Object { $UploadHeaders[$_.Name] = $_.Value }
Invoke-WebRequest -UseBasicParsing -Method PUT -Uri $Upload.upload_url -ContentType 'image/png' -Headers $UploadHeaders -Body $Png | Select-Object StatusCode
Api catalog "/books/$($Book.book_id)/cover/confirm" POST
$Signed = Api catalog "/books/$($Book.book_id)/cover-url"
$CoverFile = "digital-library/.local/cli-cover-$Run.png"
Invoke-WebRequest -UseBasicParsing -Uri $Signed.url -OutFile $CoverFile
[Convert]::ToBase64String([IO.File]::ReadAllBytes((Join-Path (Get-Location) $CoverFile))) -eq $PngBase64
curl.exe --silent --show-error --output NUL --write-out '%{http_code}' (($Signed.url -split '\?')[0])
```

### 5. Availability and Reservation — READY, FIFO waiter, list/detail

Initially availability is 1. The first reservation is READY, the second is
WAITLISTED, and available copies becomes 0.

```powershell
Api availability "/books/$($Book.book_id)/availability"
$HoldBody = @{book_id=$Book.book_id;member_id=$Member.member_id}
$Hold = Api reservation '/reservations' POST $HoldBody
$Waiter = Api reservation '/reservations' POST @{book_id=$Book.book_id;member_id=$SecondMember.member_id}
$Hold.status
$Waiter.status
Api reservation "/reservations/$($Hold.reservation_id)"
Api reservation "/reservations?member_id=$($Member.member_id)&limit=1&offset=0"
Api availability "/books/$($Book.book_id)/availability"
Expect reservation '/reservations' 409 POST $HoldBody
Expect reservation "/reservations/$Unknown" 404
Expect availability "/books/$Unknown/availability" 404
```

### 6. Lending — issue, retrieve, list and conflicts

POST returns 201 and status ACTIVE. Duplicate checkout returns 409.

```powershell
$LoanBody = @{member_id=$Member.member_id;reservation_id=$Hold.reservation_id;copy_id=$Copy.copy_id}
$Loan = Api lending '/loans' POST $LoanBody
Api lending "/loans/$($Loan.loan_id)"
Api lending "/loans?member_id=$($Member.member_id)&active_only=true&limit=1&offset=0"
Api availability "/books/$($Book.book_id)/availability"
Expect lending '/loans' 409 POST $LoanBody
Expect lending "/loans/$Unknown" 404
```

### 7. Fine — assessment, then return and cleanup

A new loan must have `fine_amount_cents=0`. A positive overdue fine requires an
actually overdue loan; this API has no test-time/backdating parameter. Returning
twice must preserve the same return timestamp. The waiter is then promoted to
READY; cancel it to release the copy.

```powershell
Api fine "/loans/$($Loan.loan_id)/fine"
Expect fine "/loans/$Unknown/fine" 404
Expect fine '/loans/not-a-uuid/fine' 422
$Returned = Api lending "/loans/$($Loan.loan_id)/return" POST
$ReturnedAgain = Api lending "/loans/$($Loan.loan_id)/return" POST
$Returned.returned_at -eq $ReturnedAgain.returned_at
Api fine "/loans/$($Loan.loan_id)/fine"
(Api reservation "/reservations/$($Waiter.reservation_id)").status
Api reservation "/reservations/$($Waiter.reservation_id)" DELETE
Api reservation "/reservations/$($Waiter.reservation_id)" DELETE
(Api availability "/books/$($Book.book_id)/availability").available_copies
```

### 8. Notification — enqueue a simulator email

POST returns 202/QUEUED. This tests explicit intake in addition to the automatic
checkout/return flow. The simulator receives no real person's email. The earlier
CLI members use example addresses; their automatic events do not prove SES delivery.
Use the simulator-only audit in [notification behavior](README.md#services-and-behavior) for that proof.

```powershell
$Event = @{event_type='LoanReturned';recipient='success@simulator.amazonses.com';subject="CLI verification $Run";body='AWS API test completed.';member_id=$Member.member_id;occurred_at=[DateTime]::UtcNow.ToString('o')}
$Notification = Api notification '/notifications' POST $Event
$Notification
Expect notification '/notifications' 422 POST @{event_type='LoanReturned';recipient='invalid';body='Invalid test';member_id=$Member.member_id;occurred_at=[DateTime]::UtcNow.ToString('o')}
```

### 9. Common operational endpoints

All seven health/readiness pairs return 200. All seven metrics endpoints return
Prometheus text containing request counters.

```powershell
foreach ($service in ($Routes.Keys | Sort-Object)) {
    [pscustomobject]@{Service=$service;Health=(Api $service '/health').status;Ready=(Api $service '/ready').status}
}
foreach ($service in ($Routes.Keys | Sort-Object)) {
    [pscustomobject]@{Service=$service;HasRequestMetrics=((Api $service '/metrics') -match '_http_requests_total')}
}
```

### 10. Verify the real gRPC path and ZooKeeper

These execute API clients inside existing pods; they do not deploy anything.
Expected: eligible `True`, missing member `MEMBER_NOT_FOUND`, and lock path `True`.

```powershell
@"
import grpc, json
with grpc.insecure_channel('member:50051') as channel:
    call = channel.unary_unary('/library.member.v1.MemberEligibility/CheckoutEligibility', request_serializer=lambda v: json.dumps(v).encode(), response_deserializer=lambda v: json.loads(v.decode()))
    print(call({'member_id': '$($Member.member_id)'}, timeout=10))
    print(call({'member_id': '$Unknown'}, timeout=10))
"@ | kubectl --kubeconfig $Kube -n library exec -i deployment/lending -- python -
@"
import os
from kazoo.client import KazooClient
client = KazooClient(hosts=os.environ['ZOOKEEPER_HOSTS'])
client.start(timeout=10)
try:
    print('Connected:', client.connected, 'Book lock path exists:', bool(client.exists('/library/books/$($Book.book_id)')))
finally:
    client.stop(); client.close()
"@ | kubectl --kubeconfig $Kube -n library exec -i deployment/reservation -- python -
```

### 11. Confirm asynchronous delivery and aggregated logs

Delivery is asynchronous: rerun the first command after a few seconds if it is
initially empty. A matching `notification_delivered` line confirms SES delivery.

```powershell
aws logs filter-log-events --log-group-name /aws/lambda/digital-library-dev-notification --filter-pattern notification_delivered --region ap-south-1 --query "events[?contains(message, '$($Notification.notification_id)')].message" --output json --no-cli-pager
aws logs describe-log-streams --log-group-name /digital-library/eks --order-by LastEventTime --descending --limit 5 --region ap-south-1 --query 'logStreams[].{Stream:logStreamName,LastEvent:lastEventTimestamp}' --output json --no-cli-pager
kubectl --kubeconfig $Kube -n library get hpa
kubectl --kubeconfig $Kube -n argocd get applications
```

### 12. Usage Analytics — inspect Kafka and EMR

The original baseline had no consumer group, nonzero offsets or EMR steps. The
complete audit now submits a real Flink job and validates output on isolated
`library.audit.RUN_ID.events` and `.results` topics. These commands inspect the
default topics and historical EMR steps; they do not submit a job or events.
Use `.local/final-api-audit.json` → `flink` for the exact successful audit's topic
names, application/step IDs, input records, results and checkpoint evidence.
Historical EMR steps also include earlier diagnostic attempts.

```powershell
kubectl --kubeconfig $Kube -n library exec kafka-0 -- /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --list
kubectl --kubeconfig $Kube -n library exec kafka-0 -- /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server kafka:9092 --list
kubectl --kubeconfig $Kube -n library exec kafka-0 -- /opt/kafka/bin/kafka-get-offsets.sh --bootstrap-server kafka:9092 --topic library.events.v1
kubectl --kubeconfig $Kube -n library exec kafka-0 -- /opt/kafka/bin/kafka-get-offsets.sh --bootstrap-server kafka:9092 --topic library.analytics.results.v1
$EmrId = (aws emr list-clusters --active --region ap-south-1 --query "Clusters[?Name=='digital-library-dev-analytics'].Id | [0]" --output text --no-cli-pager).Trim()
aws emr list-steps --cluster-id $EmrId --region ap-south-1 --query 'Steps[].{Name:Name,State:Status.State}' --output json --no-cli-pager
```

### 13. Isolated positive overdue-fine fixture

This runs the deployed Fine code in the existing pod using temporary SQLite and
a loopback-only HTTP server. It does not access RDS or alter production loans,
and is **not** a positive-fine test through the public ingress. Expected: PASS,
three chargeable days/300 cents for active and returned overdue fixtures, zero
for an on-time return, 404 for an unknown loan, and temporary database cleanup.

```powershell
Get-Content digital-library/scripts/verify-overdue-fixture.py -Raw | kubectl --kubeconfig $Kube -n library exec -i deployment/fine -- python -
if ($LASTEXITCODE -ne 0) { throw 'Isolated overdue fixture failed' }
```

Evidence artifacts: `.local/final-api-audit.json` contains the complete current
audit from `.local/final-api-audit.py`, including all seven sections, load/cooldown
samples, Prometheus replica history and Flink results/checkpoints. The successful
run is archived in `.local/audit-runs/616db3cdeb91443e947243b56f23dd58/report.json`.
The original 35-assertion result is archived in `.local/final-api-audit-before-metrics.json`.
`.local/cli-guide-verification.json` and `.local/cli-guide-verification.txt` record
all 13 sequential blocks and actual SES delivery. `.local/metrics-verification.json`
records seven scrape targets and dashboard query results;
`.local/overdue-fixture-verification.json` records the isolated fine cases.
`.local/loan-notifications-verification.json` records the subsequent 18-request
automatic-notification audit, Lambda delivery/duplicate logs, Lending queue logs,
Argo CD health and seven healthy scrape targets.
The current audit includes a bounded HTTP load test. It is not a security,
business-capacity or failover test.

## Remaining decisions and assignment caveats

- Automatic checkout/return notifications are implemented using stored Member
  emails and stable per-loan/event UUIDs. Publishing failures are logged without
  failing the committed loan operation. Delivery is best-effort: crashes/failed
  publishes can lose events; no outbox or new publisher retry design was added.
  Notification failure handling passed container tests, not a forced live outage.
- Positive overdue fines passed the isolated deployed-code fixture, but remain
  untested through public ingress. No production loan dates were changed.
- Usage Analytics has passed a real isolated Flink/Kafka demonstration; automatic
  Lending/Reservation Kafka publishers remain unimplemented.
- Catalog/Reservation HPAs passed sustained read-only load, scale-out, scale-down
  and Prometheus checks. This does not establish business-endpoint capacity.
- API updates use Argo CD; bootstrap/monitoring direct applies remain a strict
  GitOps caveat. Infrastructure was not changed and AWS resources remain running.

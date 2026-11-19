# Automatic loan notifications

Lending publishes `LoanIssued` after a checkout commits, and `LoanReturned` after
the first return commits. It reads the recipient from the Member API's stored
email address. The existing Notification API forwards the event to SQS; the
existing Lambda sends through SES. No new infrastructure or Lambda deployment is
required.

Publishing is synchronous with a two-second timeout per HTTP request and no
publisher retries. Lookup, validation or publish failures are logged as
`notification_publish_failed`; they do not roll back the loan or change its
successful HTTP response. Notification availability is not a readiness condition.
Existing checkout validation and reservation-cancellation failure behavior remain.

Each event uses UUIDv5 with `NAMESPACE_URL` and the name
`digital-library/loans/{loan_id}/{event_type}`. Notification intake accepts the
optional UUID field `event_id` and preserves it as `notification_id` in the SQS
envelope. Requests without `event_id` keep their previous random-ID behavior.
The existing Lambda/DynamoDB consumer suppresses repeats of the same ID within
its 14-day deduplication retention window. Return uses a conditional database
update so concurrent/repeated requests preserve the first return timestamp and
only one caller publishes `LoanReturned`.

This is best-effort delivery, not a durable outbox or an exactly-once guarantee.
A crash between commit and publish, or a failed publish, can lose a notification.
The existing consumer also has a crash window between claiming its deduplication
record and sending email. No new outbox, retry loop or recovery workflow was added.

AWS SES delivery requires permitted recipients for the account's current SES
configuration. Tests use the stored email `success@simulator.amazonses.com` and
never alter an existing member's email. CLI examples using `example.com` members
can exercise the loan APIs without proving automatic email delivery.

## Validation

Verified on AWS on 19 November 2026 after Argo CD deployed notification code
revision `2bc68e7`: **18 HTTP requests and 8 assertions passed**. Both automatic
event IDs reached SES before explicit intake was called. Subsequent ID replays
were suppressed by Lambda; Lending logs confirm one enqueue per transition.
Argo CD was Synced/Healthy and all seven Prometheus targets remained up.

The Notification/Lending container suites pass 14 tests, including concurrent
returns, stable IDs, old intake compatibility, Lambda duplicate suppression, and
successful checkout/return despite Member-email lookup or notification HTTP 503s.

Run the bounded public AWS audit from `digital-library`:

```powershell
$base = (Get-Content .local/deployed-url.txt -Raw).Trim()
python scripts/verify-loan-notifications.py --base-url $base
if ($LASTEXITCODE -ne 0) { throw 'Automatic loan notification audit failed' }
```

The audit creates a labeled book/copy/reservation/loan, verifies automatic delivery
of both event IDs in Lambda logs before making any explicit notification POST,
then replays the IDs and verifies duplicate suppression. It also checks duplicate
checkout rejection, four concurrent returns, and released availability. It returns
the loan and cancels the reservation; member/book/copy records remain because
deletion endpoints do not exist. Evidence is saved to
`.local/loan-notifications-verification.json`.

EKS configures `NOTIFICATION_URL=http://notification:80`; Compose uses
`http://notification:8004`. Only the Lending and Notification images need rebuilding.
Push their digest changes to `deploy/deploy-20261118203335` for Argo CD deployment.

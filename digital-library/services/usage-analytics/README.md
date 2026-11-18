# Usage Analytics Flink Job

The job reads domain events from Kafka topic `library.events.v1`, computes keyed
one-minute event-time aggregates per book, and writes JSON results to the
separate `library.analytics.results.v1` topic. It uses Flink's incremental window
aggregate and retains a set of member IDs for each active book/window to count
distinct borrowers/reservers.

## Event contract

Each Kafka value must be one JSON object with these fields:

```json
{
  "event_type": "ReservationCreated",
  "book_id": "book-uuid",
  "member_id": "member-uuid",
  "occurred_at": "2026-01-01T12:00:01Z"
}
```

Accepted `event_type` values are `ReservationCreated`, `ReservationConflict`,
`LoanCheckedOut`, and `LoanReturned`. `occurred_at` must be an ISO-8601 UTC
timestamp. Events are keyed by `book_id`; windows are UTC-aligned, one-minute
tumbling windows. A 30-second bounded-out-of-orderness watermark allows late
events up to that delay. Invalid records fail the job rather than being silently
discarded.

Each result contains `book_id`, `window_start`, `window_end`,
`reservation_count`, `conflict_count`, `checkout_count`, `return_count`,
`unique_members`, and `total_events`. The Kafka sink is at-least-once; consumers
should deduplicate results by `(book_id, window_start)` if replay-safe writes are
needed. Checkpointing is enabled every 30 seconds.

## Build and test

From this directory, run:

```sh
mvn -B clean verify
```

The resulting shaded job jar is `target/usage-analytics-1.0.0.jar`. The
Dockerfile packages the same jar in the matching Flink 1.20.1 runtime image; the
container is a job artifact and is not included in the EKS Kustomize workload.

## EMR submission

Build and upload the job jar to the approved artifact location, then submit it
from an EMR primary node configured with the matching Flink 1.20 runtime and
network access to Kafka:

```sh
export KAFKA_BOOTSTRAP_SERVERS='broker1:9092,broker2:9092'
export KAFKA_INPUT_TOPIC='library.events.v1'
export KAFKA_RESULTS_TOPIC='library.analytics.results.v1'
export KAFKA_CONSUMER_GROUP='library-usage-analytics'
export KAFKA_CLIENT_PROPERTIES='{}'
flink run -m yarn-cluster -d \
  -c edu.birla.library.analytics.UsageAnalyticsJob \
  /path/to/usage-analytics-1.0.0.jar
```

For authenticated Kafka clusters, supply the connector's Kafka client
properties as JSON in `KAFKA_CLIENT_PROPERTIES` (for example
`security.protocol`, `sasl.mechanism`, and `sasl.jaas.config`) through the
approved secret-delivery mechanism. Do not commit credentials. Ensure the EMR
runtime has the required Kafka connector dependencies via the shaded jar and
the event/results topics exist before submission. The local unit tests validate
the event contract and aggregation; no AWS cluster or Kafka broker is provisioned
or contacted by this repository workflow.

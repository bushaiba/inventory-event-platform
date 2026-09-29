# Architecture

## Local command path

```text
FastAPI / CLI
     |
     v
Command service
     |-- idempotency lookup
     |-- expected-version check
     |
     v
One SQL transaction
     |-- append immutable event
     |-- update current projection
     |-- write command audit
     `-- write outbox row
```

The current projection is fast to query, but it is not the only copy of truth. Every accepted state change also exists in the ordered event stream.

## Stream versioning

Each container is its own stream. Versions start at 1 and increase by one for every event.

A command states the version it expects. The service rejects a stale command instead of applying it against a newer projection.

The database also enforces a unique `(stream_id, stream_version)` constraint.

## Transactional outbox

Publishing is deliberately separated from the inventory write.

If an external broker is unavailable, the event remains committed with an unpublished outbox row. The publisher retries a bounded number of times and moves exhausted messages to a dead-letter table.

This avoids repeating the business write just because downstream delivery failed.

## Replay and reconciliation

```text
Event 1
Event 2
Event 3
  |
  v
latest after_state per stream
  |
  +---- compare ----> current projection
                       |
                       +--> clean
                       `--> drift report / deliberate repair
```

Repair changes only the projection. Historical events are not rewritten.

## Safe undo and restore

Undo is a compensating event, not deletion. It is allowed only when no newer stream version exists after the command being undone.

A timed restore records the version created by the temporary move. When due, the same version check is applied. A newer change turns the restore into a conflict instead of being overwritten.

## AWS reference path

```text
API Gateway
    |
    v
Command Lambda
    |
    v
DynamoDB transaction
  |-- STATE
  |-- EVENT
  `-- IDEMPOTENCY
        |
        +--> DynamoDB Stream --> archive Lambda --> S3

RESTORE item --> EventBridge Scheduler --> restore Lambda --> conditional DynamoDB transaction
```

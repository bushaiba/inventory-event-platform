# Inventory Event Platform

An event-sourced inventory control project built around a simple rule: a write should not be treated as complete just because an API call returned successfully. State changes are versioned, auditable, replayable and checked against the latest state before a stale command can overwrite something newer.

The repository uses **100% synthetic data**. It does not contain Amazon inventory, internal URLs, private APIs, warehouse configuration or copied company code.

## What it does

```text
Command
  |
  v
Version + idempotency checks
  |
  v
Single database transaction
  |-- immutable event
  |-- current-state projection
  |-- command audit
  `-- transactional outbox
              |
              v
        local event bus

Event history ---------> reconciliation replay ---------> drift report / repair

Temporary move --------> scheduled restore ------------> version check before restore
```

The platform includes:

- immutable per-container event history
- current inventory projection
- optimistic concurrency using expected stream versions
- idempotency keys for safe retries
- SKU/location inventory lookup
- transactional outbox pattern
- bounded publisher retries and dead-letter handling
- command audit history
- safe undo using compensating events
- conflict-safe timed restores
- projection replay and reconciliation
- FastAPI endpoints
- SQLite zero-setup mode and PostgreSQL Docker path
- optional AWS serverless deployment code

## Why I built it

Inventory systems have two different problems that are easy to mix together: knowing what the current state is, and being able to prove how that state was reached.

I kept both.

The event log is the historical source of truth. The projection is the fast current view. If the projection drifts, the reconciliation job rebuilds expected state from the events and shows exactly what is different.

For writes, I deliberately use version checks rather than blindly retrying a failed or stale update. A client trying to move version 2 of a container after somebody else has already produced version 3 receives a conflict instead of overwriting version 3.

The same rule is used for undo and timed restore. If newer state exists, the platform stops and asks for review rather than forcing the old state back.

## Quick demo

Python 3.11+ is required.

Windows:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
inventory-platform demo --containers 40 --seed 42
```

macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
inventory-platform demo --containers 40 --seed 42
```

The demo runs with SQLite, creates synthetic containers, moves and adjusts inventory, processes temporary restores, publishes the outbox to a local NDJSON event bus and finishes with a reconciliation check.

Example summary:

```json
{
  "created": 40,
  "moved": 20,
  "adjusted": 13,
  "temporary_moves": 4,
  "restores_completed": 3,
  "restore_conflicts": 1,
  "outbox_published": 76,
  "reconciliation_drift": 0
}
```

## Start the API

```bash
inventory-platform serve
```

Useful routes:

```text
GET  /health
GET  /containers/{container_id}
GET  /containers/{container_id}/events
GET  /inventory/lookup/{sku}
GET  /audit/{command_id}
POST /commands/create
POST /commands/move
POST /commands/adjust
POST /commands/close
POST /commands/undo
POST /restores/process
POST /outbox/publish
POST /reconcile?repair=false
```

## Optimistic concurrency

A move command includes the version the caller believes is current:

```json
{
  "container_id": "CNT-0001",
  "to_location": "LOC-08",
  "expected_version": 2,
  "idempotency_key": "move-2026-09-29-001"
}
```

If the live stream is still version 2, the new event becomes version 3. If another command already created version 3, the move is rejected with a conflict.

This is also why the project does not blindly retry writes.

## Idempotency

Accepted commands store their idempotency key and result. Sending the same command again returns the original result without appending another event.

The event table also has a unique `(stream_id, stream_version)` constraint as a second line of protection.

## Transactional outbox

Each accepted command writes its event, projection update, audit row and outbox message in one database transaction.

Publishing happens separately. A broker outage therefore does not require the inventory write itself to be repeated. Failed publishes use bounded attempts and move to a dead-letter table after the configured limit.

The local publisher appends events to:

```text
data/bus/inventory_events.ndjson
```

## Safe undo

Undo is implemented as a new compensating event. It is allowed only when the container is still at the version produced by the command being undone.

If a newer event exists, undo returns a conflict and leaves the newer state untouched.

## Timed restore

A move can request `restore_after_seconds`. The previous location and the version created by the move are stored in `scheduled_restores`.

When the restore becomes due:

1. current version is checked
2. if it still matches, a normal version-checked move restores the previous location
3. if anything changed in between, the restore is marked `conflict`

No newer state is overwritten.

## Reconciliation

```bash
inventory-platform reconcile
```

This replays every stream from the immutable events and compares the result with `container_projection`.

To repair detected drift deliberately:

```bash
inventory-platform reconcile --repair
```

Repair changes the projection only. It never edits historical events.

## Repository layout

```text
src/inventory_event_platform/
  api/             FastAPI routes
  cli.py           command-line entry point
  config.py        settings
  database.py      event store, projection, audit and outbox tables
  errors.py        domain errors
  models.py        command and state models
  service.py       command handling, undo, restore, outbox and reconciliation
  synthetic.py     deterministic synthetic demo

infrastructure/aws/ optional serverless AWS reference deployment
sql/                example queries
tests/              automated tests
.github/workflows/  CI
```

## Tests and CI

```bash
make quality
```

CI runs Ruff, mypy and pytest with a coverage gate.

The executable tests cover idempotency, stale-write conflicts, undo safety, timed restore conflicts, projection drift repair, outbox publishing/dead letters, lookup, API behaviour and the full synthetic demo.

## Optional AWS path

The local project is the working implementation. `infrastructure/aws` contains a separate serverless reference architecture using:

```text
API Gateway HTTP API
AWS Lambda
DynamoDB + Streams
Amazon S3 event archive
EventBridge Scheduler
CloudWatch
IAM
```

The DynamoDB command path uses conditional writes for optimistic concurrency. Stream records are archived independently to S3, and a scheduled restore worker applies the same expected-version rule before restoring temporary moves.

The AWS code is included to show how the design maps to managed services. This repository does not claim that paid AWS infrastructure has been deployed.

**Do not run `terraform apply` casually. AWS resources can generate charges.**

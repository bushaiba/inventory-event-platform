# Optional AWS deployment

This folder maps the local design to a serverless AWS reference architecture.

It provisions:

- API Gateway HTTP API
- Lambda command handler
- DynamoDB single-table event/state store with Streams
- S3 event archive
- Lambda stream archiver
- EventBridge Scheduler
- conflict-safe restore Lambda
- CloudWatch log groups
- IAM roles scoped to the project resources

## Command path

The command Lambda stores three kinds of DynamoDB items:

```text
CONTAINER#<id> / STATE                  current projection
CONTAINER#<id> / EVENT#<version>#<id>   immutable event
IDEMPOTENCY#<key> / RESULT              accepted command result
```

A move with `restore_after_seconds` also writes a `RESTORE#<id>` item in the same transaction.

State updates use a DynamoDB condition on `version`, so a stale command fails instead of overwriting a newer state.

## Event archive

DynamoDB Streams invokes the archive Lambda. Event rows are copied to S3 using the stable event ID as the object name, making stream retries safe to repeat.

## Timed restore

EventBridge Scheduler invokes the restore worker every few minutes. The worker restores a location only if the live container version still equals the version created by the temporary move. Otherwise it marks the restore as a conflict.

The small reference worker scans due restore items for readability. A higher-volume production design would add a due-time access pattern rather than scanning the table.

## Plan it

```bash
terraform init
terraform plan -var-file=example.tfvars
```

Do not run `terraform apply` unless you intentionally want to create AWS resources and accept the cost.

The local implementation has additional features such as safe undo, transactional SQL outbox/dead-letter handling and full projection repair. The AWS folder demonstrates the managed-service equivalent of the core event/state/versioning design rather than claiming full production parity.

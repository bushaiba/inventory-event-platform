# Data dictionary

## `event_records`

Immutable event history.

| Field | Meaning |
| --- | --- |
| `event_id` | Unique event identifier |
| `stream_id` | Synthetic container identifier |
| `stream_version` | Monotonic version inside the container stream |
| `event_type` | Created, moved, adjusted, closed or compensating undo |
| `occurred_at` | Event timestamp |
| `command_id` | Command that produced the event |
| `payload` | Before/after state plus command-specific context |

## `container_projection`

Fast current-state view rebuilt from the event stream when required.

| Field | Meaning |
| --- | --- |
| `container_id` | Synthetic container ID |
| `sku` | Synthetic SKU |
| `location` | Current synthetic location |
| `quantity` | Current units |
| `status` | `open` or `closed` |
| `version` | Current stream version |
| `last_event_id` | Event that produced the current state |
| `updated_at` | Current projection timestamp |

## `command_audit`

Accepted command history including before/after versions and the stored state needed for idempotent replay and safe undo.

## `outbox_messages`

Messages created in the same transaction as an inventory event. `published_at` remains null until delivery succeeds.

## `dead_letter_messages`

Outbox messages that reached the configured retry limit.

## `scheduled_restores`

Temporary move restore state.

| Field | Meaning |
| --- | --- |
| `source_command_id` | Move command that created the restore |
| `expected_version` | Version that must still be live before restoring |
| `restore_location` | Previous location |
| `due_at` | Earliest restore time |
| `status` | Pending, restored or conflict |

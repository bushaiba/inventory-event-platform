from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from inventory_event_platform.config import Settings
from inventory_event_platform.database import (
    CommandAudit,
    ContainerProjection,
    DeadLetterMessage,
    EventRecord,
    OutboxMessage,
    ScheduledRestore,
    build_session_factory,
)
from inventory_event_platform.errors import ConflictError, NotFoundError, ValidationError
from inventory_event_platform.models import (
    AdjustInventoryCommand,
    CloseContainerCommand,
    CommandResult,
    ContainerState,
    ContainerStatus,
    CreateContainerCommand,
    EventType,
    MoveContainerCommand,
    ReconciliationResult,
    UndoCommand,
)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _state_from_projection(row: ContainerProjection) -> ContainerState:
    return ContainerState(
        container_id=row.container_id,
        sku=row.sku,
        location=row.location,
        quantity=row.quantity,
        status=ContainerStatus(row.status),
        version=row.version,
        last_event_id=row.last_event_id,
        updated_at=row.updated_at,
    )


def _state_payload(state: ContainerState | None) -> dict[str, object] | None:
    return None if state is None else state.model_dump(mode="json")


class InventoryService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.ensure_directories()
        self.engine, self.session_factory = build_session_factory(settings.database_url)

    def close(self) -> None:
        self.engine.dispose()

    def _idempotent_result(self, idempotency_key: str) -> CommandResult | None:
        with self.session_factory() as session:
            audit = session.scalar(
                select(CommandAudit).where(CommandAudit.idempotency_key == idempotency_key)
            )
            if audit is None or audit.status != "accepted":
                return None
            detail = json.loads(audit.detail)
            state = ContainerState.model_validate(detail["after_state"])
            return CommandResult(
                command_id=audit.command_id,
                status="accepted",
                container=state,
                idempotent_replay=True,
                restore_id=detail.get("restore_id"),
            )

    def _current_projection(self, session, container_id: str) -> ContainerProjection:
        row = session.get(ContainerProjection, container_id)
        if row is None:
            raise NotFoundError(f"Container {container_id} was not found.")
        return row

    def _assert_version(self, state: ContainerState, expected_version: int) -> None:
        if state.version != expected_version:
            raise ConflictError(
                f"Version conflict for {state.container_id}: expected {expected_version}, "
                f"current {state.version}."
            )

    def _append_event(
        self,
        session,
        command_id: str,
        event_type: EventType,
        before: ContainerState | None,
        after_values: dict[str, object],
        extra_payload: dict[str, object] | None = None,
    ) -> ContainerState:
        event_id = str(uuid.uuid4())
        occurred_at = _now()
        version = 1 if before is None else before.version + 1
        after = ContainerState(
            container_id=str(after_values["container_id"]),
            sku=str(after_values["sku"]),
            location=str(after_values["location"]),
            quantity=int(after_values["quantity"]),
            status=ContainerStatus(str(after_values["status"])),
            version=version,
            last_event_id=event_id,
            updated_at=occurred_at,
        )
        payload: dict[str, object] = {
            "before_state": _state_payload(before),
            "after_state": _state_payload(after),
        }
        if extra_payload:
            payload.update(extra_payload)

        session.add(
            EventRecord(
                event_id=event_id,
                stream_id=after.container_id,
                stream_version=version,
                event_type=event_type.value,
                occurred_at=occurred_at,
                command_id=command_id,
                payload=json.dumps(payload, separators=(",", ":")),
            )
        )

        projection = session.get(ContainerProjection, after.container_id)
        if projection is None:
            projection = ContainerProjection(container_id=after.container_id)
            session.add(projection)
        projection.sku = after.sku
        projection.location = after.location
        projection.quantity = after.quantity
        projection.status = after.status.value
        projection.version = after.version
        projection.last_event_id = after.last_event_id
        projection.updated_at = after.updated_at

        session.add(
            OutboxMessage(
                event_id=event_id,
                topic="inventory.events",
                payload=json.dumps(
                    {
                        "event_id": event_id,
                        "stream_id": after.container_id,
                        "stream_version": version,
                        "event_type": event_type.value,
                        "occurred_at": occurred_at.isoformat(),
                        "payload": payload,
                    },
                    separators=(",", ":"),
                ),
                created_at=occurred_at,
                attempts=0,
                last_error="",
            )
        )
        return after

    def _record_audit(
        self,
        session,
        command_id: str,
        command_type: str,
        stream_id: str,
        idempotency_key: str,
        before: ContainerState | None,
        after: ContainerState,
        restore_id: int | None = None,
    ) -> None:
        session.add(
            CommandAudit(
                command_id=command_id,
                command_type=command_type,
                stream_id=stream_id,
                idempotency_key=idempotency_key,
                requested_at=_now(),
                status="accepted",
                before_version=None if before is None else before.version,
                after_version=after.version,
                detail=json.dumps(
                    {
                        "before_state": _state_payload(before),
                        "after_state": _state_payload(after),
                        "restore_id": restore_id,
                    },
                    separators=(",", ":"),
                ),
            )
        )

    def create_container(self, command: CreateContainerCommand) -> CommandResult:
        replay = self._idempotent_result(command.idempotency_key)
        if replay:
            return replay

        command_id = str(uuid.uuid4())
        with self.session_factory() as session:
            if session.get(ContainerProjection, command.container_id) is not None:
                raise ConflictError(f"Container {command.container_id} already exists.")

            after = self._append_event(
                session,
                command_id,
                EventType.CONTAINER_CREATED,
                None,
                {
                    "container_id": command.container_id,
                    "sku": command.sku,
                    "location": command.location,
                    "quantity": command.quantity,
                    "status": ContainerStatus.OPEN.value,
                },
            )
            self._record_audit(
                session,
                command_id,
                "create_container",
                command.container_id,
                command.idempotency_key,
                None,
                after,
            )
            session.commit()
        return CommandResult(command_id=command_id, status="accepted", container=after)

    def move_container(self, command: MoveContainerCommand) -> CommandResult:
        replay = self._idempotent_result(command.idempotency_key)
        if replay:
            return replay

        command_id = str(uuid.uuid4())
        with self.session_factory() as session:
            projection = self._current_projection(session, command.container_id)
            before = _state_from_projection(projection)
            self._assert_version(before, command.expected_version)
            if before.status == ContainerStatus.CLOSED:
                raise ValidationError("Closed containers cannot be moved.")

            after = self._append_event(
                session,
                command_id,
                EventType.CONTAINER_MOVED,
                before,
                {
                    "container_id": before.container_id,
                    "sku": before.sku,
                    "location": command.to_location,
                    "quantity": before.quantity,
                    "status": before.status.value,
                },
                {"from_location": before.location, "to_location": command.to_location},
            )

            restore: ScheduledRestore | None = None
            if command.restore_after_seconds is not None:
                restore = ScheduledRestore(
                    stream_id=before.container_id,
                    source_command_id=command_id,
                    expected_version=after.version,
                    restore_location=before.location,
                    due_at=_now() + timedelta(seconds=command.restore_after_seconds),
                    status="pending",
                    detail="",
                )
                session.add(restore)
                session.flush()

            self._record_audit(
                session,
                command_id,
                "move_container",
                before.container_id,
                command.idempotency_key,
                before,
                after,
                None if restore is None else restore.restore_id,
            )
            session.commit()
            restore_id = None if restore is None else restore.restore_id

        return CommandResult(
            command_id=command_id,
            status="accepted",
            container=after,
            restore_id=restore_id,
        )

    def adjust_inventory(self, command: AdjustInventoryCommand) -> CommandResult:
        replay = self._idempotent_result(command.idempotency_key)
        if replay:
            return replay

        command_id = str(uuid.uuid4())
        with self.session_factory() as session:
            before = _state_from_projection(
                self._current_projection(session, command.container_id)
            )
            self._assert_version(before, command.expected_version)
            new_quantity = before.quantity + command.delta
            if new_quantity < 0:
                raise ValidationError("Inventory adjustment would make quantity negative.")

            after = self._append_event(
                session,
                command_id,
                EventType.INVENTORY_ADJUSTED,
                before,
                {
                    "container_id": before.container_id,
                    "sku": before.sku,
                    "location": before.location,
                    "quantity": new_quantity,
                    "status": before.status.value,
                },
                {"delta": command.delta, "reason": command.reason},
            )
            self._record_audit(
                session,
                command_id,
                "adjust_inventory",
                before.container_id,
                command.idempotency_key,
                before,
                after,
            )
            session.commit()
        return CommandResult(command_id=command_id, status="accepted", container=after)

    def close_container(self, command: CloseContainerCommand) -> CommandResult:
        replay = self._idempotent_result(command.idempotency_key)
        if replay:
            return replay

        command_id = str(uuid.uuid4())
        with self.session_factory() as session:
            before = _state_from_projection(
                self._current_projection(session, command.container_id)
            )
            self._assert_version(before, command.expected_version)
            if before.status == ContainerStatus.CLOSED:
                raise ValidationError("Container is already closed.")

            after = self._append_event(
                session,
                command_id,
                EventType.CONTAINER_CLOSED,
                before,
                {
                    "container_id": before.container_id,
                    "sku": before.sku,
                    "location": before.location,
                    "quantity": before.quantity,
                    "status": ContainerStatus.CLOSED.value,
                },
            )
            self._record_audit(
                session,
                command_id,
                "close_container",
                before.container_id,
                command.idempotency_key,
                before,
                after,
            )
            session.commit()
        return CommandResult(command_id=command_id, status="accepted", container=after)

    def undo(self, command: UndoCommand) -> CommandResult:
        replay = self._idempotent_result(command.idempotency_key)
        if replay:
            return replay

        new_command_id = str(uuid.uuid4())
        with self.session_factory() as session:
            original = session.get(CommandAudit, command.command_id)
            if original is None or original.status != "accepted":
                raise NotFoundError(f"Command {command.command_id} was not found.")
            detail = json.loads(original.detail)
            before_payload = detail.get("before_state")
            if before_payload is None:
                raise ValidationError("The original create command cannot be undone.")

            current = _state_from_projection(
                self._current_projection(session, original.stream_id)
            )
            if current.version != original.after_version:
                raise ConflictError(
                    "Undo blocked because the container changed after the original command."
                )
            target = ContainerState.model_validate(before_payload)
            after = self._append_event(
                session,
                new_command_id,
                EventType.COMMAND_UNDONE,
                current,
                {
                    "container_id": target.container_id,
                    "sku": target.sku,
                    "location": target.location,
                    "quantity": target.quantity,
                    "status": target.status.value,
                },
                {"undoes_command_id": original.command_id},
            )
            self._record_audit(
                session,
                new_command_id,
                "undo",
                current.container_id,
                command.idempotency_key,
                current,
                after,
            )
            session.commit()
        return CommandResult(command_id=new_command_id, status="accepted", container=after)

    def get_container(self, container_id: str) -> ContainerState:
        with self.session_factory() as session:
            return _state_from_projection(self._current_projection(session, container_id))

    def lookup_sku(self, sku: str) -> list[ContainerState]:
        with self.session_factory() as session:
            rows = list(
                session.scalars(
                    select(ContainerProjection)
                    .where(ContainerProjection.sku == sku)
                    .order_by(ContainerProjection.location, ContainerProjection.container_id)
                )
            )
            return [_state_from_projection(row) for row in rows]

    def event_history(self, container_id: str) -> list[dict[str, object]]:
        with self.session_factory() as session:
            rows = list(
                session.scalars(
                    select(EventRecord)
                    .where(EventRecord.stream_id == container_id)
                    .order_by(EventRecord.stream_version)
                )
            )
        if not rows:
            raise NotFoundError(f"Container {container_id} was not found.")
        return [
            {
                "event_id": row.event_id,
                "stream_version": row.stream_version,
                "event_type": row.event_type,
                "occurred_at": row.occurred_at.isoformat(),
                "command_id": row.command_id,
                "payload": json.loads(row.payload),
            }
            for row in rows
        ]

    def command_audit(self, command_id: str) -> dict[str, object]:
        with self.session_factory() as session:
            row = session.get(CommandAudit, command_id)
            if row is None:
                raise NotFoundError(f"Command {command_id} was not found.")
            return {
                "command_id": row.command_id,
                "command_type": row.command_type,
                "stream_id": row.stream_id,
                "requested_at": row.requested_at.isoformat(),
                "status": row.status,
                "before_version": row.before_version,
                "after_version": row.after_version,
                "detail": json.loads(row.detail),
            }

    def process_due_restores(self, now: datetime | None = None) -> dict[str, int]:
        now = now or _now()
        with self.session_factory() as session:
            restore_ids = list(
                session.scalars(
                    select(ScheduledRestore.restore_id)
                    .where(
                        ScheduledRestore.status == "pending",
                        ScheduledRestore.due_at <= now,
                    )
                    .order_by(ScheduledRestore.due_at)
                )
            )

        completed = 0
        conflicts = 0
        for restore_id in restore_ids:
            with self.session_factory() as session:
                restore = session.get(ScheduledRestore, restore_id)
                if restore is None or restore.status != "pending":
                    continue
                state = _state_from_projection(
                    self._current_projection(session, restore.stream_id)
                )
                expected_version = restore.expected_version
                restore_location = restore.restore_location

            try:
                result = self.move_container(
                    MoveContainerCommand(
                        container_id=state.container_id,
                        to_location=restore_location,
                        expected_version=expected_version,
                        idempotency_key=f"restore:{restore_id}",
                    )
                )
            except ConflictError as exc:
                with self.session_factory() as session:
                    restore = session.get(ScheduledRestore, restore_id)
                    if restore is not None:
                        restore.status = "conflict"
                        restore.detail = str(exc)
                        session.commit()
                conflicts += 1
                continue

            with self.session_factory() as session:
                restore = session.get(ScheduledRestore, restore_id)
                if restore is not None:
                    restore.status = "restored"
                    restore.completed_command_id = result.command_id
                    restore.detail = "Verified restore applied against the expected version."
                    session.commit()
            completed += 1

        return {"due": len(restore_ids), "completed": completed, "conflicts": conflicts}

    def reconcile(self, repair: bool = False) -> ReconciliationResult:
        with self.session_factory() as session:
            events = list(
                session.scalars(
                    select(EventRecord).order_by(EventRecord.stream_id, EventRecord.stream_version)
                )
            )
            expected: dict[str, ContainerState] = {}
            for event in events:
                payload = json.loads(event.payload)
                expected[event.stream_id] = ContainerState.model_validate(payload["after_state"])

            drift: list[dict[str, object]] = []
            repaired = 0
            for stream_id, expected_state in expected.items():
                projection = session.get(ContainerProjection, stream_id)
                actual = None if projection is None else _state_from_projection(projection)
                if actual is not None and actual.model_dump() == expected_state.model_dump():
                    continue

                drift.append(
                    {
                        "container_id": stream_id,
                        "expected": expected_state.model_dump(mode="json"),
                        "actual": None if actual is None else actual.model_dump(mode="json"),
                    }
                )
                if repair:
                    if projection is None:
                        projection = ContainerProjection(container_id=stream_id)
                        session.add(projection)
                    projection.sku = expected_state.sku
                    projection.location = expected_state.location
                    projection.quantity = expected_state.quantity
                    projection.status = expected_state.status.value
                    projection.version = expected_state.version
                    projection.last_event_id = expected_state.last_event_id
                    projection.updated_at = expected_state.updated_at
                    repaired += 1

            if repair:
                session.commit()

        return ReconciliationResult(
            checked_streams=len(expected),
            drifted_streams=len(drift),
            repaired_streams=repaired,
            drift=drift,
        )

    def publish_outbox(self, publisher: Callable[[str], None]) -> dict[str, int]:
        published = 0
        failed = 0
        dead_lettered = 0

        with self.session_factory() as session:
            ids = list(
                session.scalars(
                    select(OutboxMessage.outbox_id)
                    .where(
                        OutboxMessage.published_at.is_(None),
                        OutboxMessage.attempts < self.settings.outbox_max_attempts,
                    )
                    .order_by(OutboxMessage.outbox_id)
                )
            )

        for outbox_id in ids:
            with self.session_factory() as session:
                message = session.get(OutboxMessage, outbox_id)
                if message is None or message.published_at is not None:
                    continue
                try:
                    publisher(message.payload)
                    message.published_at = _now()
                    message.attempts += 1
                    message.last_error = ""
                    session.commit()
                    published += 1
                except Exception as exc:
                    message.attempts += 1
                    message.last_error = str(exc)
                    failed += 1
                    if message.attempts >= self.settings.outbox_max_attempts:
                        session.add(
                            DeadLetterMessage(
                                outbox_id=message.outbox_id,
                                event_id=message.event_id,
                                payload=message.payload,
                                failed_at=_now(),
                                error=str(exc),
                            )
                        )
                        dead_lettered += 1
                    session.commit()

        return {
            "pending_seen": len(ids),
            "published": published,
            "failed": failed,
            "dead_lettered": dead_lettered,
        }

    def file_publisher(self) -> Callable[[str], None]:
        path: Path = self.settings.bus_path

        def publish(payload: str) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(payload + "\n")

        return publish

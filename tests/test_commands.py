import pytest

from inventory_event_platform.errors import ConflictError
from inventory_event_platform.models import (
    AdjustInventoryCommand,
    CreateContainerCommand,
    MoveContainerCommand,
    UndoCommand,
)


def _create(service, container_id="CNT-0001"):
    return service.create_container(
        CreateContainerCommand(
            container_id=container_id,
            sku="SKU-001",
            location="LOC-01",
            quantity=10,
            idempotency_key=f"create:{container_id}",
        )
    )


def test_idempotency_returns_original_command_result(service):
    first = _create(service)
    second = _create(service)

    assert second.idempotent_replay is True
    assert second.command_id == first.command_id
    assert second.container.version == 1
    assert len(service.event_history("CNT-0001")) == 1


def test_optimistic_version_conflict_blocks_stale_write(service):
    created = _create(service)
    moved = service.move_container(
        MoveContainerCommand(
            container_id="CNT-0001",
            to_location="LOC-02",
            expected_version=created.container.version,
            idempotency_key="move:1",
        )
    )
    assert moved.container.version == 2

    with pytest.raises(ConflictError):
        service.adjust_inventory(
            AdjustInventoryCommand(
                container_id="CNT-0001",
                delta=2,
                expected_version=1,
                reason="stale count",
                idempotency_key="adjust:stale",
            )
        )

    assert service.get_container("CNT-0001").quantity == 10


def test_undo_restores_state_only_when_no_newer_change_exists(service):
    created = _create(service)
    moved = service.move_container(
        MoveContainerCommand(
            container_id="CNT-0001",
            to_location="LOC-02",
            expected_version=created.container.version,
            idempotency_key="move:undoable",
        )
    )
    undone = service.undo(
        UndoCommand(command_id=moved.command_id, idempotency_key="undo:move")
    )

    assert undone.container.location == "LOC-01"
    assert undone.container.version == 3


def test_undo_is_blocked_after_newer_change(service):
    created = _create(service)
    moved = service.move_container(
        MoveContainerCommand(
            container_id="CNT-0001",
            to_location="LOC-02",
            expected_version=created.container.version,
            idempotency_key="move:original",
        )
    )
    service.adjust_inventory(
        AdjustInventoryCommand(
            container_id="CNT-0001",
            delta=3,
            expected_version=moved.container.version,
            reason="cycle count",
            idempotency_key="adjust:newer",
        )
    )

    with pytest.raises(ConflictError):
        service.undo(
            UndoCommand(command_id=moved.command_id, idempotency_key="undo:blocked")
        )

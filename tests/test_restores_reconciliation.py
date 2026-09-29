from datetime import timedelta

from inventory_event_platform.database import ContainerProjection
from inventory_event_platform.models import (
    AdjustInventoryCommand,
    CreateContainerCommand,
    MoveContainerCommand,
)
from inventory_event_platform.service import _now


def _create(service, suffix="1"):
    return service.create_container(
        CreateContainerCommand(
            container_id=f"CNT-{suffix}",
            sku="SKU-RESTORE",
            location="LOC-01",
            quantity=8,
            idempotency_key=f"create:{suffix}",
        )
    )


def test_due_restore_applies_when_version_is_unchanged(service):
    created = _create(service)
    moved = service.move_container(
        MoveContainerCommand(
            container_id=created.container.container_id,
            to_location="LOC-09",
            expected_version=created.container.version,
            idempotency_key="move:temporary",
            restore_after_seconds=10,
        )
    )
    assert moved.restore_id is not None

    summary = service.process_due_restores(now=_now() + timedelta(seconds=20))

    assert summary == {"due": 1, "completed": 1, "conflicts": 0}
    assert service.get_container(created.container.container_id).location == "LOC-01"


def test_due_restore_pauses_on_newer_state(service):
    created = _create(service)
    moved = service.move_container(
        MoveContainerCommand(
            container_id=created.container.container_id,
            to_location="LOC-09",
            expected_version=created.container.version,
            idempotency_key="move:temporary",
            restore_after_seconds=10,
        )
    )
    service.adjust_inventory(
        AdjustInventoryCommand(
            container_id=created.container.container_id,
            delta=1,
            expected_version=moved.container.version,
            reason="newer change",
            idempotency_key="adjust:newer",
        )
    )

    summary = service.process_due_restores(now=_now() + timedelta(seconds=20))

    assert summary == {"due": 1, "completed": 0, "conflicts": 1}
    assert service.get_container(created.container.container_id).location == "LOC-09"


def test_reconciliation_detects_and_repairs_projection_drift(service):
    created = _create(service)

    with service.session_factory() as session:
        projection = session.get(ContainerProjection, created.container.container_id)
        assert projection is not None
        projection.quantity = 999
        session.commit()

    detected = service.reconcile(repair=False)
    repaired = service.reconcile(repair=True)
    clean = service.reconcile(repair=False)

    assert detected.drifted_streams == 1
    assert repaired.repaired_streams == 1
    assert clean.drifted_streams == 0
    assert service.get_container(created.container.container_id).quantity == 8

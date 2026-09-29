from __future__ import annotations

import random
from datetime import timedelta

from inventory_event_platform.models import (
    AdjustInventoryCommand,
    CreateContainerCommand,
    MoveContainerCommand,
)
from inventory_event_platform.service import InventoryService, _now

SKUS = tuple(f"SKU-{index:03d}" for index in range(1, 11))
LOCATIONS = tuple(f"LOC-{index:02d}" for index in range(1, 13))


def seed_demo(service: InventoryService, containers: int = 40, seed: int = 42) -> dict[str, int]:
    rng = random.Random(seed)
    created = 0
    moved = 0
    adjusted = 0
    temporary_moves = 0

    for index in range(1, containers + 1):
        container_id = f"CNT-{index:04d}"
        create_result = service.create_container(
            CreateContainerCommand(
                container_id=container_id,
                sku=SKUS[(index - 1) % len(SKUS)],
                location=LOCATIONS[(index - 1) % len(LOCATIONS)],
                quantity=rng.randint(4, 35),
                idempotency_key=f"demo:create:{container_id}",
            )
        )
        created += 1
        state = create_result.container

        if index % 2 == 0:
            move_result = service.move_container(
                MoveContainerCommand(
                    container_id=container_id,
                    to_location=LOCATIONS[(index + 2) % len(LOCATIONS)],
                    expected_version=state.version,
                    idempotency_key=f"demo:move:{container_id}",
                    restore_after_seconds=30 if index % 10 == 0 else None,
                )
            )
            moved += 1
            temporary_moves += int(index % 10 == 0)
            state = move_result.container

        if index % 3 == 0:
            service.adjust_inventory(
                AdjustInventoryCommand(
                    container_id=container_id,
                    delta=rng.randint(-2, 5),
                    expected_version=state.version,
                    reason="demo cycle count",
                    idempotency_key=f"demo:adjust:{container_id}",
                )
            )
            adjusted += 1

    restore_result = service.process_due_restores(now=_now() + timedelta(minutes=1))
    outbox_result = service.publish_outbox(service.file_publisher())
    reconciliation = service.reconcile()

    return {
        "created": created,
        "moved": moved,
        "adjusted": adjusted,
        "temporary_moves": temporary_moves,
        "restores_completed": restore_result["completed"],
        "restore_conflicts": restore_result["conflicts"],
        "outbox_published": outbox_result["published"],
        "reconciliation_drift": reconciliation.drifted_streams,
    }

from sqlalchemy import func, select

from inventory_event_platform.database import DeadLetterMessage, OutboxMessage
from inventory_event_platform.models import CreateContainerCommand


def _create(service):
    return service.create_container(
        CreateContainerCommand(
            container_id="CNT-OUTBOX",
            sku="SKU-001",
            location="LOC-01",
            quantity=4,
            idempotency_key="outbox:create",
        )
    )


def test_outbox_publishes_once(service, tmp_path):
    _create(service)
    target = tmp_path / "events.ndjson"

    def publisher(payload: str) -> None:
        with target.open("a", encoding="utf-8") as handle:
            handle.write(payload + "\n")

    first = service.publish_outbox(publisher)
    second = service.publish_outbox(publisher)

    assert first["published"] == 1
    assert second["pending_seen"] == 0
    assert len(target.read_text(encoding="utf-8").splitlines()) == 1


def test_outbox_dead_letters_after_bounded_failures(service):
    _create(service)

    def failing_publisher(_: str) -> None:
        raise RuntimeError("simulated broker outage")

    first = service.publish_outbox(failing_publisher)
    second = service.publish_outbox(failing_publisher)
    third = service.publish_outbox(failing_publisher)

    assert first["failed"] == 1
    assert second["dead_lettered"] == 1
    assert third["pending_seen"] == 0

    with service.session_factory() as session:
        dead_letters = session.scalar(select(func.count()).select_from(DeadLetterMessage))
        pending = session.scalar(
            select(func.count())
            .select_from(OutboxMessage)
            .where(OutboxMessage.published_at.is_(None), OutboxMessage.attempts < 2)
        )
    assert dead_letters == 1
    assert pending == 0

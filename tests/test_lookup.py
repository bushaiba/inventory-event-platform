from inventory_event_platform.models import CreateContainerCommand


def test_sku_lookup_groups_current_container_state(service):
    for index, location in enumerate(("LOC-02", "LOC-01"), start=1):
        service.create_container(
            CreateContainerCommand(
                container_id=f"CNT-L{index}",
                sku="SKU-SHARED",
                location=location,
                quantity=index * 5,
                idempotency_key=f"lookup:{index}",
            )
        )

    rows = service.lookup_sku("SKU-SHARED")

    assert [row.location for row in rows] == ["LOC-01", "LOC-02"]
    assert sum(row.quantity for row in rows) == 15

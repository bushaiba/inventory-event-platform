from pathlib import Path

import pytest

from inventory_event_platform.config import Settings
from inventory_event_platform.service import InventoryService


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'inventory.db'}",
        data_dir=tmp_path / "data",
        outbox_max_attempts=2,
    )


@pytest.fixture
def service(settings: Settings):
    instance = InventoryService(settings)
    yield instance
    instance.close()

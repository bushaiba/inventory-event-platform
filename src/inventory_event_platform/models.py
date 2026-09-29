from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ContainerStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class EventType(StrEnum):
    CONTAINER_CREATED = "container_created"
    CONTAINER_MOVED = "container_moved"
    INVENTORY_ADJUSTED = "inventory_adjusted"
    CONTAINER_CLOSED = "container_closed"
    COMMAND_UNDONE = "command_undone"


class CreateContainerCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    container_id: str = Field(min_length=1)
    sku: str = Field(min_length=1)
    location: str = Field(min_length=1)
    quantity: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1)


class MoveContainerCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    container_id: str = Field(min_length=1)
    to_location: str = Field(min_length=1)
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1)
    restore_after_seconds: int | None = Field(default=None, ge=1)


class AdjustInventoryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    container_id: str = Field(min_length=1)
    delta: int
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)


class CloseContainerCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    container_id: str = Field(min_length=1)
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1)


class UndoCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)


class ContainerState(BaseModel):
    container_id: str
    sku: str
    location: str
    quantity: int
    status: ContainerStatus
    version: int
    last_event_id: str
    updated_at: datetime


class CommandResult(BaseModel):
    command_id: str
    status: str
    container: ContainerState
    idempotent_replay: bool = False
    restore_id: int | None = None


class ReconciliationResult(BaseModel):
    checked_streams: int
    drifted_streams: int
    repaired_streams: int
    drift: list[dict[str, object]]

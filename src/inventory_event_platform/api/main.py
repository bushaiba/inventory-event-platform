from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from inventory_event_platform.config import Settings
from inventory_event_platform.errors import ConflictError, NotFoundError, ValidationError
from inventory_event_platform.models import (
    AdjustInventoryCommand,
    CloseContainerCommand,
    CreateContainerCommand,
    MoveContainerCommand,
    UndoCommand,
)
from inventory_event_platform.service import InventoryService


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    service = InventoryService(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            service.close()

    app = FastAPI(
        title="Inventory Event Platform",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.inventory_service = service

    def handle_error(exc: Exception) -> HTTPException:
        if isinstance(exc, NotFoundError):
            return HTTPException(status_code=404, detail=str(exc))
        if isinstance(exc, ConflictError):
            return HTTPException(status_code=409, detail=str(exc))
        if isinstance(exc, ValidationError):
            return HTTPException(status_code=422, detail=str(exc))
        return HTTPException(status_code=500, detail="Unexpected inventory platform error.")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/containers/{container_id}")
    def get_container(container_id: str):
        try:
            return service.get_container(container_id)
        except Exception as exc:
            raise handle_error(exc) from exc

    @app.get("/containers/{container_id}/events")
    def get_events(container_id: str):
        try:
            return service.event_history(container_id)
        except Exception as exc:
            raise handle_error(exc) from exc

    @app.get("/inventory/lookup/{sku}")
    def lookup_sku(sku: str):
        return service.lookup_sku(sku)

    @app.get("/audit/{command_id}")
    def get_audit(command_id: str):
        try:
            return service.command_audit(command_id)
        except Exception as exc:
            raise handle_error(exc) from exc

    @app.post("/commands/create")
    def create_container(command: CreateContainerCommand):
        try:
            return service.create_container(command)
        except Exception as exc:
            raise handle_error(exc) from exc

    @app.post("/commands/move")
    def move_container(command: MoveContainerCommand):
        try:
            return service.move_container(command)
        except Exception as exc:
            raise handle_error(exc) from exc

    @app.post("/commands/adjust")
    def adjust_inventory(command: AdjustInventoryCommand):
        try:
            return service.adjust_inventory(command)
        except Exception as exc:
            raise handle_error(exc) from exc

    @app.post("/commands/close")
    def close_container(command: CloseContainerCommand):
        try:
            return service.close_container(command)
        except Exception as exc:
            raise handle_error(exc) from exc

    @app.post("/commands/undo")
    def undo_command(command: UndoCommand):
        try:
            return service.undo(command)
        except Exception as exc:
            raise handle_error(exc) from exc

    @app.post("/restores/process")
    def process_restores():
        return service.process_due_restores()

    @app.post("/outbox/publish")
    def publish_outbox():
        return service.publish_outbox(service.file_publisher())

    @app.post("/reconcile")
    def reconcile(repair: bool = Query(default=False)):
        return service.reconcile(repair=repair)

    return app


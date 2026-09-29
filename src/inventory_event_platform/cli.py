from __future__ import annotations

import argparse
import json

import uvicorn

from inventory_event_platform.api.main import create_app
from inventory_event_platform.config import Settings
from inventory_event_platform.service import InventoryService
from inventory_event_platform.synthetic import seed_demo


def _demo(args: argparse.Namespace) -> int:
    settings = Settings()
    service = InventoryService(settings)
    try:
        summary = seed_demo(service, containers=args.containers, seed=args.seed)
        print(json.dumps(summary, indent=2))
    finally:
        service.close()
    return 0


def _publish(_: argparse.Namespace) -> int:
    settings = Settings()
    service = InventoryService(settings)
    try:
        print(json.dumps(service.publish_outbox(service.file_publisher()), indent=2))
    finally:
        service.close()
    return 0


def _reconcile(args: argparse.Namespace) -> int:
    settings = Settings()
    service = InventoryService(settings)
    try:
        print(service.reconcile(repair=args.repair).model_dump_json(indent=2))
    finally:
        service.close()
    return 0


def _serve(args: argparse.Namespace) -> int:
    uvicorn.run(create_app(Settings()), host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synthetic inventory event platform")
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("demo", help="Seed synthetic inventory and run reliability jobs")
    demo.add_argument("--containers", type=int, default=40)
    demo.add_argument("--seed", type=int, default=42)
    demo.set_defaults(handler=_demo)

    publish = subparsers.add_parser("publish", help="Publish pending transactional outbox rows")
    publish.set_defaults(handler=_publish)

    reconcile = subparsers.add_parser(
        "reconcile", help="Compare projection state with event history"
    )
    reconcile.add_argument("--repair", action="store_true")
    reconcile.set_defaults(handler=_reconcile)

    serve = subparsers.add_parser("serve", help="Start the FastAPI service")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(handler=_serve)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(args.handler(args))


if __name__ == "__main__":
    main()

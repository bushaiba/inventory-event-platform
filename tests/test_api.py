from fastapi.testclient import TestClient

from inventory_event_platform.api.main import create_app

def test_api_create_lookup_and_conflict(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/commands/create",
            json={
                "container_id": "CNT-API",
                "sku": "SKU-API",
                "location": "LOC-01",
                "quantity": 7,
                "idempotency_key": "api:create",
            },
        )
        assert response.status_code == 200
        assert response.json()["container"]["version"] == 1

        container = client.get("/containers/CNT-API")
        assert container.status_code == 200
        assert container.json()["quantity"] == 7

        lookup = client.get("/inventory/lookup/SKU-API")
        assert lookup.status_code == 200
        assert lookup.json()[0]["container_id"] == "CNT-API"

        events = client.get("/containers/CNT-API/events")
        assert events.status_code == 200
        assert events.json()[0]["event_type"] == "container_created"

        command_id = response.json()["command_id"]
        audit = client.get(f"/audit/{command_id}")
        assert audit.status_code == 200
        assert audit.json()["command_type"] == "create_container"

        publish = client.post("/outbox/publish")
        assert publish.status_code == 200
        assert publish.json()["published"] == 1

        reconcile = client.post("/reconcile?repair=false")
        assert reconcile.status_code == 200
        assert reconcile.json()["drifted_streams"] == 0

        conflict = client.post(
            "/commands/move",
            json={
                "container_id": "CNT-API",
                "to_location": "LOC-02",
                "expected_version": 99,
                "idempotency_key": "api:stale",
            },
        )
        assert conflict.status_code == 409



def test_health_endpoint(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        missing = client.get("/containers/DOES-NOT-EXIST")
        assert missing.status_code == 404

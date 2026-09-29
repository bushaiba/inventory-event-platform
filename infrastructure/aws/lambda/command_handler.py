import json
import os
import uuid
from datetime import UTC, datetime

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

TABLE_NAME = os.environ["TABLE_NAME"]
table = boto3.resource("dynamodb").Table(TABLE_NAME)
client = boto3.client("dynamodb")
serializer = TypeSerializer()


def now_iso():
    return datetime.now(UTC).isoformat()


def encode_item(item):
    return {key: serializer.serialize(value) for key, value in item.items()}


def response(status, body):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def state_key(container_id):
    return {"pk": f"CONTAINER#{container_id}", "sk": "STATE"}


def get_state(container_id):
    result = table.get_item(Key=state_key(container_id), ConsistentRead=True)
    return result.get("Item")


def existing_idempotency(key):
    result = table.get_item(
        Key={"pk": f"IDEMPOTENCY#{key}", "sk": "RESULT"},
        ConsistentRead=True,
    )
    item = result.get("Item")
    return None if item is None else json.loads(item["response_json"])


def event_item(container_id, version, event_id, command_id, event_type, before, after):
    return {
        "pk": f"CONTAINER#{container_id}",
        "sk": f"EVENT#{version:010d}#{event_id}",
        "entity_type": "event",
        "event_id": event_id,
        "stream_version": version,
        "event_type": event_type,
        "command_id": command_id,
        "occurred_at": now_iso(),
        "before_state": before,
        "after_state": after,
    }


def idem_item(key, body):
    return {
        "pk": f"IDEMPOTENCY#{key}",
        "sk": "RESULT",
        "entity_type": "idempotency",
        "response_json": json.dumps(body, default=str),
        "created_at": now_iso(),
    }


def handle_create(body):
    idem = existing_idempotency(body["idempotency_key"])
    if idem is not None:
        idem["idempotent_replay"] = True
        return response(200, idem)

    container_id = body["container_id"]
    command_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    after = {
        "container_id": container_id,
        "sku": body["sku"],
        "location": body["location"],
        "quantity": int(body["quantity"]),
        "status": "open",
        "version": 1,
        "last_event_id": event_id,
    }
    state = {
        **state_key(container_id),
        "entity_type": "state",
        **after,
        "gsi1pk": f"SKU#{after['sku']}",
        "gsi1sk": f"LOCATION#{after['location']}#CONTAINER#{container_id}",
        "updated_at": now_iso(),
    }
    result = {
        "command_id": command_id,
        "status": "accepted",
        "container": after,
        "idempotent_replay": False,
    }
    transact = [
        {
            "Put": {
                "TableName": TABLE_NAME,
                "Item": encode_item(state),
                "ConditionExpression": "attribute_not_exists(pk)",
            }
        },
        {
            "Put": {
                "TableName": TABLE_NAME,
                "Item": encode_item(
                    event_item(container_id, 1, event_id, command_id, "container_created", None, after)
                ),
            }
        },
        {
            "Put": {
                "TableName": TABLE_NAME,
                "Item": encode_item(idem_item(body["idempotency_key"], result)),
                "ConditionExpression": "attribute_not_exists(pk)",
            }
        },
    ]
    try:
        client.transact_write_items(TransactItems=transact)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "TransactionCanceledException":
            return response(409, {"detail": "Container already exists or command conflicted."})
        raise
    return response(200, result)


def handle_update(body, action):
    idem = existing_idempotency(body["idempotency_key"])
    if idem is not None:
        idem["idempotent_replay"] = True
        return response(200, idem)

    container_id = body["container_id"]
    before = get_state(container_id)
    if before is None:
        return response(404, {"detail": "Container not found."})
    expected = int(body["expected_version"])
    if int(before["version"]) != expected:
        return response(409, {"detail": f"Expected version {expected}, current {before['version']}."})
    if before["status"] == "closed" and action != "close":
        return response(422, {"detail": "Closed containers cannot be changed."})

    command_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    version = expected + 1
    after = {
        "container_id": container_id,
        "sku": before["sku"],
        "location": before["location"],
        "quantity": int(before["quantity"]),
        "status": before["status"],
        "version": version,
        "last_event_id": event_id,
    }
    event_type = ""
    update_expression = ""
    names = {"#version": "version", "#status": "status"}
    values = {
        ":expected": expected,
        ":version": version,
        ":event": event_id,
        ":updated": now_iso(),
    }

    if action == "move":
        after["location"] = body["to_location"]
        event_type = "container_moved"
        values[":location"] = after["location"]
        values[":gsi1sk"] = f"LOCATION#{after['location']}#CONTAINER#{container_id}"
        update_expression = (
            "SET location=:location, gsi1sk=:gsi1sk, #version=:version, "
            "last_event_id=:event, updated_at=:updated"
        )
    elif action == "adjust":
        quantity = int(before["quantity"]) + int(body["delta"])
        if quantity < 0:
            return response(422, {"detail": "Adjustment would make quantity negative."})
        after["quantity"] = quantity
        event_type = "inventory_adjusted"
        values[":quantity"] = quantity
        update_expression = (
            "SET quantity=:quantity, #version=:version, last_event_id=:event, updated_at=:updated"
        )
    elif action == "close":
        if before["status"] == "closed":
            return response(422, {"detail": "Container is already closed."})
        after["status"] = "closed"
        event_type = "container_closed"
        values[":status"] = "closed"
        update_expression = (
            "SET #status=:status, #version=:version, last_event_id=:event, updated_at=:updated"
        )
    else:
        return response(400, {"detail": "Unsupported command."})

    result = {
        "command_id": command_id,
        "status": "accepted",
        "container": after,
        "idempotent_replay": False,
    }
    transact = [
        {
            "Update": {
                "TableName": TABLE_NAME,
                "Key": encode_item(state_key(container_id)),
                "UpdateExpression": update_expression,
                "ConditionExpression": "#version = :expected",
                "ExpressionAttributeNames": names,
                "ExpressionAttributeValues": encode_item(values),
            }
        },
        {
            "Put": {
                "TableName": TABLE_NAME,
                "Item": encode_item(
                    event_item(container_id, version, event_id, command_id, event_type, before, after)
                ),
            }
        },
        {
            "Put": {
                "TableName": TABLE_NAME,
                "Item": encode_item(idem_item(body["idempotency_key"], result)),
                "ConditionExpression": "attribute_not_exists(pk)",
            }
        },
    ]

    restore_seconds = body.get("restore_after_seconds") if action == "move" else None
    if restore_seconds:
        restore_id = str(uuid.uuid4())
        restore = {
            "pk": f"RESTORE#{restore_id}",
            "sk": "PENDING",
            "entity_type": "restore",
            "restore_id": restore_id,
            "container_id": container_id,
            "restore_location": before["location"],
            "expected_version": version,
            "due_epoch": int(datetime.now(UTC).timestamp()) + int(restore_seconds),
            "status": "pending",
        }
        result["restore_id"] = restore_id
        transact.append({"Put": {"TableName": TABLE_NAME, "Item": encode_item(restore)}})
        transact[2]["Put"]["Item"] = encode_item(idem_item(body["idempotency_key"], result))

    try:
        client.transact_write_items(TransactItems=transact)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "TransactionCanceledException":
            return response(409, {"detail": "State changed before the command could be committed."})
        raise
    return response(200, result)


def handler(event, _context):
    route = event.get("routeKey", "")
    if route == "GET /health":
        return response(200, {"status": "ok"})

    path = event.get("pathParameters") or {}
    if route == "GET /containers/{container_id}":
        item = get_state(path["container_id"])
        return response(404, {"detail": "Container not found."}) if item is None else response(200, item)

    if route == "GET /containers/{container_id}/events":
        container_id = path["container_id"]
        result = table.query(
            KeyConditionExpression=Key("pk").eq(f"CONTAINER#{container_id}")
            & Key("sk").begins_with("EVENT#")
        )
        return response(200, result.get("Items", []))

    if route == "GET /inventory/lookup/{sku}":
        result = table.query(
            IndexName="gsi1",
            KeyConditionExpression=Key("gsi1pk").eq(f"SKU#{path['sku']}"),
        )
        return response(200, result.get("Items", []))

    body = json.loads(event.get("body") or "{}")
    required = {"idempotency_key", "container_id"}
    if not required.issubset(body):
        return response(400, {"detail": "container_id and idempotency_key are required."})

    if route == "POST /commands/create":
        return handle_create(body)
    if route == "POST /commands/move":
        return handle_update(body, "move")
    if route == "POST /commands/adjust":
        return handle_update(body, "adjust")
    if route == "POST /commands/close":
        return handle_update(body, "close")
    return response(404, {"detail": "Route not found."})

import os
import time
import uuid
from datetime import UTC, datetime

import boto3
from boto3.dynamodb.conditions import Attr
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

TABLE_NAME = os.environ["TABLE_NAME"]
table = boto3.resource("dynamodb").Table(TABLE_NAME)
client = boto3.client("dynamodb")
serializer = TypeSerializer()


def encode(item):
    return {key: serializer.serialize(value) for key, value in item.items()}


def now_iso():
    return datetime.now(UTC).isoformat()


def handler(_event, _context):
    now_epoch = int(time.time())
    result = table.scan(
        FilterExpression=Attr("entity_type").eq("restore")
        & Attr("status").eq("pending")
        & Attr("due_epoch").lte(now_epoch)
    )
    restored = 0
    conflicts = 0

    for restore in result.get("Items", []):
        container_id = restore["container_id"]
        state_key = {"pk": f"CONTAINER#{container_id}", "sk": "STATE"}
        state = table.get_item(Key=state_key, ConsistentRead=True).get("Item")
        expected = int(restore["expected_version"])
        if state is None or int(state["version"]) != expected:
            table.update_item(
                Key={"pk": restore["pk"], "sk": restore["sk"]},
                UpdateExpression="SET #status=:status, detail=:detail",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":status": "conflict",
                    ":detail": "Live version changed before restore.",
                },
            )
            conflicts += 1
            continue

        event_id = str(uuid.uuid4())
        command_id = f"restore:{restore['restore_id']}"
        version = expected + 1
        before = {
            "container_id": container_id,
            "sku": state["sku"],
            "location": state["location"],
            "quantity": int(state["quantity"]),
            "status": state["status"],
            "version": expected,
            "last_event_id": state["last_event_id"],
        }
        after = {
            **before,
            "location": restore["restore_location"],
            "version": version,
            "last_event_id": event_id,
        }
        event_item = {
            "pk": f"CONTAINER#{container_id}",
            "sk": f"EVENT#{version:010d}#{event_id}",
            "entity_type": "event",
            "event_id": event_id,
            "stream_version": version,
            "event_type": "container_moved",
            "command_id": command_id,
            "occurred_at": now_iso(),
            "before_state": before,
            "after_state": after,
        }
        values = {
            ":expected": expected,
            ":version": version,
            ":location": restore["restore_location"],
            ":gsi1sk": f"LOCATION#{restore['restore_location']}#CONTAINER#{container_id}",
            ":event": event_id,
            ":updated": now_iso(),
        }
        try:
            client.transact_write_items(
                TransactItems=[
                    {
                        "Update": {
                            "TableName": TABLE_NAME,
                            "Key": encode(state_key),
                            "UpdateExpression": (
                                "SET location=:location, gsi1sk=:gsi1sk, #version=:version, "
                                "last_event_id=:event, updated_at=:updated"
                            ),
                            "ConditionExpression": "#version=:expected",
                            "ExpressionAttributeNames": {"#version": "version"},
                            "ExpressionAttributeValues": encode(values),
                        }
                    },
                    {"Put": {"TableName": TABLE_NAME, "Item": encode(event_item)}},
                    {
                        "Update": {
                            "TableName": TABLE_NAME,
                            "Key": encode({"pk": restore["pk"], "sk": restore["sk"]}),
                            "UpdateExpression": "SET #status=:status, completed_command_id=:command",
                            "ConditionExpression": "#status=:pending",
                            "ExpressionAttributeNames": {"#status": "status"},
                            "ExpressionAttributeValues": encode(
                                {
                                    ":status": "restored",
                                    ":pending": "pending",
                                    ":command": command_id,
                                }
                            ),
                        }
                    },
                ]
            )
            restored += 1
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "TransactionCanceledException":
                raise
            table.update_item(
                Key={"pk": restore["pk"], "sk": restore["sk"]},
                UpdateExpression="SET #status=:status, detail=:detail",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":status": "conflict",
                    ":detail": "State changed during restore transaction.",
                },
            )
            conflicts += 1

    return {"due": len(result.get("Items", [])), "restored": restored, "conflicts": conflicts}

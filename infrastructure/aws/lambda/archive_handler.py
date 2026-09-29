import json
import os
from datetime import UTC, datetime

import boto3
from boto3.dynamodb.types import TypeDeserializer

BUCKET = os.environ["ARCHIVE_BUCKET"]
s3 = boto3.client("s3")
deserializer = TypeDeserializer()


def decode(image):
    return {key: deserializer.deserialize(value) for key, value in image.items()}


def handler(event, _context):
    archived = 0
    for record in event.get("Records", []):
        image = record.get("dynamodb", {}).get("NewImage")
        if not image:
            continue
        item = decode(image)
        if item.get("entity_type") != "event":
            continue
        occurred = item.get("occurred_at", datetime.now(UTC).isoformat())
        day = str(occurred)[:10].replace("-", "/")
        key = f"events/{day}/{item['event_id']}.json"
        s3.put_object(
            Bucket=BUCKET,
            Key=key,
            Body=json.dumps(item, default=str).encode("utf-8"),
            ContentType="application/json",
        )
        archived += 1
    return {"archived": archived}

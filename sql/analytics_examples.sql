-- Current inventory by SKU and location
SELECT
    sku,
    location,
    COUNT(*) AS containers,
    SUM(quantity) AS units
FROM container_projection
GROUP BY sku, location
ORDER BY sku, location;

-- Event history for one stream
SELECT
    stream_version,
    event_type,
    occurred_at,
    command_id,
    payload
FROM event_records
WHERE stream_id = 'CNT-0001'
ORDER BY stream_version;

-- Outbox health
SELECT
    COUNT(*) FILTER (WHERE published_at IS NULL) AS unpublished,
    COUNT(*) FILTER (WHERE published_at IS NOT NULL) AS published,
    MAX(attempts) AS max_attempts
FROM outbox_messages;

-- Timed restores requiring review
SELECT *
FROM scheduled_restores
WHERE status = 'conflict'
ORDER BY due_at DESC;

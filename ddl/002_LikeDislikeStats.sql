-- Like / dislike votes per module item, written through POST /stats/.
-- Snapshot of the hand-created production table (SHOW CREATE TABLE), kept idempotent.
CREATE TABLE IF NOT EXISTS LikeDislikeStats
(
    `id` UInt64,
    `module` LowCardinality(String),
    `type` UInt8 DEFAULT 1,
    `value` UInt8
)
ENGINE = MergeTree
ORDER BY id
SETTINGS index_granularity = 8192

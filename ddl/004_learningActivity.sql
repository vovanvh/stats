-- One row per learning action (answer, review, lesson step), written through POST /stats/.
-- ts is UTC; send it as unix epoch seconds (an ISO string fails the insert).
-- result: -1 not graded, 0 wrong, 1 correct.
CREATE TABLE IF NOT EXISTS learningActivity
(
    `externalId` Int64,
    `languageId` Int8,
    `activityType` LowCardinality(String),
    `entityId` Int64 DEFAULT 0,
    `ts` DateTime('UTC'),
    `result` Int8 DEFAULT -1
)
ENGINE = MergeTree
ORDER BY (externalId, ts)
SETTINGS index_granularity = 8192

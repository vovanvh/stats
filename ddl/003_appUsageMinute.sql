-- One row per minute a user had the app open, written through POST /stats/.
-- minuteTs is UTC truncated to the minute; send it as unix epoch seconds (an ISO string fails the insert).
-- ReplacingMergeTree collapses repeated (externalId, languageId, minuteTs) rows on merge; reads still use uniqExact(minuteTs).
CREATE TABLE IF NOT EXISTS appUsageMinute
(
    `externalId` Int64,
    `languageId` Int8,
    `minuteTs` DateTime('UTC'),
    `platform` LowCardinality(String),
    `appVersion` LowCardinality(String)
)
ENGINE = ReplacingMergeTree
ORDER BY (externalId, languageId, minuteTs)
SETTINGS index_granularity = 8192

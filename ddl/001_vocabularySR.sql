-- Spaced-repetition state per word, written by my-nest-voc through POST /stats/.
-- Snapshot of the hand-created production table (SHOW CREATE TABLE), kept idempotent.
CREATE TABLE IF NOT EXISTS vocabularySR
(
    `language` Int8,
    `translationLanguage` Int8,
    `wordId` Int64,
    `externalId` Int64,
    `interval` Int32,
    `repetitions` Int32,
    `lastRes` Int32,
    `timestampAdded` Int64,
    `timestampUpdated` Int64,
    `nextStartTS` Int64,
    `type` Int8
)
ENGINE = MergeTree
ORDER BY (externalId, language, translationLanguage, wordId, type)
SETTINGS index_granularity = 8192

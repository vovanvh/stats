-- Adds the CEFR levels and a numeric score to learningActivity (VBM-585).
-- materialLevel / learnerLevel: CEFR label 'A1'..'C2'; '' = unknown (rows written before this file stay '').
-- score: 0-100, NULL = not scored; the -1/0/1 `result` column is unchanged.
-- ADD COLUMN IF NOT EXISTS keeps this file idempotent, so apply_ddl.py may re-run it on every deploy.
ALTER TABLE learningActivity
    ADD COLUMN IF NOT EXISTS `materialLevel` LowCardinality(String) DEFAULT '',
    ADD COLUMN IF NOT EXISTS `learnerLevel` LowCardinality(String) DEFAULT '',
    ADD COLUMN IF NOT EXISTS `score` Nullable(UInt8)

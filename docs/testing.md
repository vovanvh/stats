# Testing

pytest suites under `tests/`. Every suite uses a router-only FastAPI app, so `main.py` (Playwright, Tor) is
never imported.

## Commands

The dev image may lack the dev dependencies; install them first.

```bash
# Unit suites (stubbed ClickHouse client)
docker exec krys-stats sh -c 'pip install -q -r requirements-dev.txt && python -m pytest -q tests'

# Unit + integration against the dev ClickHouse (v_clickhouse on devnetwork)
docker exec krys-stats sh -c 'STATS_IT=1 python -m pytest -q tests'
```

The integration suite creates the database `stats_test`, applies `ddl/` through `scripts/apply_ddl.py` (twice,
to prove it is idempotent) and drops the database afterwards. Without `STATS_IT=1` it is skipped.

## Suites

### `tests/test_stats.py` — `POST /stats/`
- `LikeDislikeStats` and `vocabularySR` rows are inserted with sorted columns.
- Arbitrary table and column names are accepted; the table name is stripped.
- Missing / empty / qualified / injected table names, bad column keys and empty `data` are 422.
- An insert failure is a 500 carrying the ClickHouse message.

### `tests/test_activity_summary.py` — activity summary (stubbed client)
- `compute_streak`: ends today, ends yesterday, 0 when neither is active, stops at a gap, capped at `STREAK_LOOKBACK_DAYS`.
- `accuracy` is null without graded answers and counts only the current week.
- `last7Days` has `WEEK_LENGTH_DAYS` entries, oldest first, with per-day `active` / `minutes`.
- `minutesThisWeek` follows `weekStart` (monday vs sunday).
- A minutes-only day is not active.
- The calendar query receives the `WEEK_START_MODES` mode, `STREAK_LOOKBACK_DAYS` and `WEEK_LENGTH_DAYS - 1`.
- An unknown zone falls back to `UTC` in every query; zone lookups are cached.
- Endpoint: default `weekStart`, reported fallback zone, 422 on missing fields / bad `weekStart`, 500 with detail on a ClickHouse error.

### `tests/test_apply_ddl.py` — DDL sorting-key guard (stubbed client)
- `expected_sorting_key` handles a bare `ORDER BY id` and a whitespace-normalised tuple key; no `ORDER BY` raises.
- `table_name` reads the table of a `CREATE TABLE IF NOT EXISTS` statement.
- The repo's `appUsageMinute` file is keyed `externalId, languageId, minuteTs`.
- `verify_sorting_keys` passes on a match and raises on a stale key or a missing table.

### `tests/integration/test_activity_summary_clickhouse.py` — real ClickHouse (`STATS_IT=1`)
- `ddl/` creates exactly the four tables on a fresh database; `appUsageMinute` is keyed `externalId, languageId, minuteTs`.
- DST spring (`Europe/Berlin`, 2026-03-29): 00:30-local rows land on the local day; streak, minutes, accuracy.
- The same rows read in `UTC` land on the UTC days.
- DST autumn (2026-10-25): 00:30-local rows before and after the switch land on the local days.
- The same `minuteTs` inserted twice counts once, before and after `OPTIMIZE ... FINAL`.
- A minutes-only day is not active; accuracy is null.
- Streak ending yesterday.
- Language isolation: rows in language 2 never change language 1 numbers.
- Language isolation survives a merge: the same `minuteTs` in two languages is still one minute each after `OPTIMIZE ... FINAL`.
- Unknown zone falls back to `UTC`.

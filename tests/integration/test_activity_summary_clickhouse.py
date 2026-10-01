"""
Real-ClickHouse fixture suite for the activity summary and the ddl/ files.

Runs only with STATS_IT=1; creates the database `stats_test`, applies ddl/ through
scripts/apply_ddl.py and drops the database afterwards.
"""
import os
from datetime import datetime, timezone

import pytest

from app.database import get_clickhouse_client
from app.services import activity_summary as svc
from app.services.activity_summary import (
    APP_USAGE_MINUTE_TABLE,
    DEFAULT_TIME_ZONE,
    LEARNING_ACTIVITY_TABLE,
    WEEK_LENGTH_DAYS,
    build_summary,
)
from scripts.apply_ddl import apply_ddl, list_ddl_files

pytestmark = pytest.mark.skipif(os.getenv("STATS_IT") != "1", reason="set STATS_IT=1 to run against ClickHouse")

TEST_DATABASE = "stats_test"
BERLIN = "Europe/Berlin"
LANG = 1
OTHER_LANG = 2
NOT_GRADED, WRONG, CORRECT = -1, 0, 1
ACTIVITY_COLUMNS = ["externalId", "languageId", "activityType", "entityId", "ts", "result"]
MINUTE_COLUMNS = ["externalId", "languageId", "minuteTs", "platform", "appVersion"]
EXPECTED_TABLES = {"vocabularySR", "LikeDislikeStats", APP_USAGE_MINUTE_TABLE, LEARNING_ACTIVITY_TABLE}
APP_USAGE_MINUTE_KEY = "externalId, languageId, minuteTs"


def utc(text: str) -> int:
    """Epoch seconds of a 'YYYY-MM-DD HH:MM' UTC timestamp (the writer contract for DateTime columns)."""
    return int(datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp())


@pytest.fixture(scope="module")
def client():
    """Fresh `stats_test` database with ddl/ applied; dropped after the module."""
    admin = get_clickhouse_client()
    admin.command(f"DROP DATABASE IF EXISTS {TEST_DATABASE}")
    apply_ddl(TEST_DATABASE)
    # A second run must be a no-op (idempotent DDL)
    apply_ddl(TEST_DATABASE)
    yield get_clickhouse_client(TEST_DATABASE)
    admin.command(f"DROP DATABASE IF EXISTS {TEST_DATABASE}")


@pytest.fixture(autouse=True)
def clear_zone_cache():
    """Each test resolves time zones against the real server."""
    svc._known_time_zones.clear()


def add_activity(client, external_id, rows):
    """Insert (languageId, ts, result) learning actions for one user."""
    data = [[external_id, lang, "word_review", 0, ts, result] for lang, ts, result in rows]
    client.insert(LEARNING_ACTIVITY_TABLE, data, ACTIVITY_COLUMNS)


def add_minutes(client, external_id, rows):
    """Insert (languageId, minuteTs) app-usage minutes for one user."""
    data = [[external_id, lang, ts, "ios", "1.0.0"] for lang, ts in rows]
    client.insert(APP_USAGE_MINUTE_TABLE, data, MINUTE_COLUMNS)


def merge_minutes(client):
    """Force the ReplacingMergeTree merge so duplicate collapsing is observable."""
    client.command(f"OPTIMIZE TABLE {APP_USAGE_MINUTE_TABLE} FINAL")


def active_dates(summary):
    """ISO dates marked active in last7Days."""
    return [d["date"] for d in summary["last7Days"] if d["active"]]


def test_ddl_creates_all_tables(client):
    tables = {row[0] for row in client.query("SHOW TABLES").result_rows}

    assert tables == EXPECTED_TABLES
    assert len(list_ddl_files()) == len(EXPECTED_TABLES)
    key = client.query(
        "SELECT sorting_key FROM system.tables WHERE database = {db:String} AND name = {t:String}",
        parameters={"db": TEST_DATABASE, "t": APP_USAGE_MINUTE_TABLE},
    ).result_rows[0][0]
    assert key == APP_USAGE_MINUTE_KEY


def test_dst_spring_and_local_00_30(client):
    user = 101
    # 2026-03-29: Berlin switches CET -> CEST; both 00:30-local rows are the previous UTC day
    add_activity(client, user, [
        (LANG, utc("2026-03-28 10:00"), CORRECT),
        (LANG, utc("2026-03-28 23:30"), CORRECT),
        (LANG, utc("2026-03-29 22:30"), WRONG),
    ])
    add_minutes(client, user, [(LANG, utc("2026-03-29 22:30")), (LANG, utc("2026-03-29 22:31"))])

    summary = build_summary(client, user, LANG, BERLIN, "monday", utc("2026-03-30 10:00"))

    assert active_dates(summary) == ["2026-03-28", "2026-03-29", "2026-03-30"]
    assert summary["currentStreak"] == 3
    assert summary["activeToday"] is True
    assert summary["minutesToday"] == 2
    assert summary["last7Days"][0]["date"] == "2026-03-24"
    assert len(summary["last7Days"]) == WEEK_LENGTH_DAYS
    # Week starts Monday 2026-03-30: only the WRONG answer is in this week
    assert summary["accuracy"] == 0.0
    assert summary["minutesThisWeek"] == 2


def test_same_rows_in_utc_land_on_utc_days(client):
    user = 101
    summary = build_summary(client, user, LANG, DEFAULT_TIME_ZONE, "monday", utc("2026-03-30 10:00"))

    assert active_dates(summary) == ["2026-03-28", "2026-03-29"]
    assert summary["activeToday"] is False
    assert summary["currentStreak"] == 2
    assert summary["minutesToday"] == 0


def test_dst_autumn(client):
    user = 102
    # 2026-10-25: Berlin switches CEST -> CET; 00:30 local is 22:30 UTC before, 23:30 UTC after
    add_activity(client, user, [
        (LANG, utc("2026-10-24 22:30"), CORRECT),
        (LANG, utc("2026-10-25 23:30"), CORRECT),
    ])

    summary = build_summary(client, user, LANG, BERLIN, "monday", utc("2026-10-26 12:00"))

    assert active_dates(summary) == ["2026-10-25", "2026-10-26"]
    assert summary["currentStreak"] == 2
    assert summary["activeToday"] is True


def test_duplicate_minutes_count_once(client):
    user = 103
    minute = utc("2026-05-10 08:15")
    add_minutes(client, user, [(LANG, minute)])
    add_minutes(client, user, [(LANG, minute), (LANG, utc("2026-05-10 08:16"))])

    summary = build_summary(client, user, LANG, BERLIN, "monday", utc("2026-05-10 12:00"))
    assert summary["minutesToday"] == 2

    # After the merge collapses the duplicate row the count is unchanged
    merge_minutes(client)
    merged = build_summary(client, user, LANG, BERLIN, "monday", utc("2026-05-10 12:00"))
    assert merged["minutesToday"] == 2


def test_minutes_only_day_is_not_active(client):
    user = 103
    summary = build_summary(client, user, LANG, BERLIN, "monday", utc("2026-05-10 12:00"))

    assert summary["activeToday"] is False
    assert summary["currentStreak"] == 0
    assert summary["accuracy"] is None


def test_streak_ending_yesterday(client):
    user = 104
    add_activity(client, user, [
        (LANG, utc("2026-06-08 09:00"), NOT_GRADED),
        (LANG, utc("2026-06-09 09:00"), NOT_GRADED),
        (LANG, utc("2026-06-06 09:00"), NOT_GRADED),
    ])

    summary = build_summary(client, user, LANG, BERLIN, "monday", utc("2026-06-10 09:00"))

    assert summary["currentStreak"] == 2
    assert summary["activeToday"] is False
    assert summary["accuracy"] is None


def test_language_isolation(client):
    user = 105
    now = utc("2026-07-15 12:00")
    add_activity(client, user, [(LANG, utc("2026-07-15 08:00"), CORRECT)])
    add_minutes(client, user, [(LANG, utc("2026-07-15 08:00"))])
    before = build_summary(client, user, LANG, BERLIN, "monday", now)

    # Heavy activity in another language must not move the first language's numbers
    add_activity(client, user, [
        (OTHER_LANG, utc("2026-07-14 08:00"), WRONG),
        (OTHER_LANG, utc("2026-07-15 09:00"), WRONG),
    ])
    add_minutes(client, user, [(OTHER_LANG, utc("2026-07-15 09:00")), (OTHER_LANG, utc("2026-07-15 09:01"))])
    after = build_summary(client, user, LANG, BERLIN, "monday", now)
    other = build_summary(client, user, OTHER_LANG, BERLIN, "monday", now)

    assert after == before
    assert after["currentStreak"] == 1
    assert after["accuracy"] == 1.0
    assert after["minutesToday"] == 1
    assert other["currentStreak"] == 2
    assert other["accuracy"] == 0.0
    assert other["minutesToday"] == 2


def test_language_isolation_survives_merge(client):
    user = 106
    now = utc("2026-08-20 12:00")
    minute = utc("2026-08-20 08:00")
    # The same minute in two languages must stay two rows after the merge
    add_minutes(client, user, [(LANG, minute), (OTHER_LANG, minute)])
    merge_minutes(client)

    first = build_summary(client, user, LANG, BERLIN, "monday", now)
    other = build_summary(client, user, OTHER_LANG, BERLIN, "monday", now)

    assert first["minutesToday"] == 1
    assert other["minutesToday"] == 1


def test_unknown_zone_falls_back_to_utc(client):
    user = 101
    summary = build_summary(client, user, LANG, "Mars/Olympus", "monday", utc("2026-03-30 10:00"))

    assert summary["timeZone"] == DEFAULT_TIME_ZONE
    assert active_dates(summary) == ["2026-03-28", "2026-03-29"]

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import activity_summary as router_module
from app.services import activity_summary as svc
from app.services.activity_summary import (
    ACTIVITY_SQL,
    CALENDAR_SQL,
    DEFAULT_TIME_ZONE,
    MINUTES_SQL,
    STREAK_LOOKBACK_DAYS,
    TIME_ZONE_SQL,
    WEEK_LENGTH_DAYS,
    WEEK_START_MODES,
    build_summary,
    compute_streak,
)

TODAY = date(2026, 3, 26)  # a Thursday
MONDAY = date(2026, 3, 23)
SUNDAY = date(2026, 3, 22)
NOW_TS = 1774540800
ZONE = "Europe/Berlin"
UNKNOWN_ZONE = "Mars/Olympus"


def days_back(n: int) -> date:
    """Local day `n` days before TODAY."""
    return TODAY - timedelta(days=n)


def make_client(activity_rows=(), minute_rows=(), zone_known=True, week_start=MONDAY):
    """Stub ClickHouse client answering each summary query with canned rows."""
    client = MagicMock()

    def query(sql, parameters=None):
        # Route each statement to its canned result set
        result = MagicMock()
        if sql == TIME_ZONE_SQL:
            result.result_rows = [(1 if zone_known else 0,)]
        elif sql == CALENDAR_SQL:
            result.result_rows = [(TODAY, week_start, 100, 200)]
        elif sql == ACTIVITY_SQL:
            result.result_rows = list(activity_rows)
        elif sql == MINUTES_SQL:
            result.result_rows = list(minute_rows)
        else:
            raise AssertionError(f"unexpected SQL: {sql}")
        return result

    client.query.side_effect = query
    return client


@pytest.fixture(autouse=True)
def clear_zone_cache():
    """Each test starts with an empty time-zone cache."""
    svc._known_time_zones.clear()
    yield
    svc._known_time_zones.clear()


# --- compute_streak ---------------------------------------------------------


def test_streak_ending_today():
    assert compute_streak({TODAY, days_back(1), days_back(2)}, TODAY) == 3


def test_streak_ending_yesterday():
    assert compute_streak({days_back(1), days_back(2)}, TODAY) == 2


def test_streak_is_zero_when_neither_today_nor_yesterday_is_active():
    assert compute_streak({days_back(2), days_back(3)}, TODAY) == 0


def test_streak_stops_at_first_gap():
    assert compute_streak({TODAY, days_back(1), days_back(3)}, TODAY) == 2


def test_streak_is_capped_at_lookback():
    active = {days_back(n) for n in range(STREAK_LOOKBACK_DAYS + 10)}
    assert compute_streak(active, TODAY) == STREAK_LOOKBACK_DAYS


# --- build_summary ----------------------------------------------------------


def test_accuracy_is_null_without_graded_answers():
    client = make_client(activity_rows=[(TODAY, 3, 0, 0)])
    summary = build_summary(client, 1, 2, ZONE, "monday", NOW_TS)

    assert summary["accuracy"] is None
    assert summary["activeToday"] is True


def test_accuracy_counts_only_this_week():
    rows = [(TODAY, 4, 3, 4), (MONDAY, 2, 1, 2), (days_back(5), 10, 0, 10)]
    summary = build_summary(make_client(activity_rows=rows), 1, 2, ZONE, "monday", NOW_TS)

    assert summary["accuracy"] == pytest.approx(4 / 6)


def test_last_7_days_has_week_length_entries_oldest_first():
    client = make_client(activity_rows=[(days_back(1), 1, 0, 0)], minute_rows=[(days_back(6), 5)])
    summary = build_summary(client, 1, 2, ZONE, "monday", NOW_TS)
    last7 = summary["last7Days"]

    assert len(last7) == WEEK_LENGTH_DAYS
    assert last7[0] == {"date": days_back(6).isoformat(), "active": False, "minutes": 5}
    assert last7[-2] == {"date": days_back(1).isoformat(), "active": True, "minutes": 0}
    assert last7[-1]["date"] == TODAY.isoformat()
    assert summary["currentStreak"] == 1
    assert summary["activeToday"] is False


def test_week_minutes_follow_week_start():
    minutes = [(TODAY, 10), (MONDAY, 5), (SUNDAY, 7)]

    monday = build_summary(make_client(minute_rows=minutes), 1, 2, ZONE, "monday", NOW_TS)
    sunday = build_summary(
        make_client(minute_rows=minutes, week_start=SUNDAY), 1, 2, ZONE, "sunday", NOW_TS
    )

    assert monday["minutesToday"] == 10
    assert monday["minutesThisWeek"] == 15
    assert sunday["minutesThisWeek"] == 22


def test_minutes_only_day_is_not_active():
    summary = build_summary(make_client(minute_rows=[(TODAY, 3)]), 1, 2, ZONE, "monday", NOW_TS)

    assert summary["activeToday"] is False
    assert summary["currentStreak"] == 0
    assert summary["minutesToday"] == 3


def test_calendar_uses_week_mode_and_named_constants():
    client = make_client()
    build_summary(client, 1, 2, ZONE, "sunday", NOW_TS)

    calendar_params = next(
        c.kwargs["parameters"] for c in client.query.call_args_list if c.args[0] == CALENDAR_SQL
    )
    assert calendar_params["weekMode"] == WEEK_START_MODES["sunday"]
    assert calendar_params["lookback"] == STREAK_LOOKBACK_DAYS
    assert calendar_params["last7Offset"] == WEEK_LENGTH_DAYS - 1
    assert calendar_params["tz"] == ZONE


def test_unknown_zone_falls_back_to_utc():
    client = make_client(zone_known=False)
    summary = build_summary(client, 1, 2, UNKNOWN_ZONE, "monday", NOW_TS)

    assert summary["timeZone"] == DEFAULT_TIME_ZONE
    used_zones = {c.kwargs["parameters"]["tz"] for c in client.query.call_args_list if c.args[0] != TIME_ZONE_SQL}
    assert used_zones == {DEFAULT_TIME_ZONE}


def test_zone_lookup_is_cached():
    client = make_client()
    build_summary(client, 1, 2, ZONE, "monday", NOW_TS)
    build_summary(client, 1, 2, ZONE, "monday", NOW_TS)

    zone_calls = [c for c in client.query.call_args_list if c.args[0] == TIME_ZONE_SQL]
    assert len(zone_calls) == 1


# --- router -----------------------------------------------------------------


@pytest.fixture
def api():
    """Router-only app: avoids importing main.py (Playwright, Tor)."""
    app = FastAPI()
    app.include_router(router_module.router)
    return TestClient(app)


def stub_client(monkeypatch, client):
    """Make the router use the given stub client."""
    monkeypatch.setattr(router_module, "get_clickhouse_client", lambda: client)


def test_endpoint_returns_summary_with_default_week_start(api, monkeypatch):
    client = make_client(activity_rows=[(TODAY, 2, 1, 2)], minute_rows=[(TODAY, 4)])
    stub_client(monkeypatch, client)

    res = api.post("/stats/activity-summary", json={"externalId": 1, "languageId": 2, "timeZone": ZONE})

    assert res.status_code == 200
    body = res.json()
    assert body["currentStreak"] == 1
    assert body["minutesToday"] == 4
    assert body["accuracy"] == 0.5
    assert body["timeZone"] == ZONE
    calendar_params = next(
        c.kwargs["parameters"] for c in client.query.call_args_list if c.args[0] == CALENDAR_SQL
    )
    assert calendar_params["weekMode"] == WEEK_START_MODES["monday"]


def test_endpoint_reports_fallback_zone(api, monkeypatch):
    stub_client(monkeypatch, make_client(zone_known=False))

    res = api.post(
        "/stats/activity-summary", json={"externalId": 1, "languageId": 2, "timeZone": UNKNOWN_ZONE}
    )

    assert res.status_code == 200
    assert res.json()["timeZone"] == DEFAULT_TIME_ZONE


@pytest.mark.parametrize(
    "body",
    [
        {"languageId": 2, "timeZone": ZONE},
        {"externalId": 1, "timeZone": ZONE},
        {"externalId": 1, "languageId": 2},
        {"externalId": 1, "languageId": 2, "timeZone": ZONE, "weekStart": "friday"},
    ],
    ids=["no-externalId", "no-languageId", "no-timeZone", "bad-weekStart"],
)
def test_endpoint_rejects_bad_body(api, monkeypatch, body):
    client = make_client()
    stub_client(monkeypatch, client)

    res = api.post("/stats/activity-summary", json=body)

    assert res.status_code == 422
    client.query.assert_not_called()


def test_endpoint_returns_500_with_detail_on_clickhouse_error(api, monkeypatch):
    client = MagicMock()
    client.query.side_effect = RuntimeError("Table default.learningActivity doesn't exist")
    stub_client(monkeypatch, client)

    res = api.post("/stats/activity-summary", json={"externalId": 1, "languageId": 2, "timeZone": ZONE})

    assert res.status_code == 500
    assert "learningActivity doesn't exist" in res.json()["detail"]

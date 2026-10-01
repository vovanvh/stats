"""
Activity summary: streak, local-day activity, practice minutes and accuracy for one user and language.

Calendar math (local day, week start, local midnights) runs in ClickHouse via the caller's IANA zone;
Python only walks the streak and sums the per-day rows.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set

# Days shown in last7Days and the fallback week length
WEEK_LENGTH_DAYS = 7
# Longest streak that is counted; also how far back activity is read
STREAK_LOOKBACK_DAYS = 365
# Zone used when the caller's zone is unknown to ClickHouse
DEFAULT_TIME_ZONE = "UTC"
# toStartOfWeek mode per accepted weekStart value
WEEK_START_MODES = {"monday": 1, "sunday": 0}
# weekStart used when the caller omits it
DEFAULT_WEEK_START = "monday"
# Tables read by the summary (created by ddl/003 and ddl/004)
APP_USAGE_MINUTE_TABLE = "appUsageMinute"
LEARNING_ACTIVITY_TABLE = "learningActivity"

# Today, week start and the two lower bounds (as UTC epoch seconds of local midnights) in the caller's zone
CALENDAR_SQL = (
    "SELECT toDate(toDateTime({now:UInt32}), {tz:String}) AS today, "
    "toStartOfWeek(today, {weekMode:UInt8}) AS weekStart, "
    "toUnixTimestamp(toDateTime(today - {lookback:UInt16}, {tz:String})) AS activityFromTs, "
    "toUnixTimestamp(toDateTime(least(weekStart, today - {last7Offset:UInt8}), {tz:String})) AS minutesFromTs"
)

# Learning actions per local day, with graded / correct counts for accuracy
ACTIVITY_SQL = (
    "SELECT toDate(ts, {tz:String}) AS day, count() AS actions, "
    "countIf(result = 1) AS correct, countIf(result >= 0) AS graded "
    f"FROM {LEARNING_ACTIVITY_TABLE} "
    "WHERE externalId = {externalId:Int64} AND languageId = {languageId:Int8} "
    "AND ts >= toDateTime({fromTs:UInt32}) AND ts <= toDateTime({now:UInt32}) "
    "GROUP BY day"
)

# Distinct app-usage minutes per local day; uniqExact ignores not-yet-merged duplicate rows
MINUTES_SQL = (
    "SELECT toDate(minuteTs, {tz:String}) AS day, uniqExact(minuteTs) AS minutes "
    f"FROM {APP_USAGE_MINUTE_TABLE} "
    "WHERE externalId = {externalId:Int64} AND languageId = {languageId:Int8} "
    "AND minuteTs >= toDateTime({fromTs:UInt32}) AND minuteTs <= toDateTime({now:UInt32}) "
    "GROUP BY day"
)

# Whether ClickHouse knows the zone
TIME_ZONE_SQL = "SELECT count() FROM system.time_zones WHERE time_zone = {tz:String}"

# Per-process cache of zone lookups: zone name -> known to ClickHouse
_known_time_zones: Dict[str, bool] = {}


@dataclass
class Calendar:
    """Local calendar anchors for one request, computed by ClickHouse."""

    today: date
    week_start: date
    activity_from_ts: int
    minutes_from_ts: int


@dataclass
class ActivityDay:
    """Learning-action counts for one local day."""

    actions: int
    correct: int
    graded: int


def resolve_time_zone(client: Any, time_zone: str) -> str:
    """
    Return `time_zone` when ClickHouse knows it, else DEFAULT_TIME_ZONE.
    Lookups are cached per process.
    """
    # Ask ClickHouse once per zone name
    if time_zone not in _known_time_zones:
        rows = client.query(TIME_ZONE_SQL, parameters={"tz": time_zone}).result_rows
        _known_time_zones[time_zone] = bool(rows and rows[0][0])

    # Fall back to UTC for an unknown zone
    return time_zone if _known_time_zones[time_zone] else DEFAULT_TIME_ZONE


def load_calendar(client: Any, time_zone: str, week_start: str, now_ts: int) -> Calendar:
    """
    Compute today, the week start and the read lower bounds in the caller's zone.
    """
    # One row with the local anchors
    row = client.query(
        CALENDAR_SQL,
        parameters={
            "now": now_ts,
            "tz": time_zone,
            "weekMode": WEEK_START_MODES[week_start],
            "lookback": STREAK_LOOKBACK_DAYS,
            "last7Offset": WEEK_LENGTH_DAYS - 1,
        },
    ).result_rows[0]
    return Calendar(today=row[0], week_start=row[1], activity_from_ts=row[2], minutes_from_ts=row[3])


def fetch_activity_days(
    client: Any, external_id: int, language_id: int, time_zone: str, from_ts: int, now_ts: int
) -> Dict[date, ActivityDay]:
    """
    Read learning-action counts per local day between `from_ts` and `now_ts`.
    """
    # Group the user's actions in this language by local day
    rows = client.query(
        ACTIVITY_SQL,
        parameters={
            "tz": time_zone,
            "externalId": external_id,
            "languageId": language_id,
            "fromTs": from_ts,
            "now": now_ts,
        },
    ).result_rows
    return {row[0]: ActivityDay(actions=row[1], correct=row[2], graded=row[3]) for row in rows}


def fetch_minute_days(
    client: Any, external_id: int, language_id: int, time_zone: str, from_ts: int, now_ts: int
) -> Dict[date, int]:
    """
    Read distinct app-usage minutes per local day between `from_ts` and `now_ts`.
    """
    # Group the user's minutes in this language by local day
    rows = client.query(
        MINUTES_SQL,
        parameters={
            "tz": time_zone,
            "externalId": external_id,
            "languageId": language_id,
            "fromTs": from_ts,
            "now": now_ts,
        },
    ).result_rows
    return {row[0]: row[1] for row in rows}


def compute_streak(active_days: Set[date], today: date) -> int:
    """
    Count consecutive active days ending today, or yesterday when today is not active yet.
    Returns 0 when neither is active; never exceeds STREAK_LOOKBACK_DAYS.
    """
    # The streak may still be alive from yesterday
    day = today if today in active_days else today - timedelta(days=1)

    # Walk back until the first gap or the cap
    streak = 0
    while day in active_days and streak < STREAK_LOOKBACK_DAYS:
        streak += 1
        day -= timedelta(days=1)
    return streak


def sum_minutes(minute_days: Dict[date, int], days: Iterable[date]) -> int:
    """
    Sum the minutes of the given local days.
    """
    return sum(minute_days.get(day, 0) for day in days)


def build_summary(
    client: Any, external_id: int, language_id: int, time_zone: str, week_start: str, now_ts: int
) -> Dict[str, Any]:
    """
    Build the full activity summary for one user and language at `now_ts`.
    `timeZone` in the result is the zone actually used after the UTC fallback.
    """
    # Resolve the zone and the local calendar anchors
    zone = resolve_time_zone(client, time_zone)
    calendar = load_calendar(client, zone, week_start, now_ts)
    today = calendar.today

    # Read per-day activity and minutes
    activity = fetch_activity_days(client, external_id, language_id, zone, calendar.activity_from_ts, now_ts)
    minutes = fetch_minute_days(client, external_id, language_id, zone, calendar.minutes_from_ts, now_ts)
    active_days = {day for day, counts in activity.items() if counts.actions > 0}

    # Last WEEK_LENGTH_DAYS local days, oldest first
    last_days = [today - timedelta(days=offset) for offset in range(WEEK_LENGTH_DAYS - 1, -1, -1)]
    last_7_days: List[Dict[str, Any]] = [
        {"date": day.isoformat(), "active": day in active_days, "minutes": minutes.get(day, 0)}
        for day in last_days
    ]

    # Days of the current week up to today
    week_days = [calendar.week_start + timedelta(days=i) for i in range((today - calendar.week_start).days + 1)]

    # Accuracy over the current week; null without graded answers
    correct = sum(activity[day].correct for day in week_days if day in activity)
    graded = sum(activity[day].graded for day in week_days if day in activity)
    accuracy: Optional[float] = correct / graded if graded else None

    return {
        "currentStreak": compute_streak(active_days, today),
        "activeToday": today in active_days,
        "last7Days": last_7_days,
        "minutesToday": minutes.get(today, 0),
        "minutesThisWeek": sum_minutes(minutes, week_days),
        "accuracy": accuracy,
        "timeZone": zone,
    }

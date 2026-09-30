import logging
import time
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from app.database import get_clickhouse_client
from app.services.activity_summary import DEFAULT_WEEK_START, WEEK_START_MODES, build_summary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stats", tags=["statistics"])


class ActivitySummaryRequest(BaseModel):
    """Request body of POST /stats/activity-summary."""

    externalId: int
    languageId: int
    timeZone: str
    weekStart: str = DEFAULT_WEEK_START

    @field_validator("weekStart")
    @classmethod
    def validate_week_start(cls, value: str) -> str:
        """
        Accept only the week starts listed in WEEK_START_MODES (surfaced as a 422).
        """
        # Reject any value without a toStartOfWeek mode
        if value not in WEEK_START_MODES:
            raise ValueError(f"weekStart must be one of {sorted(WEEK_START_MODES)}")
        return value


class ActivityDayResponse(BaseModel):
    """One local day in last7Days."""

    date: str
    active: bool
    minutes: int


class ActivitySummaryResponse(BaseModel):
    """Streak, minutes and accuracy for one user and language."""

    currentStreak: int
    activeToday: bool
    last7Days: List[ActivityDayResponse]
    minutesToday: int
    minutesThisWeek: int
    accuracy: Optional[float]
    timeZone: str


@router.post("/activity-summary", response_model=ActivitySummaryResponse)
def activity_summary(req: ActivitySummaryRequest):
    """
    Return streak, last-7-days activity, practice minutes and weekly accuracy in the caller's time zone.
    Returns 500 with the ClickHouse error message when a read fails.
    """
    # Read and aggregate; surface a readable error instead of a bare failure
    try:
        client = get_clickhouse_client()
        return build_summary(
            client, req.externalId, req.languageId, req.timeZone, req.weekStart, int(time.time())
        )
    except Exception as exc:
        logger.exception("ClickHouse activity summary for externalId %s failed", req.externalId)
        raise HTTPException(
            status_code=500,
            detail=f"ClickHouse activity summary failed: {exc}",
        ) from exc

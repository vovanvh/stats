import logging
import re
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.database import get_clickhouse_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stats", tags=["statistics"])

# A bare ClickHouse identifier: keeps table and column names out of SQL injection.
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _require_identifier(value: str, kind: str) -> str:
    """
    Validate that a table or column name is a bare ClickHouse identifier.
    Raises ValueError (surfaced by pydantic as a 422) when it is not.
    """
    # Reject anything that is not a plain identifier (dots, spaces, quotes, empty)
    if not IDENTIFIER_PATTERN.match(value):
        raise ValueError(f"invalid {kind} name '{value}': must match {IDENTIFIER_PATTERN.pattern}")
    return value


class StatData(BaseModel):
    """Request body of POST /stats/: a target table and the rows to insert into it."""

    table: str
    data: List[Dict[str, Any]] = Field(min_length=1)

    @field_validator("table")
    @classmethod
    def validate_table(cls, value: str) -> str:
        """
        Strip the table name and require a non-empty bare identifier.
        """
        # Normalise surrounding whitespace before the identifier check
        return _require_identifier(value.strip(), "table")

    @field_validator("data")
    @classmethod
    def validate_columns(cls, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Require every column key of every row to be a bare identifier.
        """
        # Check each key once per row; any bad key fails the whole request
        for row in rows:
            for key in row.keys():
                _require_identifier(key, "column")
        return rows


def extract_columns_and_data(rows: list[dict]) -> tuple[list[str], list[list]]:
    """
    Build the sorted union of column names and the row values in that column order.
    Missing keys become None.
    """
    column_names = sorted(set().union(*(row.keys() for row in rows)))
    data = [[row.get(col) for col in column_names] for row in rows]
    return column_names, data


@router.post("/")
def create_stat(stat: StatData):
    """
    Insert the given rows into the given ClickHouse table.
    Returns 500 with the ClickHouse error message when the insert fails.
    """
    # Derive column names from the row keys
    column_names, data = extract_columns_and_data(stat.data)

    # Insert and surface a readable error instead of a bare failure
    try:
        client = get_clickhouse_client()
        client.insert(stat.table, data, column_names)
    except Exception as exc:
        logger.exception("ClickHouse insert into '%s' failed", stat.table)
        raise HTTPException(
            status_code=500,
            detail=f"ClickHouse insert into '{stat.table}' failed: {exc}",
        ) from exc

    return {"status": "success"}

from typing import List
from pydantic import BaseModel
from fastapi import APIRouter
from app.database import get_clickhouse_client

router = APIRouter(prefix="/stats", tags=["statistics"])


class StatItem(BaseModel):
    language: int
    translationLanguage: int
    wordId: int
    externalId: int
    interval: int
    repetitions: int
    lastRes: int
    timestampAdded: int
    timestampUpdated: int
    nextStartTS: int
    type: int


class StatData(BaseModel):
    table: str
    data: List[StatItem]


def extract_columns_and_data(rows: list[dict]) -> tuple[list[str], list[list]]:
    column_names = sorted(set().union(*(row.keys() for row in rows)))
    data = [[row.get(col) for col in column_names] for row in rows]
    return column_names, data


@router.post("/")
def create_stat(stat: StatData):
    client = get_clickhouse_client()
    data_as_dicts = [item.model_dump() for item in stat.data]
    column_names, data = extract_columns_and_data(data_as_dicts)
    client.insert(stat.table, data, column_names)
    return {"status": "success"}

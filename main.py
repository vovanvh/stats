from typing import List
from pydantic import BaseModel
from fastapi import FastAPI
from os import environ as env
from app.database import get_clickhouse_client
from app.config import settings
from pprint import pprint

app = FastAPI()

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

@app.get("/test/")
def read_root():
    client = get_clickhouse_client()
    return {"Hello": "World", "Host": f"HOST name: {env['HOST']}", "ClickHouse": client.query("SELECT 1").result_rows}

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/stats/")
def create_stat(stat: StatData):
    client = get_clickhouse_client()
    data_as_dicts = [item.model_dump() for item in stat.data]
    column_names, data = extract_columns_and_data(data_as_dicts)
    client.insert(stat.table, data, column_names)
    return {"status": "success"}

def extract_columns_and_data(rows: list[dict]) -> tuple[list[str], list[list]]:
    # Get the union of all column names from all rows
    column_names = sorted(set().union(*(row.keys() for row in rows)))
    
    # Create the matrix of row values with consistent column order
    data = [[row.get(col) for col in column_names] for row in rows]
    
    return column_names, data
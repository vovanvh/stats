from typing import Union

from fastapi import FastAPI
from os import environ as env
from app.database import get_clickhouse_client
from app.config import settings

app = FastAPI()

@app.get("/")
def read_root():
    client = get_clickhouse_client()
    return {"Hello": "World", "Host": f"HOST name: {env['HOST']}", "ClickHouse": client.query("SELECT 1").result_rows}

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/items/{item_id}")
def read_item(item_id: int, q: Union[str, None] = None):
    return {"item_id": item_id, "q": q, "ddd": 333}

@app.post("/stats")
def create_stat(stat: any):
    return {"stat": stat}
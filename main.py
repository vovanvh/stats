from typing import List
from pydantic import BaseModel
from fastapi import FastAPI
from os import environ as env
from app.database import get_clickhouse_client
from app.config import settings
from pprint import pprint
from youtube_transcript_api import YouTubeTranscriptApi
from fastapi import HTTPException
from fastapi.routing import APIRoute

class SlashInsensitiveAPIRoute(APIRoute):
    def matches(self, scope):
        path = scope["path"]
        if path != "/" and path.endswith("/"):
            scope["path"] = path.rstrip("/")
        return super().matches(scope)

app = FastAPI(route_class=SlashInsensitiveAPIRoute)

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

@app.get("/yt")
async def get_youtube_transcript(videoId: str, language: str):
    try:
        transcript = YouTubeTranscriptApi.get_transcript(videoId, languages=[language])
        return {"transcript": transcript}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.get("/yt-list")
async def get_available_transcripts(videoId: str):
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(videoId)
        available_transcripts = [
            {
                "language": t.language,
                "language_code": t.language_code,
                "is_generated": t.is_generated,
                "is_translatable": t.is_translatable
            }
            for t in transcript_list
        ]
        return {"available_transcripts": available_transcripts}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


def extract_columns_and_data(rows: list[dict]) -> tuple[list[str], list[list]]:
    # Get the union of all column names from all rows
    column_names = sorted(set().union(*(row.keys() for row in rows)))
    
    # Create the matrix of row values with consistent column order
    data = [[row.get(col) for col in column_names] for row in rows]
    
    return column_names, data
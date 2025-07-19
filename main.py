from typing import List
from pydantic import BaseModel
from fastapi import FastAPI
from os import environ as env
from app.database import get_clickhouse_client
from app.config import settings
from pprint import pprint
from youtube_transcript_api import YouTubeTranscriptApi
from fastapi import HTTPException, Request
from fastapi.routing import APIRoute
import requests

class SlashInsensitiveAPIRoute(APIRoute):
    def matches(self, scope):
        path = scope["path"]
        print(f"[MATCHES] incoming path: {path}")
        if path != "/" and path.endswith("/"):
            scope["path"] = path.rstrip("/")
            print(f"[MATCHES] normalized path: {scope['path']}")
        return super().matches(scope)

app = FastAPI(route_class=SlashInsensitiveAPIRoute)

def configure_youtube_api_with_tor():
    """Configure youtube_transcript_api to use Tor proxy if enabled"""
    if settings.USE_TOR_PROXY:
        proxies = {
            'http': f'socks5://{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}',
            'https': f'socks5://{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}'
        }
        
        # Monkey patch the global requests module
        original_get = requests.get
        original_post = requests.post
        
        def proxied_get(*args, **kwargs):
            kwargs['proxies'] = proxies
            kwargs['timeout'] = kwargs.get('timeout', 30)
            return original_get(*args, **kwargs)
            
        def proxied_post(*args, **kwargs):
            kwargs['proxies'] = proxies
            kwargs['timeout'] = kwargs.get('timeout', 30)
            return original_post(*args, **kwargs)
        
        # Patch the global requests module
        requests.get = proxied_get
        requests.post = proxied_post
        
        print(f"[TOR] YouTube API configured to use Tor proxy at {settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}")
    else:
        print("[TOR] Tor proxy disabled, using direct connection")

# Configure Tor proxy on startup
configure_youtube_api_with_tor()

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

@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f">>> {request.method} {request.url.path}")
    return await call_next(request)

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
        print(f"[YT] Getting transcript for video {videoId} in language {language}")
        if settings.USE_TOR_PROXY:
            print(f"[YT] Using Tor proxy: {settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}")
        transcript = YouTubeTranscriptApi.get_transcript(videoId, languages=[language])
        return {"transcript": transcript}
    except Exception as e:
        error_msg = str(e)
        if "Connection" in error_msg or "timeout" in error_msg.lower():
            print(f"[YT] Connection error (possibly Tor-related): {error_msg}")
            raise HTTPException(status_code=503, detail=f"Connection error: {error_msg}")
        print(f"[YT] Error: {error_msg}")
        raise HTTPException(status_code=404, detail=error_msg)

@app.get("/yt-list")
async def get_available_transcripts(videoId: str):
    try:
        print(f"[YT-LIST] Getting available transcripts for video {videoId}")
        if settings.USE_TOR_PROXY:
            print(f"[YT-LIST] Using Tor proxy: {settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}")
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
        error_msg = str(e)
        if "Connection" in error_msg or "timeout" in error_msg.lower():
            print(f"[YT-LIST] Connection error (possibly Tor-related): {error_msg}")
            raise HTTPException(status_code=503, detail=f"Connection error: {error_msg}")
        print(f"[YT-LIST] Error: {error_msg}")
        raise HTTPException(status_code=404, detail=error_msg)


def extract_columns_and_data(rows: list[dict]) -> tuple[list[str], list[list]]:
    # Get the union of all column names from all rows
    column_names = sorted(set().union(*(row.keys() for row in rows)))
    
    # Create the matrix of row values with consistent column order
    data = [[row.get(col) for col in column_names] for row in rows]
    
    return column_names, data
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

# def configure_youtube_api_with_tor():
#     """Configure youtube_transcript_api to use Tor proxy if enabled"""
#     if settings.USE_TOR_PROXY:
#         proxies = {
#             'http': f'socks5://{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}',
#             'https': f'socks5://{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}'
#         }
        
#         # Store original functions
#         original_get = requests.get
#         original_post = requests.post
#         original_request = requests.request
        
#         def proxied_get(*args, **kwargs):
#             # Force proxy usage unless explicitly disabled
#             if 'proxies' not in kwargs:
#                 kwargs['proxies'] = proxies
#             kwargs['timeout'] = kwargs.get('timeout', 30)
#             print(f"[TOR] GET request via proxy: {args[0] if args else 'unknown URL'}")
#             return original_get(*args, **kwargs)
            
#         def proxied_post(*args, **kwargs):
#             # Force proxy usage unless explicitly disabled
#             if 'proxies' not in kwargs:
#                 kwargs['proxies'] = proxies
#             kwargs['timeout'] = kwargs.get('timeout', 30)
#             print(f"[TOR] POST request via proxy: {args[0] if args else 'unknown URL'}")
#             return original_post(*args, **kwargs)
            
#         def proxied_request(*args, **kwargs):
#             # Force proxy usage unless explicitly disabled
#             if 'proxies' not in kwargs:
#                 kwargs['proxies'] = proxies
#             kwargs['timeout'] = kwargs.get('timeout', 30)
#             method = args[0] if args else kwargs.get('method', 'UNKNOWN')
#             url = args[1] if len(args) > 1 else kwargs.get('url', 'unknown URL')
#             print(f"[TOR] {method} request via proxy: {url}")
#             return original_request(*args, **kwargs)
        
#         # Patch the global requests module
#         requests.get = proxied_get
#         requests.post = proxied_post
#         requests.request = proxied_request
        
#         print(f"[TOR] All HTTP requests configured to use Tor proxy at {settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}")
#     else:
#         print("[TOR] Tor proxy disabled, using direct connection")

# Configure Tor proxy on startup
#configure_youtube_api_with_tor()

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

@app.get("/test-tor")
async def test_tor_connection():
    """Test if Tor proxy is working by checking external IP"""
    try:
        # Test direct connection
        direct_response = requests.get("https://httpbin.org/ip", timeout=10, proxies={})
        direct_ip = direct_response.json().get("origin")
        
        # Test through current proxy setup
        if settings.USE_TOR_PROXY:
            proxied_response = requests.get("https://httpbin.org/ip", timeout=30)
            proxied_ip = proxied_response.json().get("origin")
            
            return {
                "tor_enabled": True,
                "tor_proxy": f"{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}",
                "direct_ip": direct_ip,
                "proxied_ip": proxied_ip,
                "tor_working": direct_ip != proxied_ip
            }
        else:
            return {
                "tor_enabled": False,
                "direct_ip": direct_ip
            }
    except Exception as e:
        return {"error": str(e), "tor_enabled": settings.USE_TOR_PROXY}

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
        transcript = YouTubeTranscriptApi.get_transcript(videoId, languages=[language], proxies = {
            'http': f'socks5://{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}',
            'https': f'socks5://{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}'
        })
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
        transcript_list = YouTubeTranscriptApi.list_transcripts(videoId, proxies = {
            'http': f'socks5://{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}',
            'https': f'socks5://{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}'
        })
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
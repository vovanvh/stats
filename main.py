from typing import List
from pydantic import BaseModel
from fastapi import FastAPI
from os import environ as env
from app.database import get_clickhouse_client
from app.config import settings
from pprint import pprint
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._api import TranscriptList
from fastapi import HTTPException, Request
from fastapi.routing import APIRoute
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import socket
import time

class SlashInsensitiveAPIRoute(APIRoute):
    def matches(self, scope):
        path = scope["path"]
        print(f"[MATCHES] incoming path: {path}")
        if path != "/" and path.endswith("/"):
            scope["path"] = path.rstrip("/")
            print(f"[MATCHES] normalized path: {scope['path']}")
        return super().matches(scope)

app = FastAPI(route_class=SlashInsensitiveAPIRoute)

def create_session_with_timeout(timeout=120):
    """Create a requests session with default timeout and retry logic"""
    session = requests.Session()

    # Configure retry strategy
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    # Monkey-patch session.request to add default timeout
    original_request = session.request
    def request_with_timeout(*args, **kwargs):
        if 'timeout' not in kwargs:
            kwargs['timeout'] = timeout
        return original_request(*args, **kwargs)
    session.request = request_with_timeout

    return session

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

@app.post("/tor/new-identity")
async def request_new_tor_identity():
    """
    Force Tor to switch to a new circuit and exit IP address

    Sends NEWNYM signal to Tor control port to request a new identity.
    This is useful when the current exit node is blocked by YouTube or other services.

    Note: Tor rate-limits this signal to approximately once per 10 seconds.
    """
    if not settings.USE_TOR_PROXY:
        raise HTTPException(
            status_code=400,
            detail="Tor proxy is not enabled. Set USE_TOR_PROXY=True to use this endpoint."
        )

    control_port = 9051
    control_password = "my-stats-tor-2026"

    try:
        print(f"[TOR] Requesting new identity via control port {settings.TOR_PROXY_HOST}:{control_port}")

        # Connect to Tor control port
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect((settings.TOR_PROXY_HOST, control_port))

        # Authenticate
        auth_cmd = f'AUTHENTICATE "{control_password}"\r\n'
        s.send(auth_cmd.encode())
        response = s.recv(1024).decode()

        if "250 OK" not in response:
            s.close()
            print(f"[TOR] Authentication failed: {response}")
            raise HTTPException(
                status_code=500,
                detail=f"Tor control port authentication failed: {response.strip()}"
            )

        # Send NEWNYM signal
        s.send(b'SIGNAL NEWNYM\r\n')
        response = s.recv(1024).decode()

        if "250 OK" not in response:
            s.close()
            print(f"[TOR] NEWNYM signal failed: {response}")
            raise HTTPException(
                status_code=500,
                detail=f"Tor NEWNYM signal failed: {response.strip()}"
            )

        # Get current circuit info (optional)
        s.send(b'GETINFO circuit-status\r\n')
        circuit_info = s.recv(4096).decode()

        # Close connection
        s.send(b'QUIT\r\n')
        s.close()

        print("[TOR] New identity requested successfully")

        # Wait a moment for new circuit to establish
        time.sleep(1)

        # Try to get new IP to verify
        new_ip = None
        try:
            proxies = {
                'http': f'socks5://{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}',
                'https': f'socks5://{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}'
            }
            response = requests.get("https://httpbin.org/ip", proxies=proxies, timeout=15)
            new_ip = response.json().get("origin")
        except Exception as e:
            print(f"[TOR] Could not verify new IP: {e}")

        return {
            "status": "success",
            "message": "New Tor identity requested. New circuit should be established within 1-2 seconds.",
            "new_exit_ip": new_ip,
            "note": "Tor rate-limits this request to approximately once per 10 seconds."
        }

    except socket.timeout:
        print(f"[TOR] Connection timeout to control port")
        raise HTTPException(
            status_code=504,
            detail=f"Timeout connecting to Tor control port at {settings.TOR_PROXY_HOST}:{control_port}"
        )
    except ConnectionRefusedError:
        print(f"[TOR] Connection refused to control port")
        raise HTTPException(
            status_code=503,
            detail=f"Cannot connect to Tor control port at {settings.TOR_PROXY_HOST}:{control_port}. Ensure control port is enabled in torrc."
        )
    except Exception as e:
        print(f"[TOR] Error requesting new identity: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error requesting new Tor identity: {str(e)}"
        )

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

        # Create proxies dict
        proxies = {
            'http': f'socks5://{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}',
            'https': f'socks5://{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}'
        } if settings.USE_TOR_PROXY else None

        # Patch requests.Session to always include proxies
        original_session_init = requests.Session.__init__

        def patched_session_init(self, *args, **kwargs):
            original_session_init(self, *args, **kwargs)
            if proxies:
                self.proxies.update(proxies)
                # Set timeout for all requests
                original_request = self.request
                def request_with_timeout(*args, **kwargs):
                    kwargs.setdefault('timeout', 120)
                    return original_request(*args, **kwargs)
                self.request = request_with_timeout

        requests.Session.__init__ = patched_session_init

        try:
            transcript = YouTubeTranscriptApi.get_transcript(videoId, languages=[language])
        finally:
            requests.Session.__init__ = original_session_init

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

        # Create proxies dict
        proxies = {
            'http': f'socks5://{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}',
            'https': f'socks5://{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}'
        } if settings.USE_TOR_PROXY else None

        # Patch requests.Session to always include proxies
        original_session_init = requests.Session.__init__

        def patched_session_init(self, *args, **kwargs):
            original_session_init(self, *args, **kwargs)
            if proxies:
                self.proxies.update(proxies)
                # Set timeout for all requests
                original_request = self.request
                def request_with_timeout(*args, **kwargs):
                    kwargs.setdefault('timeout', 120)
                    return original_request(*args, **kwargs)
                self.request = request_with_timeout

        requests.Session.__init__ = patched_session_init

        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(videoId)
        finally:
            requests.Session.__init__ = original_session_init

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
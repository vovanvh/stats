from typing import List, Optional
from pydantic import BaseModel, Field
from fastapi import FastAPI, Query
from os import environ as env
from app.database import get_clickhouse_client
from app.config import settings
from pprint import pprint
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig
from fastapi import HTTPException, Request
from fastapi.routing import APIRoute
import requests
import socket
import time
import asyncio
import base64
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from readability import Document
from lxml import html as lxml_html

class SlashInsensitiveAPIRoute(APIRoute):
    def matches(self, scope):
        path = scope["path"]
        print(f"[MATCHES] incoming path: {path}")
        if path != "/" and path.endswith("/"):
            scope["path"] = path.rstrip("/")
            print(f"[MATCHES] normalized path: {scope['path']}")
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


class ScrapeMetadata(BaseModel):
    description: Optional[str] = None
    keywords: Optional[str] = None
    ogTitle: Optional[str] = None
    ogDescription: Optional[str] = None
    ogImage: Optional[str] = None
    author: Optional[str] = None
    canonical: Optional[str] = None


class ScrapeTiming(BaseModel):
    total_ms: int


class ScrapeResponse(BaseModel):
    url: str
    title: str
    html: str
    textContent: str
    mainContent: Optional[str] = None
    metadata: ScrapeMetadata
    screenshot: Optional[str] = None
    timing: ScrapeTiming

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

def get_youtube_api_client() -> YouTubeTranscriptApi:
    """Create a YouTubeTranscriptApi client with optional Tor proxy configuration"""
    if settings.USE_TOR_PROXY:
        proxy_url = f"socks5://{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}"
        proxy_config = GenericProxyConfig(
            http_url=proxy_url,
            https_url=proxy_url,
        )
        return YouTubeTranscriptApi(proxy_config=proxy_config)
    return YouTubeTranscriptApi()


@app.get("/yt")
async def get_youtube_transcript(videoId: str, language: str):
    try:
        print(f"[YT] Getting transcript for video {videoId} in language {language}")
        if settings.USE_TOR_PROXY:
            print(f"[YT] Using Tor proxy: {settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}")

        ytt_api = get_youtube_api_client()
        transcript = ytt_api.fetch(videoId, languages=[language])

        return {"transcript": transcript.to_raw_data()}
    except Exception as e:
        error_msg = str(e)
        if "Connection" in error_msg or "timeout" in error_msg.lower():
            print(f"[YT] Connection error (possibly Tor-related): {error_msg}")
            raise HTTPException(status_code=503, detail=f"Connection error: {error_msg}")
        if "IpBlocked" in error_msg or "429" in error_msg:
            print(f"[YT] IP blocked by YouTube: {error_msg}")
            raise HTTPException(status_code=429, detail="YouTube has blocked this IP. Try requesting a new Tor identity via POST /tor/new-identity")
        print(f"[YT] Error: {error_msg}")
        raise HTTPException(status_code=404, detail=error_msg)

@app.get("/yt-list")
async def get_available_transcripts(videoId: str):
    try:
        print(f"[YT-LIST] Getting available transcripts for video {videoId}")
        if settings.USE_TOR_PROXY:
            print(f"[YT-LIST] Using Tor proxy: {settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}")

        ytt_api = get_youtube_api_client()
        transcript_list = ytt_api.list(videoId)

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
        if "IpBlocked" in error_msg or "429" in error_msg:
            print(f"[YT-LIST] IP blocked by YouTube: {error_msg}")
            raise HTTPException(status_code=429, detail="YouTube has blocked this IP. Try requesting a new Tor identity via POST /tor/new-identity")
        print(f"[YT-LIST] Error: {error_msg}")
        raise HTTPException(status_code=404, detail=error_msg)


def extract_metadata_from_html(html_content: str) -> ScrapeMetadata:
    """Extract metadata from HTML using lxml"""
    try:
        tree = lxml_html.fromstring(html_content)

        def get_meta(name: str = None, property: str = None) -> Optional[str]:
            if name:
                elements = tree.xpath(f'//meta[@name="{name}"]/@content')
            elif property:
                elements = tree.xpath(f'//meta[@property="{property}"]/@content')
            else:
                return None
            return elements[0] if elements else None

        def get_link(rel: str) -> Optional[str]:
            elements = tree.xpath(f'//link[@rel="{rel}"]/@href')
            return elements[0] if elements else None

        return ScrapeMetadata(
            description=get_meta(name="description"),
            keywords=get_meta(name="keywords"),
            ogTitle=get_meta(property="og:title"),
            ogDescription=get_meta(property="og:description"),
            ogImage=get_meta(property="og:image"),
            author=get_meta(name="author"),
            canonical=get_link("canonical")
        )
    except Exception as e:
        print(f"[SCRAPE] Error extracting metadata: {e}")
        return ScrapeMetadata()


def extract_main_content(html_content: str) -> Optional[str]:
    """Extract main readable content using Mozilla's Readability algorithm"""
    try:
        doc = Document(html_content)
        summary_html = doc.summary()
        # Convert HTML to plain text
        tree = lxml_html.fromstring(summary_html)
        text = tree.text_content()
        # Clean up whitespace
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return '\n'.join(lines)
    except Exception as e:
        print(f"[SCRAPE] Error extracting main content: {e}")
        return None


@app.get("/scrape", response_model=ScrapeResponse)
async def scrape_website(
    url: str = Query(..., description="Target URL to scrape"),
    waitForSelector: Optional[str] = Query(None, description="CSS selector to wait for before scraping"),
    timeout: Optional[int] = Query(30000, description="Max wait time in milliseconds"),
    screenshot: Optional[bool] = Query(False, description="Return base64 PNG screenshot")
):
    """
    Scrape a website with JavaScript rendering support via Playwright.

    Uses Tor proxy if USE_TOR_PROXY is enabled.
    Waits for JavaScript to finish loading (networkidle) by default.
    """
    start_time = time.time()

    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    # Validate URL
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    print(f"[SCRAPE] Starting scrape for: {url}")
    print(f"[SCRAPE] Options: waitForSelector={waitForSelector}, timeout={timeout}, screenshot={screenshot}")

    if settings.USE_TOR_PROXY:
        print(f"[SCRAPE] Using Tor proxy: {settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}")

    browser = None
    playwright = None
    try:
        playwright = await async_playwright().start()

        # Browser launch options
        launch_options = {
            "headless": True,
        }

        # Configure proxy if Tor is enabled
        if settings.USE_TOR_PROXY:
            launch_options["proxy"] = {
                "server": f"socks5://{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}"
            }

        browser = await playwright.chromium.launch(**launch_options)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # Navigate to URL with networkidle wait strategy
        print(f"[SCRAPE] Navigating to {url}")
        await page.goto(url, wait_until="networkidle", timeout=timeout)

        # Wait for custom selector if provided
        if waitForSelector:
            print(f"[SCRAPE] Waiting for selector: {waitForSelector}")
            await page.wait_for_selector(waitForSelector, timeout=timeout)

        # Get final URL (after redirects)
        final_url = page.url
        print(f"[SCRAPE] Final URL: {final_url}")

        # Extract page title
        title = await page.title()

        # Get full HTML
        html_content = await page.content()

        # Get all visible text content
        text_content = await page.evaluate("""
            () => {
                // Remove script and style elements
                const scripts = document.querySelectorAll('script, style, noscript');
                scripts.forEach(el => el.remove());

                // Get text content
                return document.body.innerText || document.body.textContent || '';
            }
        """)

        # Extract metadata
        metadata = extract_metadata_from_html(html_content)

        # Extract main content using Readability
        main_content = extract_main_content(html_content)

        # Take screenshot if requested
        screenshot_base64 = None
        if screenshot:
            print("[SCRAPE] Taking screenshot")
            screenshot_bytes = await page.screenshot(full_page=True)
            screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')

        # Calculate timing
        total_ms = int((time.time() - start_time) * 1000)
        print(f"[SCRAPE] Completed in {total_ms}ms")

        return ScrapeResponse(
            url=final_url,
            title=title or "",
            html=html_content,
            textContent=text_content,
            mainContent=main_content,
            metadata=metadata,
            screenshot=screenshot_base64,
            timing=ScrapeTiming(total_ms=total_ms)
        )

    except PlaywrightTimeout as e:
        print(f"[SCRAPE] Timeout error: {e}")
        raise HTTPException(
            status_code=504,
            detail=f"Page load timeout after {timeout}ms. Try increasing timeout or check if the URL is accessible."
        )
    except Exception as e:
        error_msg = str(e)
        print(f"[SCRAPE] Error: {error_msg}")

        if "net::ERR_PROXY_CONNECTION_FAILED" in error_msg or "SOCKS" in error_msg:
            raise HTTPException(
                status_code=503,
                detail=f"Tor proxy connection failed. Ensure Tor is running at {settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}"
            )

        raise HTTPException(status_code=500, detail=f"Scraping error: {error_msg}")
    finally:
        if browser:
            await browser.close()
        if playwright:
            await playwright.stop()


def extract_columns_and_data(rows: list[dict]) -> tuple[list[str], list[list]]:
    # Get the union of all column names from all rows
    column_names = sorted(set().union(*(row.keys() for row in rows)))
    
    # Create the matrix of row values with consistent column order
    data = [[row.get(col) for col in column_names] for row in rows]
    
    return column_names, data
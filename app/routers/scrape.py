from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Query
import asyncio
import time
import base64
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from playwright_stealth import Stealth
from readability import Document
from lxml import html as lxml_html
from app.proxy import get_playwright_proxy, rotate_session

router = APIRouter(tags=["scraping"])

# Cap concurrent Chromium instances to prevent resource exhaustion under burst traffic
_browser_semaphore = asyncio.Semaphore(3)

# Total navigation attempts before giving up; retries rotate the proxy exit IP between tries
_MAX_SCRAPE_ATTEMPTS = 3

# After the DOM is parsed, wait this long (ms) for a full "load" before proceeding with the DOM as-is
_LOAD_STATE_BUDGET_MS = 10000


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
        tree = lxml_html.fromstring(summary_html)
        text = tree.text_content()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return '\n'.join(lines)
    except Exception as e:
        print(f"[SCRAPE] Error extracting main content: {e}")
        return None


async def _perform_scrape_attempt(
    url: str,
    waitForSelector: Optional[str],
    timeout: int,
    screenshot: bool,
    isFree: bool,
    start_time: float,
    attempt: int,
) -> ScrapeResponse:
    """
    Run a single scrape attempt with its own browser → context → page lifecycle.

    Builds the proxy from the current session ID (rotated by the caller between retries),
    navigates, extracts the page data, and tears everything down in the finally block.
    Raises PlaywrightTimeout or proxy errors so the caller's retry loop can react.
    """
    browser = None
    playwright = None
    context = None
    try:
        # Resolve proxy fresh each attempt so a rotated session ID takes effect
        playwright_proxy = get_playwright_proxy(is_free=isFree)
        print(f"[SCRAPE] Attempt {attempt}/{_MAX_SCRAPE_ATTEMPTS} using proxy: {playwright_proxy['server']}")

        playwright = await async_playwright().start()

        launch_options = {
            "headless": True,
            "proxy": playwright_proxy,
        }

        browser = await playwright.chromium.launch(**launch_options)
        context = await browser.new_context()
        page = await context.new_page()
        # Patch automation signals (navigator.webdriver, plugins, UA data, etc.)
        await Stealth().apply_stealth_async(page)

        print(f"[SCRAPE] Navigating to {url}")
        # Commit on domcontentloaded (fires reliably even when a sub-resource hangs and "load" never does)
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        # Prefer a full load, but don't fail if it never fires (hanging trackers/ads/long-polls)
        try:
            await page.wait_for_load_state("load", timeout=_LOAD_STATE_BUDGET_MS)
        except PlaywrightTimeout:
            pass  # "load" not reached within budget, proceed with the parsed DOM
        # Let late client-side JS settle (key for SPAs); non-fatal on sites with persistent network activity
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except PlaywrightTimeout:
            pass  # networkidle not reached within grace period, proceed with loaded DOM

        if waitForSelector:
            print(f"[SCRAPE] Waiting for selector: {waitForSelector}")
            await page.wait_for_selector(waitForSelector, timeout=timeout)

        final_url = page.url
        print(f"[SCRAPE] Final URL: {final_url}")

        title = await page.title()
        html_content = await page.content()

        text_content = await page.evaluate("""
            () => {
                if (!document.body) return '';
                const scripts = document.querySelectorAll('script, style, noscript');
                scripts.forEach(el => el.remove());
                return document.body.innerText || document.body.textContent || '';
            }
        """)

        metadata = extract_metadata_from_html(html_content)
        main_content = extract_main_content(html_content)

        screenshot_base64 = None
        if screenshot:
            print("[SCRAPE] Taking screenshot")
            screenshot_bytes = await page.screenshot(full_page=True)
            screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')

        total_ms = int((time.time() - start_time) * 1000)
        print(f"[SCRAPE] Completed in {total_ms}ms on attempt {attempt}")

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
    finally:
        # Always tear down this attempt's browser stack before retrying or returning
        if context:
            await context.close()
        if browser:
            await browser.close()
        if playwright:
            await playwright.stop()


@router.get("/scrape", response_model=ScrapeResponse)
async def scrape_website(
    url: str = Query(..., description="Target URL to scrape"),
    waitForSelector: Optional[str] = Query(None, description="CSS selector to wait for before scraping"),
    timeout: Optional[int] = Query(30000, description="Max wait time in milliseconds"),
    screenshot: Optional[bool] = Query(False, description="Return base64 PNG screenshot"),
    isFree: Optional[bool] = Query(False, description="Use free Tor proxy instead of paid residential proxy")
):
    """
    Scrape a website with JavaScript rendering support via Playwright.

    Retries up to _MAX_SCRAPE_ATTEMPTS times, rotating the residential proxy exit IP
    between tries, so a single slow/stuck IP no longer fails the whole request.

    Uses proxy based on isFree parameter:
    - isFree=true: Uses Tor SOCKS5 proxy (free but slower)
    - isFree=false: Uses paid residential proxy (faster, better success rate)
    """
    start_time = time.time()

    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    print(f"[SCRAPE] Starting scrape for: {url}")
    print(f"[SCRAPE] Options: waitForSelector={waitForSelector}, timeout={timeout}, screenshot={screenshot}, isFree={isFree}")

    # Queue requests when browser limit is reached to prevent resource exhaustion
    async with _browser_semaphore:
        last_exc: Optional[Exception] = None

        # Retry only for paid proxy (we can rotate its exit IP here). For Tor, do a single
        # attempt: its rotation happens via /tor/new-identity, coordinated by the caller.
        max_attempts = 1 if isFree else _MAX_SCRAPE_ATTEMPTS

        for attempt in range(1, max_attempts + 1):
            # On retries, rotate to a fresh residential exit IP (paid proxy only; Tor rotates via its control port)
            if attempt > 1 and not isFree:
                new_session = rotate_session()
                print(f"[SCRAPE] Rotated proxy session to {new_session} before attempt {attempt}")

            try:
                return await _perform_scrape_attempt(
                    url=url,
                    waitForSelector=waitForSelector,
                    timeout=timeout,
                    screenshot=screenshot,
                    isFree=isFree,
                    start_time=start_time,
                    attempt=attempt,
                )
            except PlaywrightTimeout as e:
                # Timeouts are retryable: a different exit IP may load the page in time
                last_exc = e
                print(f"[SCRAPE] Attempt {attempt}/{_MAX_SCRAPE_ATTEMPTS} timed out")
            except Exception as e:
                error_msg = str(e)
                is_proxy_error = (
                    "net::ERR_PROXY_CONNECTION_FAILED" in error_msg
                    or "SOCKS" in error_msg
                    or "proxy" in error_msg.lower()
                )
                # Proxy connection failures are retryable; anything else fails fast
                if is_proxy_error:
                    last_exc = e
                    print(f"[SCRAPE] Attempt {attempt}/{_MAX_SCRAPE_ATTEMPTS} proxy error: {error_msg}")
                else:
                    print(f"[SCRAPE] Non-retryable error: {error_msg}")
                    raise HTTPException(status_code=500, detail=f"Scraping error: {error_msg}")

        # All attempts exhausted - surface the appropriate final error
        if isinstance(last_exc, PlaywrightTimeout):
            print(f"[SCRAPE] Giving up after {max_attempts} timed-out attempt(s)")
            raise HTTPException(
                status_code=504,
                detail=f"Page load timeout after {max_attempts} attempt(s) ({timeout}ms each). Try increasing timeout or check if the URL is accessible."
            )
        print(f"[SCRAPE] Giving up after {max_attempts} proxy failure(s)")
        raise HTTPException(
            status_code=503,
            detail=f"Proxy connection failed after {max_attempts} attempt(s). Check proxy configuration."
        )

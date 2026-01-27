from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Query
import time
import base64
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from readability import Document
from lxml import html as lxml_html
from app.proxy import get_playwright_proxy, get_proxy

router = APIRouter(tags=["scraping"])


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

    Uses proxy based on isFree parameter:
    - isFree=true: Uses Tor SOCKS5 proxy (free but slower)
    - isFree=false: Uses paid residential proxy (faster, better success rate)
    """
    start_time = time.time()

    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    proxy_config = get_proxy(is_free=isFree)
    print(f"[SCRAPE] Starting scrape for: {url}")
    print(f"[SCRAPE] Options: waitForSelector={waitForSelector}, timeout={timeout}, screenshot={screenshot}, isFree={isFree}")
    print(f"[SCRAPE] Using proxy: {proxy_config.provider}")

    browser = None
    playwright = None
    try:
        playwright = await async_playwright().start()

        launch_options = {
            "headless": True,
            "proxy": get_playwright_proxy(is_free=isFree)
        }

        browser = await playwright.chromium.launch(**launch_options)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        print(f"[SCRAPE] Navigating to {url}")
        await page.goto(url, wait_until="networkidle", timeout=timeout)

        if waitForSelector:
            print(f"[SCRAPE] Waiting for selector: {waitForSelector}")
            await page.wait_for_selector(waitForSelector, timeout=timeout)

        final_url = page.url
        print(f"[SCRAPE] Final URL: {final_url}")

        title = await page.title()
        html_content = await page.content()

        text_content = await page.evaluate("""
            () => {
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

        if "net::ERR_PROXY_CONNECTION_FAILED" in error_msg or "SOCKS" in error_msg or "proxy" in error_msg.lower():
            raise HTTPException(
                status_code=503,
                detail=f"Proxy connection failed ({proxy_config.provider}). Check proxy configuration."
            )

        raise HTTPException(status_code=500, detail=f"Scraping error: {error_msg}")
    finally:
        if browser:
            await browser.close()
        if playwright:
            await playwright.stop()

import asyncio
from fastapi import APIRouter, HTTPException, Query
from typing import Any, Callable, Optional
from requests.exceptions import ConnectionError as RequestsConnectionError, Timeout as RequestsTimeout
from youtube_transcript_api import YouTubeTranscriptApi, RequestBlocked
from youtube_transcript_api.proxies import GenericProxyConfig
from app.proxy import get_proxy, rotate_session

router = APIRouter(prefix="/yt", tags=["youtube"])

# Total attempts per request (paid proxy only); retries rotate the proxy exit IP between tries
_MAX_YT_ATTEMPTS = 3


def get_youtube_api_client(is_free: bool = False) -> YouTubeTranscriptApi:
    """
    Create a YouTubeTranscriptApi client with proxy configuration.

    Args:
        is_free: If True, use Tor (free). If False, use paid residential proxy.
    """
    proxy_config = get_proxy(is_free)
    print(f"[YT] Using proxy: {proxy_config.provider}")

    ytt_proxy = GenericProxyConfig(
        http_url=proxy_config.http_url,
        https_url=proxy_config.https_url,
    )
    return YouTubeTranscriptApi(proxy_config=ytt_proxy)


def _is_retryable(exc: Exception) -> bool:
    """
    Decide whether a failed YouTube call is worth retrying on a fresh exit IP.
    True for proxy/connection failures (incl. gateway 504 tunnel errors) and YouTube IP blocks.
    """
    return isinstance(exc, (RequestsConnectionError, RequestsTimeout, RequestBlocked))


async def _run_with_rotation(label: str, is_free: bool, op: Callable[[YouTubeTranscriptApi], Any]) -> Any:
    """
    Run `op` with a proxied client, retrying up to _MAX_YT_ATTEMPTS times (paid proxy only)
    and rotating the residential session before each retry. The blocking HTTP call runs in a
    worker thread so the event loop stays free. Re-raises the last error once attempts run out.
    """
    # Tor rotates via /proxy/new-identity, so it gets a single attempt
    max_attempts = 1 if is_free else _MAX_YT_ATTEMPTS
    last_exc: Optional[Exception] = None

    for attempt in range(1, max_attempts + 1):
        # On retries, switch to a fresh residential exit IP before rebuilding the client
        if attempt > 1:
            new_session = rotate_session()
            print(f"[{label}] Rotated proxy session to {new_session} before attempt {attempt}")

        try:
            # Build the client per attempt so the (possibly rotated) session ID takes effect
            client = get_youtube_api_client(is_free=is_free)
            return await asyncio.to_thread(op, client)
        except Exception as e:
            # Non-retryable errors (no transcript, unavailable video, ...) fail fast
            if not _is_retryable(e):
                raise
            last_exc = e
            print(f"[{label}] Attempt {attempt}/{max_attempts} failed: {e}")

    # All attempts exhausted - surface the last retryable error
    raise last_exc


def _to_http_error(label: str, exc: Exception, is_free: bool) -> HTTPException:
    """
    Map a YouTube/proxy exception to the endpoint's HTTP error:
    503 for connection/proxy failures, 429 for YouTube IP blocks, 404 otherwise.
    """
    error_msg = str(exc)
    attempts = 1 if is_free else _MAX_YT_ATTEMPTS

    # YouTube blocked every exit IP we tried
    if isinstance(exc, RequestBlocked) or "IpBlocked" in error_msg or "429" in error_msg:
        print(f"[{label}] IP blocked by YouTube: {error_msg}")
        if is_free:
            return HTTPException(status_code=429, detail="YouTube has blocked this IP. Try requesting a new Tor identity via POST /proxy/new-identity?isFree=true")
        return HTTPException(status_code=429, detail=f"YouTube blocked the proxy IP on all {attempts} attempt(s), each with a rotated session.")

    # Proxy or network failure on every attempt
    if isinstance(exc, (RequestsConnectionError, RequestsTimeout)) or "Connection" in error_msg or "timeout" in error_msg.lower():
        print(f"[{label}] Connection error: {error_msg}")
        return HTTPException(status_code=503, detail=f"Connection error after {attempts} attempt(s): {error_msg}")

    # Anything else (no transcript, video unavailable, ...)
    print(f"[{label}] Error: {error_msg}")
    return HTTPException(status_code=404, detail=error_msg)


@router.get("")
async def get_youtube_transcript(
    videoId: str,
    language: str,
    isFree: Optional[bool] = Query(False, description="Use free Tor proxy instead of paid residential proxy")
):
    """
    Fetch the transcript of a video in the requested language.
    Retries with a rotated paid-proxy session on proxy failures and IP blocks.
    """
    print(f"[YT] Getting transcript for video {videoId} in language {language}, isFree={isFree}")
    try:
        transcript = await _run_with_rotation(
            "YT", isFree, lambda c: c.fetch(videoId, languages=[language]).to_raw_data()
        )
        return {"transcript": transcript}
    except Exception as e:
        raise _to_http_error("YT", e, isFree)


@router.get("-list")
async def get_available_transcripts(
    videoId: str,
    isFree: Optional[bool] = Query(False, description="Use free Tor proxy instead of paid residential proxy")
):
    """
    List the transcript tracks available for a video.
    Retries with a rotated paid-proxy session on proxy failures and IP blocks.
    """
    print(f"[YT-LIST] Getting available transcripts for video {videoId}, isFree={isFree}")

    def list_tracks(client: YouTubeTranscriptApi) -> list:
        # Map each track to a plain dict inside the worker thread
        return [
            {
                "language": t.language,
                "language_code": t.language_code,
                "is_generated": t.is_generated,
                "is_translatable": t.is_translatable
            }
            for t in client.list(videoId)
        ]

    try:
        available_transcripts = await _run_with_rotation("YT-LIST", isFree, list_tracks)
        return {"available_transcripts": available_transcripts}
    except Exception as e:
        raise _to_http_error("YT-LIST", e, isFree)

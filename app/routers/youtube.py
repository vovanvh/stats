import asyncio
from fastapi import APIRouter, HTTPException, Query
from typing import Any, Callable, Dict, Iterable, List, Optional
from requests.exceptions import ConnectionError as RequestsConnectionError, Timeout as RequestsTimeout
from youtube_transcript_api import YouTubeTranscriptApi, RequestBlocked
from youtube_transcript_api._transcripts import TranscriptListFetcher
from youtube_transcript_api.proxies import GenericProxyConfig
from app.proxy import get_proxy, rotate_session

router = APIRouter(prefix="/yt", tags=["youtube"])

# Total attempts per request (paid proxy only); retries rotate the proxy exit IP between tries
_MAX_YT_ATTEMPTS = 3

# An innertube audio track id is "<language>.<n>" (e.g. "en-US.4"); the language part may carry a region
_AUDIO_TRACK_ID_SEPARATOR = "."
_LANG_REGION_SEPARATOR = "-"


class _AudioTrackAwareFetcher(TranscriptListFetcher):
    """
    Transcript list fetcher that also keeps the `streamingData.adaptiveFormats` of the innertube player
    response the library already requests, so the original audio language of an auto-dubbed video is
    known without a second YouTube call. Relies on the private API of the pinned youtube-transcript-api
    1.2.3 (`TranscriptListFetcher._extract_captions_json`); re-check both names on a version bump.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Adaptive formats of the last `list()` call; [] until one succeeded
        self.adaptive_formats: List[Dict[str, Any]] = []

    def _extract_captions_json(self, innertube_data: Dict, video_id: str) -> Dict:
        # Keep the audio formats before the library discards everything but the captions
        streaming_data = innertube_data.get("streamingData") or {}
        formats = streaming_data.get("adaptiveFormats") or []
        self.adaptive_formats = formats if isinstance(formats, list) else []
        return super()._extract_captions_json(innertube_data, video_id)


def _base_language(code: str) -> str:
    """Strip the region of a BCP-47 code and lower-case it: "en-US" -> "en"."""
    return (code or "").split(_LANG_REGION_SEPARATOR)[0].strip().lower()


def _audio_track_language(audio_track: Dict[str, Any]) -> str:
    """Language part of an innertube audio track id without its region: "en-US.4" -> "en"."""
    track_id = str(audio_track.get("id") or "")
    return _base_language(track_id.split(_AUDIO_TRACK_ID_SEPARATOR)[0])


def resolve_original_language_code(adaptive_formats: Iterable[Dict[str, Any]], tracks: Iterable[Dict[str, Any]]) -> Optional[str]:
    """
    Language code of the video's original audio, derived from the player's audio tracks:
    the default track that is not auto-dubbed, else the only non-dubbed one. A video without audio
    tracks resolves to its single auto-generated caption track. None when undetermined or when no
    listed caption track has that language.
    """
    tracks = list(tracks)

    # Unique audio tracks by id; a video has one format entry per bitrate for the same track
    audio_tracks: Dict[str, Dict[str, Any]] = {}
    for fmt in adaptive_formats:
        audio_track = fmt.get("audioTrack") if isinstance(fmt, dict) else None
        if isinstance(audio_track, dict) and audio_track.get("id"):
            audio_tracks.setdefault(str(audio_track["id"]), audio_track)

    candidate: Optional[str] = None
    if audio_tracks:
        # Original = the default track that is not an auto-dub, else the single non-dubbed track
        not_dubbed = [t for t in audio_tracks.values() if not t.get("isAutoDubbed")]
        default = [t for t in not_dubbed if t.get("audioIsDefault")]
        if default:
            candidate = _audio_track_language(default[0])
        elif len(not_dubbed) == 1:
            candidate = _audio_track_language(not_dubbed[0])
    else:
        # No audio track metadata: a single auto-generated caption track is the spoken language
        generated = [t for t in tracks if t.get("is_generated")]
        if len(generated) == 1:
            candidate = _base_language(str(generated[0].get("language_code") or ""))

    # The code is only useful when a listed caption track carries that language
    if not candidate:
        return None
    if not any(_base_language(str(t.get("language_code") or "")) == candidate for t in tracks):
        return None
    return candidate


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
    client = YouTubeTranscriptApi(proxy_config=ytt_proxy)
    # Swap in the fetcher that keeps the audio tracks (same session and proxy config)
    client._fetcher = _AudioTrackAwareFetcher(client._fetcher._http_client, proxy_config=ytt_proxy)
    return client


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
    List the transcript tracks available for a video plus the original audio language
    (`original_language_code`, null when undetermined), so auto-dubbed videos resolve to their
    spoken language. Retries with a rotated paid-proxy session on proxy failures and IP blocks.
    """
    print(f"[YT-LIST] Getting available transcripts for video {videoId}, isFree={isFree}")

    def list_tracks(client: YouTubeTranscriptApi) -> dict:
        # Map each track to a plain dict inside the worker thread
        available_transcripts = [
            {
                "language": t.language,
                "language_code": t.language_code,
                "is_generated": t.is_generated,
                "is_translatable": t.is_translatable
            }
            for t in client.list(videoId)
        ]

        # Audio tracks kept by the fetcher during that same request; absent on a plain client
        adaptive_formats = getattr(getattr(client, "_fetcher", None), "adaptive_formats", None)
        if not isinstance(adaptive_formats, list):
            adaptive_formats = []

        return {
            "available_transcripts": available_transcripts,
            "original_language_code": resolve_original_language_code(adaptive_formats, available_transcripts),
        }

    try:
        return await _run_with_rotation("YT-LIST", isFree, list_tracks)
    except Exception as e:
        raise _to_http_error("YT-LIST", e, isFree)

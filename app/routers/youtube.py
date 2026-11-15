import asyncio
from enum import Enum
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Type
from requests.exceptions import ConnectionError as RequestsConnectionError, Timeout as RequestsTimeout
from youtube_transcript_api import (
    AgeRestricted,
    InvalidVideoId,
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeTranscriptApi,
)
from youtube_transcript_api._transcripts import TranscriptListFetcher
from youtube_transcript_api.proxies import GenericProxyConfig
from app.proxy import get_proxy, rotate_session

router = APIRouter(prefix="/yt", tags=["youtube"])

# Total attempts per request (paid proxy only); retries rotate the proxy exit IP between tries
_MAX_YT_ATTEMPTS = 3

# An innertube audio track id is "<language>.<n>" (e.g. "en-US.4"); the language part may carry a region
_AUDIO_TRACK_ID_SEPARATOR = "."
_LANG_REGION_SEPARATOR = "-"

# Keys of the JSON body every `/yt` / `/yt-list` error answers with
ERROR_DETAIL_KEY = "detail"
ERROR_REASON_KEY = "reason"

# HTTP statuses of the error answers (unchanged by VBM-593)
_STATUS_NOT_FOUND = 404
_STATUS_BLOCKED = 429
_STATUS_UNREACHABLE = 503


class YtErrorReason(str, Enum):
    """
    Machine-readable cause of a `/yt` / `/yt-list` error, sent as `reason` next to `detail`.
    The first five are definitive for callers (never worth a retry); the rest are not.
    """

    VIDEO_UNAVAILABLE = "video_unavailable"
    TRANSCRIPTS_DISABLED = "transcripts_disabled"
    NO_TRANSCRIPT = "no_transcript"
    AGE_RESTRICTED = "age_restricted"
    INVALID_VIDEO_ID = "invalid_video_id"
    VIDEO_UNPLAYABLE = "video_unplayable"
    OTHER = "other"
    REQUEST_BLOCKED = "request_blocked"
    CONNECTION_ERROR = "connection_error"


# Library error class -> 404 reason; checked by type before any text check
_LIBRARY_ERROR_REASONS: Tuple[Tuple[Type[Exception], YtErrorReason], ...] = (
    (VideoUnavailable, YtErrorReason.VIDEO_UNAVAILABLE),
    (TranscriptsDisabled, YtErrorReason.TRANSCRIPTS_DISABLED),
    (NoTranscriptFound, YtErrorReason.NO_TRANSCRIPT),
    (AgeRestricted, YtErrorReason.AGE_RESTRICTED),
    (InvalidVideoId, YtErrorReason.INVALID_VIDEO_ID),
    (VideoUnplayable, YtErrorReason.VIDEO_UNPLAYABLE),
)

# Lower-case fragments of a `VideoUnplayable` cause that mean the video is gone for good (VBM-597);
# such a video answers `video_unavailable` instead of `video_unplayable`. Covered YouTube texts:
# - "has been removed": "This video has been removed by the uploader", "...removed for violating
#   YouTube's Terms of Service / Community Guidelines", "...removed for violating YouTube's policy..."
# - "no longer available": "...no longer available due to a copyright claim by X", "...because the YouTube
#   account associated with this video has been terminated", "...has been closed"
# - "blocked it on copyright grounds": "...who has blocked it on copyright grounds" (not the geo-only
#   "blocked it in your country on copyright grounds", which stays `video_unplayable`)
_REMOVED_VIDEO_CAUSE_MARKERS: Tuple[str, ...] = (
    "has been removed",
    "no longer available",
    "blocked it on copyright grounds",
)


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


def _is_removed_video(exc: Exception) -> bool:
    """
    True when an unplayable error's cause (`reason` or any `sub_reasons` item) says the video
    was removed for good; matched case-insensitively against _REMOVED_VIDEO_CAUSE_MARKERS.
    """
    # Collect the cause texts; bare instances may lack both attributes
    causes = [getattr(exc, "reason", None), *(getattr(exc, "sub_reasons", None) or [])]
    texts = [str(cause).lower() for cause in causes if cause]

    # Any marker in any cause text marks the video as removed
    return any(marker in text for text in texts for marker in _REMOVED_VIDEO_CAUSE_MARKERS)


def _library_reason(exc: Exception) -> Optional[YtErrorReason]:
    """
    Reason code of a mapped youtube-transcript-api error, matched by type.
    An unplayable video whose cause says it was removed gives `video_unavailable`.
    None when the error is not one of the mapped library classes.
    """
    # First matching class wins; the mapped classes do not inherit from each other
    for error_class, reason in _LIBRARY_ERROR_REASONS:
        if isinstance(exc, error_class):
            # A removed video is gone for good, so it gets the definitive reason
            if reason is YtErrorReason.VIDEO_UNPLAYABLE and _is_removed_video(exc):
                return YtErrorReason.VIDEO_UNAVAILABLE
            return reason
    return None


def _error_response(status_code: int, detail: str, reason: YtErrorReason) -> JSONResponse:
    """Build the `{detail, reason}` error body of `/yt` and `/yt-list`."""
    return JSONResponse(status_code=status_code, content={ERROR_DETAIL_KEY: detail, ERROR_REASON_KEY: reason.value})


def _to_error_response(label: str, exc: Exception, is_free: bool) -> JSONResponse:
    """
    Map a YouTube/proxy exception to the endpoint's error answer `{detail, reason}`:
    mapped library errors give 404 with their reason first, then 429 for IP blocks,
    503 for connection/proxy failures and 404 `other` for everything else.
    """
    error_msg = str(exc)
    attempts = 1 if is_free else _MAX_YT_ATTEMPTS

    # Known library errors are classified by type, before any text match can misread them
    reason = _library_reason(exc)
    if reason is not None:
        print(f"[{label}] Error ({reason.value}): {error_msg}")
        return _error_response(_STATUS_NOT_FOUND, error_msg, reason)

    # YouTube blocked every exit IP we tried
    if isinstance(exc, RequestBlocked) or "IpBlocked" in error_msg or "429" in error_msg:
        print(f"[{label}] IP blocked by YouTube: {error_msg}")
        if is_free:
            detail = "YouTube has blocked this IP. Try requesting a new Tor identity via POST /proxy/new-identity?isFree=true"
        else:
            detail = f"YouTube blocked the proxy IP on all {attempts} attempt(s), each with a rotated session."
        return _error_response(_STATUS_BLOCKED, detail, YtErrorReason.REQUEST_BLOCKED)

    # Proxy or network failure on every attempt
    if isinstance(exc, (RequestsConnectionError, RequestsTimeout)) or "Connection" in error_msg or "timeout" in error_msg.lower():
        print(f"[{label}] Connection error: {error_msg}")
        return _error_response(
            _STATUS_UNREACHABLE, f"Connection error after {attempts} attempt(s): {error_msg}", YtErrorReason.CONNECTION_ERROR
        )

    # Anything else (unparsable data, PO token, other request failures, ...)
    print(f"[{label}] Error: {error_msg}")
    return _error_response(_STATUS_NOT_FOUND, error_msg, YtErrorReason.OTHER)


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
        # Answer `{detail, reason}` with the classified status
        return _to_error_response("YT", e, isFree)


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
        # Answer `{detail, reason}` with the classified status
        return _to_error_response("YT-LIST", e, isFree)

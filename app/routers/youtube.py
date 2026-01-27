from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig
from app.proxy import get_proxy

router = APIRouter(prefix="/yt", tags=["youtube"])


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


@router.get("")
async def get_youtube_transcript(
    videoId: str,
    language: str,
    isFree: Optional[bool] = Query(False, description="Use free Tor proxy instead of paid residential proxy")
):
    try:
        print(f"[YT] Getting transcript for video {videoId} in language {language}, isFree={isFree}")

        ytt_api = get_youtube_api_client(is_free=isFree)
        transcript = ytt_api.fetch(videoId, languages=[language])

        return {"transcript": transcript.to_raw_data()}
    except Exception as e:
        error_msg = str(e)
        if "Connection" in error_msg or "timeout" in error_msg.lower():
            print(f"[YT] Connection error: {error_msg}")
            raise HTTPException(status_code=503, detail=f"Connection error: {error_msg}")
        if "IpBlocked" in error_msg or "429" in error_msg:
            print(f"[YT] IP blocked by YouTube: {error_msg}")
            if isFree:
                raise HTTPException(status_code=429, detail="YouTube has blocked this IP. Try requesting a new Tor identity via POST /proxy/new-identity?isFree=true")
            else:
                raise HTTPException(status_code=429, detail="YouTube has blocked this IP. The paid proxy provider may need to rotate IPs.")
        print(f"[YT] Error: {error_msg}")
        raise HTTPException(status_code=404, detail=error_msg)


@router.get("-list")
async def get_available_transcripts(
    videoId: str,
    isFree: Optional[bool] = Query(False, description="Use free Tor proxy instead of paid residential proxy")
):
    try:
        print(f"[YT-LIST] Getting available transcripts for video {videoId}, isFree={isFree}")

        ytt_api = get_youtube_api_client(is_free=isFree)
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
            print(f"[YT-LIST] Connection error: {error_msg}")
            raise HTTPException(status_code=503, detail=f"Connection error: {error_msg}")
        if "IpBlocked" in error_msg or "429" in error_msg:
            print(f"[YT-LIST] IP blocked by YouTube: {error_msg}")
            if isFree:
                raise HTTPException(status_code=429, detail="YouTube has blocked this IP. Try requesting a new Tor identity via POST /proxy/new-identity?isFree=true")
            else:
                raise HTTPException(status_code=429, detail="YouTube has blocked this IP. The paid proxy provider may need to rotate IPs.")
        print(f"[YT-LIST] Error: {error_msg}")
        raise HTTPException(status_code=404, detail=error_msg)

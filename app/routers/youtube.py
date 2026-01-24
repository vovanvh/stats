from fastapi import APIRouter, HTTPException
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig
from app.config import settings

router = APIRouter(prefix="/yt", tags=["youtube"])


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


@router.get("")
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


@router.get("-list")
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

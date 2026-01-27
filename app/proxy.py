import uuid
from dataclasses import dataclass
from urllib.parse import quote
from app.config import settings


# Global session ID - reset this to get a new IP
_current_session_id: str = str(uuid.uuid4())[:16]


@dataclass
class ProxyConfig:
    """Proxy configuration for HTTP/SOCKS requests"""
    http_url: str
    https_url: str
    provider: str
    session_id: str = ""


def get_session_id() -> str:
    """Get current session ID"""
    return _current_session_id


def rotate_session() -> str:
    """Generate a new session ID to get a new IP from residential proxies"""
    global _current_session_id
    _current_session_id = str(uuid.uuid4())[:16]
    return _current_session_id


def get_tor_proxy() -> ProxyConfig:
    """Get Tor SOCKS5 proxy configuration"""
    url = f"socks5://{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}"
    return ProxyConfig(http_url=url, https_url=url, provider="tor")


def _build_proxy_url(provider: str, session_id: str) -> tuple[str, str, int]:
    """
    Build a proxy username with session ID for each provider.
    Returns (username, password, port)
    """
    if provider == "brightdata":
        # Format: user-session-{id}
        base_user = settings.BRIGHTDATA_USERNAME
        username = f"{base_user}-session-{session_id}"
        return username, settings.BRIGHTDATA_PASSWORD, settings.BRIGHTDATA_HOST, settings.BRIGHTDATA_PORT

    elif provider == "oxylabs":
        # Format: customer-{user}-sessid-{id}
        base_user = settings.OXYLABS_USERNAME
        username = f"customer-{base_user}-sessid-{session_id}"
        return username, settings.OXYLABS_PASSWORD, settings.OXYLABS_HOST, settings.OXYLABS_PORT

    elif provider == "smartproxy":
        # Format: user-session-{id}
        base_user = settings.SMARTPROXY_USERNAME
        username = f"{base_user}-session-{session_id}"
        return username, settings.SMARTPROXY_PASSWORD, settings.SMARTPROXY_HOST, settings.SMARTPROXY_PORT

    elif provider == "iproyal":
        # Format: user_session-{id}_sessionTime-{minutes}
        base_user = settings.IPROYAL_USERNAME
        username = f"{base_user}_session-{session_id}_sessionTime-10"
        return username, settings.IPROYAL_PASSWORD, settings.IPROYAL_HOST, settings.IPROYAL_PORT

    elif provider == "floppydata":
        # Format: user-{USER}-type-residential-session-{SESSION_ID}-country-{CC}-city-{CITY}-rotation-{MIN}
        # rotation: 0=sticky (we control via session ID), -1=per-request, 1-60=minutes
        base_user = settings.FLOPPYDATA_USERNAME
        country = settings.FLOPPYDATA_COUNTRY
        city = settings.FLOPPYDATA_CITY
        rotation = settings.FLOPPYDATA_ROTATION

        username = f"user-{base_user}-type-residential-session-{session_id}-country-{country}"
        if city:
            username += f"-city-{city}"
        username += f"-rotation-{rotation}"

        return username, settings.FLOPPYDATA_PASSWORD, settings.FLOPPYDATA_HOST, settings.FLOPPYDATA_PORT

    else:
        raise ValueError(f"Unknown proxy provider: {provider}")


def get_paid_proxy() -> ProxyConfig:
    """Get paid residential proxy configuration based on PROXY_PROVIDER setting"""
    provider = settings.PROXY_PROVIDER.lower()
    session_id = get_session_id()

    if provider == "brightdata":
        if not settings.BRIGHTDATA_USERNAME or not settings.BRIGHTDATA_PASSWORD:
            raise ValueError("Proxy credentials not configured for brightdata. Set BRIGHTDATA_USERNAME and BRIGHTDATA_PASSWORD")
    elif provider == "oxylabs":
        if not settings.OXYLABS_USERNAME or not settings.OXYLABS_PASSWORD:
            raise ValueError("Proxy credentials not configured for oxylabs. Set OXYLABS_USERNAME and OXYLABS_PASSWORD")
    elif provider == "smartproxy":
        if not settings.SMARTPROXY_USERNAME or not settings.SMARTPROXY_PASSWORD:
            raise ValueError("Proxy credentials not configured for smartproxy. Set SMARTPROXY_USERNAME and SMARTPROXY_PASSWORD")
    elif provider == "iproyal":
        if not settings.IPROYAL_USERNAME or not settings.IPROYAL_PASSWORD:
            raise ValueError("Proxy credentials not configured for iproyal. Set IPROYAL_USERNAME and IPROYAL_PASSWORD")
    elif provider == "floppydata":
        if not settings.FLOPPYDATA_USERNAME or not settings.FLOPPYDATA_PASSWORD:
            raise ValueError("Proxy credentials not configured for floppydata. Set FLOPPYDATA_USERNAME and FLOPPYDATA_PASSWORD")
    else:
        raise ValueError(f"Unknown proxy provider: {provider}. Valid options: brightdata, oxylabs, smartproxy, iproyal, floppydata")

    username, password, host, port = _build_proxy_url(provider, session_id)

    # URL-encode username and password to handle special characters
    encoded_user = quote(username, safe='')
    encoded_pass = quote(password, safe='')

    url = f"http://{encoded_user}:{encoded_pass}@{host}:{port}"
    return ProxyConfig(http_url=url, https_url=url, provider=provider, session_id=session_id)


def get_proxy(is_free: bool = False) -> ProxyConfig:
    """
    Get proxy configuration based on an is_free flag.

    Args:
        is_free: If True, use Tor (free). If False, use paid residential proxy.

    Returns:
        ProxyConfig with http_url and https_url
    """
    if is_free:
        return get_tor_proxy()
    return get_paid_proxy()


def get_playwright_proxy(is_free: bool = False) -> dict:
    """
    Get proxy configuration formatted for Playwright.

    Args:
        is_free: If True, use Tor (free). If False, use paid residential proxy.

    Returns:
        Dict with 'server' key for Playwright launch options
    """
    proxy_config = get_proxy(is_free)
    return {"server": proxy_config.http_url}

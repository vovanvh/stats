from pydantic_settings import BaseSettings
from typing import Optional
import os

class Settings(BaseSettings):
    # Application settings
    APP_NAME: str = os.getenv("APP_NAME", "my-stats")
    APP_VERSION: str = os.getenv("APP_VERSION", "1.0.0")
    APP_ENV: str = os.getenv("APP_ENV", "production")
    DEBUG: bool = os.getenv("DEBUG", False)

    # ClickHouse settings
    CLICKHOUSE_HOST: str = os.getenv("CLICKHOUSE_HOST", "v_clickhouse")
    CLICKHOUSE_PORT: int = os.getenv("CLICKHOUSE_PORT", 8123)
    CLICKHOUSE_USERNAME: Optional[str] = os.getenv("CLICKHOUSE_USERNAME", "root")
    CLICKHOUSE_PASSWORD: Optional[str] = os.getenv("CLICKHOUSE_PASSWORD", "")
    CLICKHOUSE_DATABASE: str = os.getenv("CLICKHOUSE_DATABASE", "default")
    CLICKHOUSE_SECURE: bool = os.getenv("CLICKHOUSE_SECURE", False)

    # Tor proxy settings (free tier)
    TOR_PROXY_HOST: str = os.getenv("TOR_PROXY_HOST", "tor-proxy")
    TOR_PROXY_PORT: int = os.getenv("TOR_PROXY_PORT", 9050)

    # Paid proxy provider selection
    # Options: brightdata, oxylabs, smartproxy, iproyal, floppydata
    PROXY_PROVIDER: str = os.getenv("PROXY_PROVIDER", "floppydata")

    # Bright Data ($15/GB)
    BRIGHTDATA_HOST: str = os.getenv("BRIGHTDATA_HOST", "brd.superproxy.io")
    BRIGHTDATA_PORT: int = int(os.getenv("BRIGHTDATA_PORT", "22225"))
    BRIGHTDATA_USERNAME: str = os.getenv("BRIGHTDATA_USERNAME", "")
    BRIGHTDATA_PASSWORD: str = os.getenv("BRIGHTDATA_PASSWORD", "")

    # Oxylabs ($12/GB)
    OXYLABS_HOST: str = os.getenv("OXYLABS_HOST", "pr.oxylabs.io")
    OXYLABS_PORT: int = int(os.getenv("OXYLABS_PORT", "7777"))
    OXYLABS_USERNAME: str = os.getenv("OXYLABS_USERNAME", "")
    OXYLABS_PASSWORD: str = os.getenv("OXYLABS_PASSWORD", "")

    # Smartproxy ($8/GB)
    SMARTPROXY_HOST: str = os.getenv("SMARTPROXY_HOST", "gate.smartproxy.com")
    SMARTPROXY_PORT: int = int(os.getenv("SMARTPROXY_PORT", "7000"))
    SMARTPROXY_USERNAME: str = os.getenv("SMARTPROXY_USERNAME", "")
    SMARTPROXY_PASSWORD: str = os.getenv("SMARTPROXY_PASSWORD", "")

    # IPRoyal ($5/GB)
    IPROYAL_HOST: str = os.getenv("IPROYAL_HOST", "geo.iproyal.com")
    IPROYAL_PORT: int = int(os.getenv("IPROYAL_PORT", "12321"))
    IPROYAL_USERNAME: str = os.getenv("IPROYAL_USERNAME", "")
    IPROYAL_PASSWORD: str = os.getenv("IPROYAL_PASSWORD", "")

    # FloppyData ($1/GB)
    # Ports: 10080 (HTTP), 10443 (HTTPS), 10800 (SOCKS5)
    FLOPPYDATA_HOST: str = os.getenv("FLOPPYDATA_HOST", "geo.g-w.info")
    FLOPPYDATA_PORT: int = int(os.getenv("FLOPPYDATA_PORT", "10080"))
    FLOPPYDATA_USERNAME: str = os.getenv("FLOPPYDATA_USERNAME", "")
    FLOPPYDATA_PASSWORD: str = os.getenv("FLOPPYDATA_PASSWORD", "")
    FLOPPYDATA_COUNTRY: str = os.getenv("FLOPPYDATA_COUNTRY", "US")
    FLOPPYDATA_CITY: str = os.getenv("FLOPPYDATA_CITY", "New_York")  # Optional: e.g., "New_York"
    FLOPPYDATA_ROTATION: int = int(os.getenv("FLOPPYDATA_ROTATION", "15"))  # 0=sticky, -1=per-request, 1-60=minutes

    class Config:
        case_sensitive = True
        extra = "allow"

settings = Settings() 
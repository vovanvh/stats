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

    class Config:
        case_sensitive = True
        extra = "allow"

settings = Settings() 
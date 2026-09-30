from typing import Optional

from .config import settings
from clickhouse_connect import get_client


def get_clickhouse_client(database: Optional[str] = None):
    """
    Create a ClickHouse client from the app settings.
    `database` overrides CLICKHOUSE_DATABASE (used by the DDL runner and the integration tests).
    """
    return get_client(
        host=settings.CLICKHOUSE_HOST,
        port=settings.CLICKHOUSE_PORT,
        username=settings.CLICKHOUSE_USERNAME,
        password=settings.CLICKHOUSE_PASSWORD,
        database=database or settings.CLICKHOUSE_DATABASE,
        secure=settings.CLICKHOUSE_SECURE
    )

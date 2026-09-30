"""
Apply the versioned ClickHouse DDL files in ddl/ in name order.

Usage: docker exec krys-stats python scripts/apply_ddl.py [--database NAME]
Every file is one idempotent CREATE ... IF NOT EXISTS statement, so re-running is safe.
"""
import argparse
from pathlib import Path
from typing import List, Optional

from app.config import settings
from app.database import get_clickhouse_client
from app.routers.stats import IDENTIFIER_PATTERN

# Folder holding the NNN_<table>.sql files, next to scripts/
DDL_DIR = Path(__file__).resolve().parent.parent / "ddl"


def list_ddl_files() -> List[Path]:
    """
    Return the DDL files sorted by name, so the NNN_ prefix sets the apply order.
    """
    return sorted(DDL_DIR.glob("*.sql"))


def apply_ddl(database: Optional[str] = None) -> List[str]:
    """
    Create the target database if missing, then run every DDL file against it.
    Returns the applied file names in apply order.
    """
    target = database or settings.CLICKHOUSE_DATABASE

    # Refuse a database name that could break out of the CREATE DATABASE statement
    if not IDENTIFIER_PATTERN.match(target):
        raise ValueError(f"invalid database name '{target}'")

    # Create the database through a client bound to the configured default database
    get_clickhouse_client().command(f"CREATE DATABASE IF NOT EXISTS {target}")

    # Run each file in order against the target database
    client = get_clickhouse_client(target)
    applied = []
    for path in list_ddl_files():
        client.command(path.read_text())
        applied.append(path.name)
    return applied


def main() -> None:
    """
    CLI entry point: parse --database, apply the DDL and print one line per applied file.
    """
    # Parse the optional database override
    parser = argparse.ArgumentParser(description="Apply ddl/*.sql to ClickHouse")
    parser.add_argument("--database", default=None, help="target database (default: CLICKHOUSE_DATABASE)")
    args = parser.parse_args()

    # Apply and report each file
    for name in apply_ddl(args.database):
        print(f"applied {name}")


if __name__ == "__main__":
    main()

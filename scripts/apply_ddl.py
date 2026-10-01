"""
Apply the versioned ClickHouse DDL files in ddl/ in name order.

Usage: docker exec krys-stats python scripts/apply_ddl.py [--database NAME]
Every file is one idempotent CREATE ... IF NOT EXISTS statement, so re-running is safe.
After applying, every table's sorting key is checked against its file, because IF NOT EXISTS
keeps a stale table with an old key silently.
"""
import argparse
import re
from pathlib import Path
from typing import List, Optional

from app.config import settings
from app.database import get_clickhouse_client
from app.routers.stats import IDENTIFIER_PATTERN

# Folder holding the NNN_<table>.sql files, next to scripts/
DDL_DIR = Path(__file__).resolve().parent.parent / "ddl"

# Captures the table name of a CREATE TABLE statement
TABLE_NAME_PATTERN = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(\w+)`?", re.I)

# Captures the ORDER BY expression, with or without the surrounding tuple parentheses
SORTING_KEY_PATTERN = re.compile(r"ORDER BY\s+\(?([^)\n]+?)\)?\s*$", re.M)

# Lists every table of one database with its sorting key
SORTING_KEYS_SQL = "SELECT name, sorting_key FROM system.tables WHERE database = {db:String}"


def list_ddl_files() -> List[Path]:
    """
    Return the DDL files sorted by name, so the NNN_ prefix sets the apply order.
    """
    return sorted(DDL_DIR.glob("*.sql"))


def table_name(sql: str) -> str:
    """
    Return the table name created by one DDL statement.
    """
    match = TABLE_NAME_PATTERN.search(sql)
    if not match:
        raise ValueError("DDL file has no CREATE TABLE statement")
    return match.group(1)


def expected_sorting_key(sql: str) -> str:
    """
    Return the ORDER BY key of one DDL statement in ClickHouse's `system.tables.sorting_key` form ("a, b, c").
    """
    match = SORTING_KEY_PATTERN.search(sql)
    if not match:
        raise ValueError("DDL file has no ORDER BY clause")
    # Normalise whitespace around each key column
    return ", ".join(part.strip() for part in match.group(1).split(","))


def verify_sorting_keys(client, database: str, files: List[Path]) -> None:
    """
    Compare every DDL file's sorting key with the live table and raise on the first mismatch.
    A mismatch means the table predates a key change; it must be dropped and re-created.
    """
    # Read the live sorting keys of the target database
    rows = client.query(SORTING_KEYS_SQL, parameters={"db": database}).result_rows
    actual_keys = {name: key for name, key in rows}

    # Fail loudly on the first table whose key differs from its file
    for path in files:
        sql = path.read_text()
        name = table_name(sql)
        expected = expected_sorting_key(sql)
        actual = actual_keys.get(name)
        if actual != expected:
            raise RuntimeError(
                f"{name}: sorting key '{actual}' differs from ddl '{expected}'; DROP TABLE and re-run"
            )


def apply_ddl(database: Optional[str] = None) -> List[str]:
    """
    Create the target database if missing, run every DDL file against it and verify the sorting keys.
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
    files = list_ddl_files()
    applied = []
    for path in files:
        client.command(path.read_text())
        applied.append(path.name)

    # Refuse to finish while an existing table still carries an outdated key
    verify_sorting_keys(client, target, files)
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

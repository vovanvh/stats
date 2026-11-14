from unittest.mock import MagicMock

import pytest

from scripts.apply_ddl import (
    SORTING_KEYS_SQL,
    apply_ddl,
    creates_table,
    expected_sorting_key,
    list_ddl_files,
    table_name,
    verify_sorting_keys,
)

DATABASE = "stats_test"
SINGLE_KEY_SQL = "CREATE TABLE IF NOT EXISTS t1\n(\n    `id` UInt64\n)\nENGINE = MergeTree\nORDER BY id\nSETTINGS index_granularity = 8192\n"
TUPLE_KEY_SQL = "CREATE TABLE IF NOT EXISTS t2\n(\n    `a` Int64\n)\nENGINE = MergeTree\nORDER BY (a,  b ,c)\n"
ALTER_SQL = "-- adds a column\nALTER TABLE t2\n    ADD COLUMN IF NOT EXISTS `d` Nullable(UInt8)\n"


def write_files(tmp_path):
    """Two DDL files on disk: a bare key and a tuple key."""
    first = tmp_path / "001_t1.sql"
    second = tmp_path / "002_t2.sql"
    first.write_text(SINGLE_KEY_SQL)
    second.write_text(TUPLE_KEY_SQL)
    return [first, second]


def stub_client(rows):
    """ClickHouse client whose system.tables query returns `rows`."""
    client = MagicMock()
    client.query.return_value.result_rows = rows
    return client


def test_expected_sorting_key_bare_column():
    assert expected_sorting_key(SINGLE_KEY_SQL) == "id"


def test_expected_sorting_key_tuple_is_normalised():
    assert expected_sorting_key(TUPLE_KEY_SQL) == "a, b, c"


def test_expected_sorting_key_without_order_by_raises():
    with pytest.raises(ValueError):
        expected_sorting_key("CREATE TABLE t ENGINE = Log")


def test_table_name():
    assert table_name(TUPLE_KEY_SQL) == "t2"


def test_repo_app_usage_minute_key_includes_language():
    path = next(p for p in list_ddl_files() if p.name.endswith("appUsageMinute.sql"))

    assert expected_sorting_key(path.read_text()) == "externalId, languageId, minuteTs"


def test_verify_sorting_keys_passes_on_match(tmp_path):
    client = stub_client([("t1", "id"), ("t2", "a, b, c")])

    verify_sorting_keys(client, DATABASE, write_files(tmp_path))

    client.query.assert_called_once_with(SORTING_KEYS_SQL, parameters={"db": DATABASE})


def test_verify_sorting_keys_raises_on_stale_key(tmp_path):
    client = stub_client([("t1", "id"), ("t2", "a, c")])

    with pytest.raises(RuntimeError, match="t2: sorting key 'a, c' differs from ddl 'a, b, c'"):
        verify_sorting_keys(client, DATABASE, write_files(tmp_path))


def test_verify_sorting_keys_raises_on_missing_table(tmp_path):
    client = stub_client([("t1", "id")])

    with pytest.raises(RuntimeError, match="t2: sorting key 'None'"):
        verify_sorting_keys(client, DATABASE, write_files(tmp_path))


def test_creates_table_tells_create_from_alter():
    assert creates_table(TUPLE_KEY_SQL) is True
    assert creates_table(ALTER_SQL) is False


def test_repo_learning_activity_levels_file_is_an_idempotent_alter():
    path = next(p for p in list_ddl_files() if p.name.endswith("learningActivity_levels.sql"))
    sql = path.read_text()

    assert creates_table(sql) is False
    assert sql.count("\n    ADD COLUMN IF NOT EXISTS ") == 3


def test_verify_sorting_keys_skips_alter_files(tmp_path):
    files = write_files(tmp_path)
    alter = tmp_path / "003_t2_extra.sql"
    alter.write_text(ALTER_SQL)
    client = stub_client([("t1", "id"), ("t2", "a, b, c")])

    verify_sorting_keys(client, DATABASE, files + [alter])


def test_apply_ddl_runs_alter_files_and_skips_their_key_check(tmp_path, monkeypatch):
    files = write_files(tmp_path)
    alter = tmp_path / "003_t2_extra.sql"
    alter.write_text(ALTER_SQL)
    client = stub_client([("t1", "id"), ("t2", "a, b, c")])
    monkeypatch.setattr("scripts.apply_ddl.DDL_DIR", tmp_path)
    monkeypatch.setattr("scripts.apply_ddl.get_clickhouse_client", lambda *args: client)

    applied = apply_ddl(DATABASE)

    assert applied == [files[0].name, files[1].name, alter.name]
    assert client.command.call_args_list[-1].args == (ALTER_SQL,)

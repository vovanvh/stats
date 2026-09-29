from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import stats

LIKE_DISLIKE_TABLE = "LikeDislikeStats"
VOCABULARY_SR_TABLE = "vocabularySR"


@pytest.fixture
def insert_mock(monkeypatch):
    """Replace the ClickHouse client with a stub and return its insert mock."""
    client = MagicMock()
    monkeypatch.setattr(stats, "get_clickhouse_client", lambda: client)
    return client.insert


@pytest.fixture
def api():
    """Router-only app: avoids importing main.py (Playwright, Tor)."""
    app = FastAPI()
    app.include_router(stats.router)
    return TestClient(app)


def test_like_dislike_row_is_inserted_with_sorted_columns(api, insert_mock):
    row = {"value": 1, "id": 42, "type": 0, "module": "translator"}
    res = api.post("/stats/", json={"table": LIKE_DISLIKE_TABLE, "data": [row]})

    assert res.status_code == 200
    assert res.json() == {"status": "success"}
    insert_mock.assert_called_once_with(
        LIKE_DISLIKE_TABLE, [[42, "translator", 0, 1]], ["id", "module", "type", "value"]
    )


def test_vocabulary_sr_row_is_inserted_unchanged(api, insert_mock):
    row = {
        "language": 1,
        "translationLanguage": 2,
        "wordId": 3,
        "externalId": 4,
        "interval": 5,
        "repetitions": 6,
        "lastRes": 1,
        "timestampAdded": 100,
        "timestampUpdated": 200,
        "nextStartTS": 300,
        "type": 0,
    }
    res = api.post("/stats/", json={"table": VOCABULARY_SR_TABLE, "data": [row]})

    assert res.status_code == 200
    columns = sorted(row.keys())
    insert_mock.assert_called_once_with(VOCABULARY_SR_TABLE, [[row[c] for c in columns]], columns)


def test_arbitrary_table_and_columns_are_accepted(api, insert_mock):
    rows = [{"chatId": 1, "minutes": 5.5}, {"chatId": 2, "minutes": 3}]
    res = api.post("/stats/", json={"table": "  someOtherTable ", "data": rows})

    assert res.status_code == 200
    insert_mock.assert_called_once_with(
        "someOtherTable", [[1, 5.5], [2, 3]], ["chatId", "minutes"]
    )


@pytest.mark.parametrize(
    "body",
    [
        {"data": [{"id": 1}]},
        {"table": "", "data": [{"id": 1}]},
        {"table": "   ", "data": [{"id": 1}]},
        {"table": "default.LikeDislikeStats", "data": [{"id": 1}]},
        {"table": "x; DROP TABLE y", "data": [{"id": 1}]},
    ],
    ids=["missing", "empty", "blank", "qualified", "injection"],
)
def test_bad_table_name_is_rejected(api, insert_mock, body):
    res = api.post("/stats/", json=body)

    assert res.status_code == 422
    insert_mock.assert_not_called()


def test_bad_column_name_is_rejected(api, insert_mock):
    res = api.post("/stats/", json={"table": LIKE_DISLIKE_TABLE, "data": [{"bad key": 1}]})

    assert res.status_code == 422
    insert_mock.assert_not_called()


def test_empty_data_is_rejected(api, insert_mock):
    res = api.post("/stats/", json={"table": LIKE_DISLIKE_TABLE, "data": []})

    assert res.status_code == 422
    insert_mock.assert_not_called()


def test_insert_failure_returns_500_with_detail(api, insert_mock):
    insert_mock.side_effect = RuntimeError("Unknown column 'foo'")
    res = api.post("/stats/", json={"table": LIKE_DISLIKE_TABLE, "data": [{"foo": 1}]})

    assert res.status_code == 500
    detail = res.json()["detail"]
    assert LIKE_DISLIKE_TABLE in detail
    assert "Unknown column 'foo'" in detail

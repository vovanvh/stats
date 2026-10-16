from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from requests.exceptions import ProxyError
from youtube_transcript_api import IpBlocked, VideoUnavailable

from app.routers import youtube

VIDEO_ID = "FR5pAGqYSnY"
RAW_TRANSCRIPT = [{"text": "hi", "start": 0.0, "duration": 1.0}]


@pytest.fixture
def client_mock(monkeypatch):
    """Replace the proxied YouTube client factory with a stub; return the stub client."""
    client = MagicMock()
    monkeypatch.setattr(youtube, "get_youtube_api_client", lambda is_free=False: client)
    return client


@pytest.fixture
def rotate_mock(monkeypatch):
    """Replace the proxy session rotation with a counting stub."""
    rotate = MagicMock(return_value="new-session")
    monkeypatch.setattr(youtube, "rotate_session", rotate)
    return rotate


@pytest.fixture
def api():
    """Router-only app: avoids importing main.py (Playwright, Tor)."""
    app = FastAPI()
    app.include_router(youtube.router)
    return TestClient(app)


def _transcript():
    """A fetched-transcript stub exposing to_raw_data()."""
    return SimpleNamespace(to_raw_data=lambda: RAW_TRANSCRIPT)


def test_proxy_error_is_retried_on_a_rotated_session(api, client_mock, rotate_mock):
    client_mock.fetch.side_effect = [ProxyError("Tunnel connection failed: 504 Gateway Time-out"), _transcript()]

    res = api.get("/yt", params={"videoId": VIDEO_ID, "language": "en"})

    assert res.status_code == 200
    assert res.json() == {"transcript": RAW_TRANSCRIPT}
    assert client_mock.fetch.call_count == 2
    rotate_mock.assert_called_once()


def test_proxy_error_on_every_attempt_is_503(api, client_mock, rotate_mock):
    client_mock.fetch.side_effect = ProxyError("Tunnel connection failed: 504 Gateway Time-out")

    res = api.get("/yt", params={"videoId": VIDEO_ID, "language": "en"})

    assert res.status_code == 503
    assert f"after {youtube._MAX_YT_ATTEMPTS} attempt(s)" in res.json()["detail"]
    assert client_mock.fetch.call_count == youtube._MAX_YT_ATTEMPTS
    assert rotate_mock.call_count == youtube._MAX_YT_ATTEMPTS - 1


def test_ip_block_is_retried_on_a_rotated_session(api, client_mock, rotate_mock):
    client_mock.fetch.side_effect = [IpBlocked(VIDEO_ID), _transcript()]

    res = api.get("/yt", params={"videoId": VIDEO_ID, "language": "en"})

    assert res.status_code == 200
    rotate_mock.assert_called_once()


def test_ip_block_on_every_attempt_is_429(api, client_mock, rotate_mock):
    client_mock.fetch.side_effect = IpBlocked(VIDEO_ID)

    res = api.get("/yt", params={"videoId": VIDEO_ID, "language": "en"})

    assert res.status_code == 429
    assert client_mock.fetch.call_count == youtube._MAX_YT_ATTEMPTS


def test_non_retryable_error_fails_fast_with_404(api, client_mock, rotate_mock):
    client_mock.fetch.side_effect = VideoUnavailable(VIDEO_ID)

    res = api.get("/yt", params={"videoId": VIDEO_ID, "language": "en"})

    assert res.status_code == 404
    assert client_mock.fetch.call_count == 1
    rotate_mock.assert_not_called()


def test_tor_gets_a_single_attempt_without_rotation(api, client_mock, rotate_mock):
    client_mock.fetch.side_effect = ProxyError("SOCKS connection failed")

    res = api.get("/yt", params={"videoId": VIDEO_ID, "language": "en", "isFree": "true"})

    assert res.status_code == 503
    assert client_mock.fetch.call_count == 1
    rotate_mock.assert_not_called()


def test_list_returns_mapped_tracks_after_a_retry(api, client_mock, rotate_mock):
    track = SimpleNamespace(language="English", language_code="en", is_generated=True, is_translatable=False)
    client_mock.list.side_effect = [ProxyError("Tunnel connection failed"), [track]]

    res = api.get("/yt-list", params={"videoId": VIDEO_ID})

    assert res.status_code == 200
    assert res.json() == {
        "available_transcripts": [
            {"language": "English", "language_code": "en", "is_generated": True, "is_translatable": False}
        ]
    }
    rotate_mock.assert_called_once()

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from requests import HTTPError
from requests.exceptions import ProxyError
from youtube_transcript_api import (
    AgeRestricted,
    CouldNotRetrieveTranscript,
    InvalidVideoId,
    IpBlocked,
    NoTranscriptFound,
    PoTokenRequired,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeDataUnparsable,
    YouTubeRequestFailed,
)

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
    assert res.json()["reason"] == "connection_error"
    assert client_mock.fetch.call_count == youtube._MAX_YT_ATTEMPTS
    assert rotate_mock.call_count == youtube._MAX_YT_ATTEMPTS - 1


def test_ip_block_is_retried_on_a_rotated_session(api, client_mock, rotate_mock):
    client_mock.fetch.side_effect = [IpBlocked(VIDEO_ID), _transcript()]

    res = api.get("/yt", params={"videoId": VIDEO_ID, "language": "en"})

    assert res.status_code == 200
    rotate_mock.assert_called_once()


@pytest.mark.parametrize("error_class", [IpBlocked, RequestBlocked])
def test_ip_block_on_every_attempt_is_429(api, client_mock, rotate_mock, error_class):
    client_mock.fetch.side_effect = error_class(VIDEO_ID)

    res = api.get("/yt", params={"videoId": VIDEO_ID, "language": "en"})

    assert res.status_code == 429
    assert res.json()["reason"] == "request_blocked"
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
    assert res.json()["reason"] == "connection_error"
    assert client_mock.fetch.call_count == 1
    rotate_mock.assert_not_called()


# --- machine-readable error reason (VBM-593) ---

# One endpoint call per route; `/yt-list` errors come from `list`, `/yt` errors from `fetch`
_ENDPOINTS = [
    ("/yt", {"videoId": VIDEO_ID, "language": "en"}, "fetch"),
    ("/yt-list", {"videoId": VIDEO_ID}, "list"),
]

# Each mapped library error with the reason it must answer
_MAPPED_ERRORS = [
    (lambda vid: VideoUnavailable(vid), "video_unavailable"),
    (lambda vid: TranscriptsDisabled(vid), "transcripts_disabled"),
    (lambda vid: NoTranscriptFound(vid, ["en"], "tracks"), "no_transcript"),
    (lambda vid: AgeRestricted(vid), "age_restricted"),
    (lambda vid: InvalidVideoId(vid), "invalid_video_id"),
    (lambda vid: VideoUnplayable(vid, "Private video", []), "video_unplayable"),
]


def _call_failing(api, client_mock, endpoint, error, video_id=VIDEO_ID):
    """Make the endpoint's client call raise `error` and return the HTTP answer."""
    path, params, method = endpoint
    getattr(client_mock, method).side_effect = error
    return api.get(path, params={**params, "videoId": video_id}), getattr(client_mock, method)


@pytest.mark.parametrize("endpoint", _ENDPOINTS, ids=[e[0] for e in _ENDPOINTS])
@pytest.mark.parametrize("make_error,reason", _MAPPED_ERRORS, ids=[r for _, r in _MAPPED_ERRORS])
def test_mapped_library_error_is_404_with_its_reason(api, client_mock, rotate_mock, endpoint, make_error, reason):
    error = make_error(VIDEO_ID)

    res, call = _call_failing(api, client_mock, endpoint, error)

    assert res.status_code == 404
    assert res.json() == {"detail": str(error), "reason": reason}
    assert call.call_count == 1
    rotate_mock.assert_not_called()


@pytest.mark.parametrize("endpoint", _ENDPOINTS, ids=[e[0] for e in _ENDPOINTS])
@pytest.mark.parametrize(
    "error",
    [
        YouTubeDataUnparsable(VIDEO_ID),
        PoTokenRequired(VIDEO_ID),
        YouTubeRequestFailed(VIDEO_ID, HTTPError("403 Client Error: Forbidden")),
        ValueError("unexpected"),
    ],
    ids=["unparsable", "po_token", "request_failed_403", "value_error"],
)
def test_unmapped_error_is_404_other(api, client_mock, rotate_mock, endpoint, error):
    res, call = _call_failing(api, client_mock, endpoint, error)

    assert res.status_code == 404
    assert res.json() == {"detail": str(error), "reason": "other"}
    assert call.call_count == 1


@pytest.mark.parametrize("endpoint", _ENDPOINTS, ids=[e[0] for e in _ENDPOINTS])
def test_block_and_connection_errors_carry_their_reason_on_both_endpoints(api, client_mock, rotate_mock, endpoint):
    res, _ = _call_failing(api, client_mock, endpoint, IpBlocked(VIDEO_ID))
    assert (res.status_code, res.json()["reason"]) == (429, "request_blocked")

    res, _ = _call_failing(api, client_mock, endpoint, ProxyError("Tunnel connection failed"))
    assert (res.status_code, res.json()["reason"]) == (503, "connection_error")


def test_unavailable_video_whose_id_contains_429_is_still_404(api, client_mock, rotate_mock):
    video_id = "ab429Connec"
    error = VideoUnavailable(video_id)

    res, _ = _call_failing(api, client_mock, _ENDPOINTS[1], error, video_id=video_id)

    assert res.status_code == 404
    assert res.json()["reason"] == "video_unavailable"


# --- removed videos answer the definitive reason (VBM-597) ---

# (reason, sub_reasons) of an unplayable video removed for good -> `video_unavailable`
_REMOVED_CAUSES = [
    ("This video has been removed by the uploader", []),
    ("This video has been removed for violating YouTube's Terms of Service", []),
    ("This video is no longer available due to a copyright claim by Some Label", []),
    ("This video is no longer available because the YouTube account associated with this video has been terminated.", []),
    ("Video unavailable", ["This video contains content from Some Label, who has blocked it on copyright grounds"]),
    ("THIS VIDEO HAS BEEN REMOVED BY THE UPLOADER", []),
]

# (reason, sub_reasons) of an unplayable video that may still play later -> `video_unplayable`
_STILL_UNPLAYABLE_CAUSES = [
    ("This video is private", []),
    ("Join this channel to get access to members-only content like this video, and other exclusive perks.", []),
    ("This live event will begin in 2 hours.", []),
    ("Video unavailable", ["The uploader has not made this video available in your country"]),
    ("Video unavailable", ["This video contains content from Some Label, who has blocked it in your country on copyright grounds"]),
    (None, []),
]


@pytest.mark.parametrize("endpoint", _ENDPOINTS, ids=[e[0] for e in _ENDPOINTS])
@pytest.mark.parametrize(
    "cause,sub_reasons,reason",
    [(c, s, "video_unavailable") for c, s in _REMOVED_CAUSES] + [(c, s, "video_unplayable") for c, s in _STILL_UNPLAYABLE_CAUSES],
    ids=[f"removed-{i}" for i in range(len(_REMOVED_CAUSES))] + [f"unplayable-{i}" for i in range(len(_STILL_UNPLAYABLE_CAUSES))],
)
def test_unplayable_cause_decides_the_reason(api, client_mock, rotate_mock, endpoint, cause, sub_reasons, reason):
    error = VideoUnplayable(VIDEO_ID, cause, sub_reasons)

    res, call = _call_failing(api, client_mock, endpoint, error)

    assert res.status_code == 404
    assert res.json() == {"detail": str(error), "reason": reason}
    assert call.call_count == 1
    rotate_mock.assert_not_called()


def test_removed_video_markers_are_lower_case_fragments():
    markers = youtube._REMOVED_VIDEO_CAUSE_MARKERS
    assert markers and len(markers) == len(set(markers))
    assert all(marker and marker == marker.lower() for marker in markers)


def _all_subclasses(cls):
    """Every direct and indirect subclass of `cls`."""
    found = []
    for sub in cls.__subclasses__():
        found.append(sub)
        found.extend(_all_subclasses(sub))
    return found


def test_every_library_error_class_gets_exactly_one_reason():
    mapped = [error_class for error_class, _ in youtube._LIBRARY_ERROR_REASONS]
    assert len(mapped) == len(set(mapped))

    for error_class in _all_subclasses(CouldNotRetrieveTranscript):
        # At most one mapped class matches, so the map order never decides a code
        matches = [m for m in mapped if issubclass(error_class, m)]
        assert len(matches) <= 1, error_class

        # A bare instance of the class still resolves to exactly one known code
        error = error_class.__new__(error_class)
        error.video_id = VIDEO_ID
        reason = youtube._library_reason(error)
        if reason is None:
            assert matches == []
        else:
            assert reason in youtube.YtErrorReason


def test_list_returns_mapped_tracks_after_a_retry(api, client_mock, rotate_mock):
    track = SimpleNamespace(language="English", language_code="en", is_generated=True, is_translatable=False)
    client_mock.list.side_effect = [ProxyError("Tunnel connection failed"), [track]]

    res = api.get("/yt-list", params={"videoId": VIDEO_ID})

    assert res.status_code == 200
    assert res.json() == {
        "available_transcripts": [
            {"language": "English", "language_code": "en", "is_generated": True, "is_translatable": False}
        ],
        # No audio-track metadata on the stub client: the single generated track is the original
        "original_language_code": "en",
    }
    rotate_mock.assert_called_once()


# --- original audio language of auto-dubbed videos (VBM-499) ---

def _audio_format(track_id: str, default: bool = False, dubbed: bool = False) -> dict:
    """One adaptive format carrying an innertube audioTrack, as the player response lists them."""
    audio_track = {"displayName": track_id, "id": track_id, "audioIsDefault": default}
    if dubbed:
        audio_track["isAutoDubbed"] = True
    return {"itag": 140, "audioTrack": audio_track}


def _asr_track(code: str) -> dict:
    return {"language": f"{code} (auto-generated)", "language_code": code, "is_generated": True, "is_translatable": True}


def test_resolver_picks_the_default_non_dubbed_audio_track():
    formats = [
        _audio_format("ar.10", dubbed=True),
        _audio_format("en-US.4", default=True),
        _audio_format("en-US.4", default=True),  # second bitrate of the same track
        _audio_format("de.10", dubbed=True),
    ]
    tracks = [_asr_track("ar"), _asr_track("de"), _asr_track("en")]

    assert youtube.resolve_original_language_code(formats, tracks) == "en"


def test_resolver_falls_back_to_the_single_non_dubbed_track():
    formats = [_audio_format("fr.10", dubbed=True), _audio_format("es-419.2")]
    tracks = [_asr_track("es"), _asr_track("fr")]

    assert youtube.resolve_original_language_code(formats, tracks) == "es"


def test_resolver_without_audio_tracks_uses_the_single_generated_caption_track():
    tracks = [
        {"language": "German", "language_code": "de", "is_generated": False, "is_translatable": True},
        _asr_track("en"),
    ]

    assert youtube.resolve_original_language_code([], tracks) == "en"


def test_resolver_without_audio_tracks_and_two_generated_tracks_is_undetermined():
    assert youtube.resolve_original_language_code([], [_asr_track("en"), _asr_track("de")]) is None


def test_resolver_ignores_a_default_track_that_is_itself_auto_dubbed():
    formats = [_audio_format("ar.10", default=True, dubbed=True), _audio_format("de.10", dubbed=True)]

    assert youtube.resolve_original_language_code(formats, [_asr_track("ar"), _asr_track("de")]) is None


def test_resolver_rejects_an_original_without_a_caption_track():
    formats = [_audio_format("ja.4", default=True), _audio_format("en.10", dubbed=True)]

    assert youtube.resolve_original_language_code(formats, [_asr_track("en")]) is None


def test_list_returns_the_original_language_from_the_fetcher_formats(api, client_mock, rotate_mock):
    client_mock.list.return_value = [
        SimpleNamespace(language="Arabic (auto-generated)", language_code="ar", is_generated=True, is_translatable=True),
        SimpleNamespace(language="English (auto-generated)", language_code="en", is_generated=True, is_translatable=True),
    ]
    client_mock._fetcher.adaptive_formats = [_audio_format("ar.10", dubbed=True), _audio_format("en-US.4", default=True)]

    res = api.get("/yt-list", params={"videoId": VIDEO_ID})

    assert res.status_code == 200
    assert res.json()["original_language_code"] == "en"
    assert [t["language_code"] for t in res.json()["available_transcripts"]] == ["ar", "en"]
    rotate_mock.assert_not_called()


def test_client_factory_installs_the_audio_track_aware_fetcher(monkeypatch):
    monkeypatch.setattr(
        youtube, "get_proxy",
        lambda is_free=False: SimpleNamespace(provider="stub", http_url="http://p:1", https_url="http://p:1"),
    )

    client = youtube.get_youtube_api_client()

    # The pinned library still exposes the hook the subclass overrides
    assert callable(getattr(youtube.TranscriptListFetcher, "_extract_captions_json", None))
    assert isinstance(client._fetcher, youtube._AudioTrackAwareFetcher)
    assert client._fetcher.adaptive_formats == []


def test_fetcher_keeps_the_adaptive_formats_of_the_player_response():
    fetcher = youtube._AudioTrackAwareFetcher(MagicMock(), proxy_config=None)
    innertube = {
        "playabilityStatus": {"status": "OK"},
        "streamingData": {"adaptiveFormats": [_audio_format("en-US.4", default=True)]},
        "captions": {"playerCaptionsTracklistRenderer": {"captionTracks": []}},
    }

    assert fetcher._extract_captions_json(innertube, VIDEO_ID) == {"captionTracks": []}
    assert fetcher.adaptive_formats == [_audio_format("en-US.4", default=True)]

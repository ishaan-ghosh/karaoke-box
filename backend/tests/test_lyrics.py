from __future__ import annotations

import io
import json
import urllib.error

import pytest

from app import lyrics


def test_lrc_parses_fractional_duplicate_and_sorts() -> None:
    parsed = lyrics.parse_lrc("[00:02.5][00:01.25] later\n[00:03.001] end\n[01:70.00] bad")
    assert [(line.start_ms, line.text) for line in parsed] == [(1250, "later"), (2500, "later"), (3001, "end")]


def test_lrc_offset_is_clamped_and_reads_offset_tag() -> None:
    assert lyrics.parse_lrc("[offset:100]\n[00:01.00] hi", offset_ms=-2000)[0].start_ms == 0
    assert lyrics.parse_lrc("[offset:100]\n[00:01.00] hi")[0].start_ms == 1100


def test_lyricsfile_rejects_alias_and_invalid_words_fallbacks_to_line() -> None:
    assert lyrics.parse_lyricsfile("version: '1.0'\na: &x [1]\nlines: *x") == ()
    parsed = lyrics.parse_lyricsfile("""version: '1.0'
lines:
  - text: Hello world
    start_ms: 1000
    end_ms: 3000
    words:
      - text: 'Hello '
        start_ms: 1000
      - text: world
        start_ms: 2000
""")
    assert parsed[0].words[1].text == "world"
    shifted = lyrics.parse_lyricsfile("version: '1.0'\nmetadata:\n  offset_ms: 100\nlines:\n  - text: hi\n    start_ms: 10")
    assert shifted[0].start_ms == 110
    invalid = lyrics.parse_lyricsfile("""version: '1.0'
lines:
  - text: Hello world
    start_ms: 1000
    end_ms: 3000
    words:
      - text: Hello
        start_ms: 500
""")
    assert invalid[0].words == ()
    assert lyrics.parse_lyricsfile("version: '1.0'\nlines:\n  - text: hi\n    start_ms: 2000\n    end_ms: 1000") == ()
    assert lyrics.parse_lyricsfile("version: '1.0'\nmetadata:\n  offset_ms: 120000\nlines:\n  - text: hi\n    start_ms: 86399999\n    end_ms: 86400000\n    words:\n      - text: hi\n        start_ms: 86399999\n        end_ms: 86400000") == ()


def test_lyricsfile_only_records_are_synchronized(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"id": 7, "trackName": "Song", "artistName": "Artist", "duration": 12, "lyricsfile": "version: '1.0'\nlines:\n  - text: hi\n    start_ms: 0"}
    monkeypatch.setattr(lyrics, "_request", lambda *args, **kwargs: [payload] if args[0] == "/api/search" else payload)
    assert [record.record_id for record in lyrics.search_lyrics("Song", "Artist")] == [7]
    assert lyrics.get_lyrics(7).lyricsfile


def test_lrc_offset_is_file_wide_even_when_tag_follows_a_line() -> None:
    parsed = lyrics.parse_lrc("[00:01.00] hi\n[offset:500]")
    assert parsed[0].start_ms == 1500


def test_hostile_yaml_and_non_finite_duration_are_rejected() -> None:
    assert lyrics.parse_lyricsfile("version: '1.0'\nlines:\n  - text: hi\n    start_ms: 1.9") == ()
    assert lyrics.parse_lyricsfile("version: '1.0'\nlines:\n  - text: hi\n    start_ms: .nan") == ()
    assert lyrics._record({"id": 1, "duration": "1e999", "syncedLyrics": "[00:00] hi"}) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"id": True},
        {"id": 1.0},
        {"id": "1"},
        {"duration": True},
        {"duration": "12"},
        {"duration": float("inf")},
        {"instrumental": "false"},
        {"instrumental": 1},
        {"trackName": []},
        {"name": {}},
        {"artistName": 7},
        {"albumName": ["Album"]},
        {"plainLyrics": {"text": "hi"}},
        {"syncedLyrics": 0},
        {"lyricsfile": ["version"]},
    ],
)
def test_provider_record_fields_are_type_strict(changes: dict) -> None:
    value = {"id": 1, "duration": 12.5, "instrumental": False, "syncedLyrics": "[00:00] hi"}
    value.update(changes)
    assert lyrics._record(value) is None


def test_provider_record_accepts_finite_numeric_duration_and_boolean_instrumental() -> None:
    record = lyrics._record({"id": 7, "duration": 12.5, "instrumental": True, "syncedLyrics": "[00:00] hi"})
    assert record is not None and record.record_id == 7 and record.duration_seconds == 12.5 and record.instrumental is True


def test_provider_record_keeps_missing_and_null_text_defaults() -> None:
    record = lyrics._record({"id": 8, "duration": None, "instrumental": False, "trackName": None, "artistName": None, "syncedLyrics": "[00:00] hi"})
    assert record is not None and record.duration_seconds == 0 and record.title == "Unknown track" and record.artist == "Unknown artist"


def test_redirect_handler_rejects_cross_host() -> None:
    handler = lyrics._StrictRedirectHandler()
    with pytest.raises(urllib.error.HTTPError, match="Unsafe LRCLIB redirect"):
        handler.redirect_request(type("Request", (), {"full_url": "https://lrclib.net/api/search"})(), None, 302, "", {}, "https://evil.example/")
    with pytest.raises(urllib.error.HTTPError, match="Unsafe LRCLIB redirect"):
        handler.redirect_request(type("Request", (), {"full_url": "https://lrclib.net/api/search"})(), None, 302, "", {}, "http://lrclib.net/api/search")


def test_request_rejects_deep_and_huge_json(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *args): return None
    monkeypatch.setattr(lyrics.urllib.request, "urlopen", lambda *args, **kwargs: Response(("[" * 1200 + "0" + "]" * 1200).encode()))
    with pytest.raises(lyrics.LyricsError): lyrics._request("/api/search", {})
    monkeypatch.setattr(lyrics.urllib.request, "urlopen", lambda *args, **kwargs: Response(("{" + '"id":' + "9" * 5000 + "}").encode()))
    with pytest.raises(lyrics.LyricsError): lyrics._request("/api/get/1", {})


def test_search_uses_fixed_host_headers_and_filters_unsynced(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *args): return None

    def fake_open(request, timeout):
        seen["url"] = request.full_url
        seen["agent"] = request.headers["User-agent"]
        seen["timeout"] = timeout
        return Response(json.dumps([
            {"id": 1, "trackName": "Song", "artistName": "Artist", "duration": 12, "syncedLyrics": "[00:00.00] hi"},
            {"id": 2, "trackName": "No", "artistName": "Artist", "duration": 12, "plainLyrics": "no"},
        ]).encode())

    monkeypatch.setattr(lyrics.urllib.request, "urlopen", fake_open)
    records = lyrics.search_lyrics("Song", "Artist")
    assert [record.record_id for record in records] == [1]
    assert str(seen["url"]).startswith(lyrics.LRCLIB_BASE_URL + "/api/search?")
    assert seen["agent"] == lyrics.LRCLIB_USER_AGENT
    assert seen["timeout"] == 10

import json
from pathlib import Path

import pytest

from app import youtube


@pytest.mark.parametrize(
    ("value", "expected_id"),
    [
        ("https://www.youtube.com/watch?v=abc123", "abc123"),
        ("https://www.youtube.com/watch?v=abc123&list=RDabc123&start_radio=1", "abc123"),
        ("https://youtu.be/abc123?si=ignored", "abc123"),
        ("https://music.youtube.com/watch?v=abc123", "abc123"),
    ],
)
def test_classify_youtube_url_canonicalizes_individual_videos(value: str, expected_id: str) -> None:
    source = youtube.classify_youtube_url(value)

    assert source.video_id == expected_id
    assert source.canonical_url == "https://www.youtube.com/watch?v=abc123"


@pytest.mark.parametrize(
    "value",
    [
        "http://www.youtube.com/watch?v=abc123",
        "https://www.youtube.com/shorts/abc123",
        "https://www.youtube.com/watch?list=PL123",
        "https://www.youtube.com/playlist?list=PL123",
        "https://example.com/watch?v=abc123",
        "https://www.youtube.com/watch",
    ],
)
def test_classify_youtube_url_rejects_unsupported_sources(value: str) -> None:
    with pytest.raises(youtube.YouTubeUrlError):
        youtube.classify_youtube_url(value)


def test_map_youtube_metadata_rejects_live_streams() -> None:
    source = youtube.classify_youtube_url("https://youtu.be/abc123")

    with pytest.raises(youtube.ProcessingError, match="Live"):
        youtube.map_youtube_metadata({"is_live": True}, source)


def test_map_youtube_metadata_keeps_provenance_and_enforces_preflight() -> None:
    source = youtube.classify_youtube_url("https://youtu.be/abc123")

    metadata = youtube.map_youtube_metadata(
        {
            "title": "  A\n permitted track  ",
            "uploader": "Uploader",
            "uploader_id": "uploader-id",
            "channel": "Channel",
            "channel_id": "channel-id",
            "extractor_key": "Youtube",
            "duration": 42.4,
            "filesize": 1024,
        },
        source,
    )

    assert metadata == {
        "canonical_url": "https://www.youtube.com/watch?v=abc123",
        "video_id": "abc123",
        "title": "A permitted track",
        "uploader": "Uploader",
        "uploader_id": "uploader-id",
        "channel": "Channel",
        "channel_id": "channel-id",
        "extractor": "Youtube",
        "duration_seconds": 42.4,
        "size_bytes": 1024,
    }


def test_ingest_youtube_job_uses_fixed_commands_and_persists_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = youtube.classify_youtube_url("https://youtu.be/abc123")
    run_commands: list[list[str]] = []
    popen_commands: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = json.dumps(
            {
                "title": "Permitted track",
                "id": source.video_id,
                "duration": 12,
                "uploader": "Uploader",
                "extractor_key": "Youtube",
            }
        )
        stderr = ""

    class FakeProcess:
        def __init__(self, command: list[str], **kwargs: object) -> None:
            popen_commands.append(command)
            (tmp_path / "source.m4a").write_bytes(b"downloaded audio")
            self.stdout = iter(["[download] 100.0% of 16.00KiB at 1MiB/s\n"])

        def poll(self) -> int:
            return 0

        def wait(self, **kwargs: object) -> int:
            return 0

    def fake_run(command: list[str], **kwargs: object) -> Result:
        run_commands.append(command)
        return Result()

    monkeypatch.setattr(youtube.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(youtube, "ytdlp_command", lambda: ["python", "-m", "yt_dlp"])
    monkeypatch.setattr(youtube.subprocess, "run", fake_run)
    monkeypatch.setattr(youtube.subprocess, "Popen", FakeProcess)

    updates: list[dict[str, object]] = []
    filename = youtube.ingest_youtube_job(
        tmp_path,
        source.canonical_url,
        lambda **changes: updates.append(changes),
    )

    assert filename == "source.m4a"
    assert (tmp_path / filename).read_bytes() == b"downloaded audio"
    assert run_commands and "--skip-download" in run_commands[0]
    assert popen_commands and "--no-playlist" in popen_commands[0]
    assert "--format" in popen_commands[0]
    assert any(option.startswith("bestaudio") for option in popen_commands[0])
    assert updates[-1]["source_filename"] == "source.m4a"
    assert updates[-1]["fetched_at"]

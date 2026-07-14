import pytest
from fastapi.testclient import TestClient

from app import main
from app.jobs import JobStore

client = TestClient(main.app)


def test_health_describes_required_tools() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert set(response.json()["tools"]) == {"ffmpeg", "ffprobe", "demucs", "yt-dlp"}


def test_upload_requires_rights_confirmation() -> None:
    response = client.post(
        "/api/jobs",
        data={"rights_confirmed": "false", "attestation_version": "1"},
        files={"file": ("track.wav", b"not actually audio", "audio/wav")},
    )

    assert response.status_code == 400
    assert "allowed" in response.json()["detail"]


def test_authorized_upload_creates_a_local_job(monkeypatch, tmp_path) -> None:
    store = JobStore(tmp_path / "jobs")
    submitted: list[str] = []
    monkeypatch.setattr(main, "job_store", store)
    monkeypatch.setattr(main.job_manager, "submit", submitted.append)

    response = client.post(
        "/api/jobs",
        data={"rights_confirmed": "true", "attestation_version": "1"},
        files={"file": ("track.wav", b"small fixture", "audio/wav")},
    )

    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "queued"
    assert job["quality"] == "preserve"
    assert job["separator_engine"] == "demucs"
    assert job["separator_model"] == "htdemucs"
    assert job["original_filename"] == "track.wav"
    assert job["source_type"] == "upload"
    assert job["rights_attestation_version"] == "1"
    assert job["rights_confirmed_at"]
    assert submitted == [job["id"]]
    assert (store.job_dir(job["id"]) / "source.wav").read_bytes() == b"small fixture"


def test_youtube_job_requires_rights_confirmation() -> None:
    response = client.post(
        "/api/jobs/youtube",
        json={
            "url": "https://www.youtube.com/watch?v=abc123",
            "rights_confirmed": False,
            "attestation_version": "1",
        },
    )

    assert response.status_code == 400
    assert "allowed" in response.json()["detail"]


def test_youtube_job_rejects_playlist_urls_and_unknown_hosts() -> None:
    for url in (
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.youtube.com/watch?list=PL123",
        "https://example.com/watch?v=abc123",
    ):
        response = client.post(
            "/api/jobs/youtube",
            json={"url": url, "rights_confirmed": True, "attestation_version": "1"},
        )
        assert response.status_code == 400


def test_authorized_youtube_job_creates_a_queued_job(monkeypatch, tmp_path) -> None:
    store = JobStore(tmp_path / "jobs")
    submitted: list[str] = []
    monkeypatch.setattr(main, "job_store", store)
    monkeypatch.setattr(main.job_manager, "submit", submitted.append)

    response = client.post(
        "/api/jobs/youtube",
        json={
            "url": "https://youtu.be/abc123",
            "rights_confirmed": True,
            "attestation_version": "1",
            "quality": "standard",
        },
    )

    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "queued"
    assert job["source_type"] == "youtube"
    assert job["source_url"] == "https://www.youtube.com/watch?v=abc123"
    assert job["canonical_url"] == job["source_url"]
    assert job["video_id"] == "abc123"
    assert job["quality"] == "standard"
    assert submitted == [job["id"]]


def test_upload_rejects_melband_with_non_preserve_quality() -> None:
    response = client.post(
        "/api/jobs",
        data={
            "rights_confirmed": "true",
            "attestation_version": "1",
            "quality": "best",
            "separator_engine": "melband_roformer",
        },
        files={"file": ("track.wav", b"fixture", "audio/wav")},
    )

    assert response.status_code == 422
    assert "only supports the preserve" in response.json()["detail"]


@pytest.mark.parametrize("quality", ["best", "standard"])
def test_youtube_rejects_melband_with_non_preserve_quality(quality: str) -> None:
    response = client.post(
        "/api/jobs/youtube",
        json={
            "url": "https://www.youtube.com/watch?v=abc123",
            "rights_confirmed": True,
            "attestation_version": "1",
            "quality": quality,
            "separator_engine": "melband_roformer",
        },
    )

    assert response.status_code == 422
    assert "only supports the preserve" in response.json()["detail"]


def test_upload_rejects_an_unknown_quality_profile() -> None:
    response = client.post(
        "/api/jobs",
        data={"rights_confirmed": "true", "attestation_version": "1", "quality": "magic"},
        files={"file": ("track.wav", b"fixture", "audio/wav")},
    )

    assert response.status_code == 422


def test_jobs_can_be_listed_after_a_browser_reload(monkeypatch, tmp_path) -> None:
    store = JobStore(tmp_path / "jobs")
    first = store.create("first.wav", "source.wav", 10)
    second = store.create("second.wav", "source.wav", 20)
    monkeypatch.setattr(main, "job_store", store)

    response = client.get("/api/jobs?limit=10")

    assert response.status_code == 200
    assert {job["id"] for job in response.json()} == {first.id, second.id}

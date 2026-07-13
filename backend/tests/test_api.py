from fastapi.testclient import TestClient

from app import main
from app.jobs import JobStore

client = TestClient(main.app)


def test_health_describes_required_tools() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert set(response.json()["tools"]) == {"ffmpeg", "ffprobe", "demucs"}


def test_upload_requires_rights_confirmation() -> None:
    response = client.post(
        "/api/jobs",
        data={"rights_confirmed": "false"},
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
        data={"rights_confirmed": "true"},
        files={"file": ("track.wav", b"small fixture", "audio/wav")},
    )

    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "queued"
    assert job["quality"] == "preserve"
    assert job["original_filename"] == "track.wav"
    assert submitted == [job["id"]]
    assert (store.job_dir(job["id"]) / "source.wav").read_bytes() == b"small fixture"


def test_upload_rejects_an_unknown_quality_profile() -> None:
    response = client.post(
        "/api/jobs",
        data={"rights_confirmed": "true", "quality": "magic"},
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

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import main
from app.jobs import KaraokeCommitConflict, KaraokeCommitError, JobManager, JobStore
from app.karaoke import KaraokeProject, save_project
from app.lyrics import LyricsRecord

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


def test_karaoke_edit_rejects_server_owned_extra_fields(monkeypatch, tmp_path) -> None:
    store, job_id, project = _completed_karaoke_job(tmp_path)
    monkeypatch.setattr(main, "job_store", store)
    payload = {"lines": [{"text": "hi", "start_ms": 0, "end_ms": 900, "words": []}], "offset_ms": 0, "title": "Song", "subtitle": "Artist", "visual": project.visual.model_dump(), "version": 1}
    response = client.post(f"/api/jobs/{job_id}/karaoke", json=payload)
    assert response.status_code == 422


def test_legacy_jobs_default_to_empty_karaoke_state(tmp_path) -> None:
    store = JobStore(tmp_path / "jobs")
    job = store.create("track.wav", "source.wav", 10)
    assert job.karaoke_status == "empty"
    assert job.karaoke_progress == 0


def _completed_karaoke_job(tmp_path: Path):
    store = JobStore(tmp_path / "jobs")
    job = store.create("track.wav", "source.wav", 10)
    job = store.update(job.id, status="completed", duration_seconds=1.0)
    job_dir = store.job_dir(job.id)
    (job_dir / "instrumental.wav").write_bytes(b"wav")
    (job_dir / "vocals.wav").write_bytes(b"wav")
    project = KaraokeProject(record={"id": 1, "title": "Song", "artist": "Artist"}, fetched_at="now", title="Song", subtitle="Artist", lines=[{"text": "hi", "start_ms": 0, "end_ms": 900}])
    project = save_project(job_dir, project)
    store.update(job.id, karaoke_status="draft", karaoke_project_revision=project.revision)
    return store, job.id, project


def test_karaoke_search_select_save_and_assets(monkeypatch, tmp_path) -> None:
    store, job_id, project = _completed_karaoke_job(tmp_path)
    monkeypatch.setattr(main, "job_store", store)
    record = LyricsRecord(4, "Song", "Artist", "Album", 1, None, "[00:00.00] hi", None)
    result = {"id": 4, "title": "Song", "artist": "Artist", "album": "Album", "duration_seconds": 1, "has_word_timing": False, "instrumental": False}
    calls: list[tuple] = []
    monkeypatch.setattr(main, "search_lyrics", lambda *args: (calls.append(args) or [result]))
    response = client.post(f"/api/jobs/{job_id}/lyrics/search", json={"title": "Song", "artist": "Artist", "album": "Album"})
    assert response.status_code == 200 and response.json()[0]["id"] == 4
    monkeypatch.setattr(main, "select_record", lambda *args, **kwargs: project)
    response = client.post(f"/api/jobs/{job_id}/lyrics/select", json={"record_id": 4})
    assert response.status_code == 200 and response.json()["project"]["record"]["id"] == 1
    assert client.post(f"/api/jobs/{job_id}/lyrics/search", json={"title": " ", "artist": "Artist"}).status_code == 422
    assert len(calls) == 1
    payload = {"lines": [{"text": "bye", "start_ms": 0, "end_ms": 900}], "offset_ms": 0, "title": "Song", "subtitle": "Artist", "visual": project.visual.model_dump()}
    response = client.post(f"/api/jobs/{job_id}/karaoke", json={**payload, "unexpected": True})
    assert response.status_code == 422
    store.update(job_id, karaoke_progress=99, karaoke_message="old render", karaoke_error="old error")
    response = client.post(f"/api/jobs/{job_id}/karaoke", json=payload)
    assert response.status_code == 200
    assert response.json()["state"]["progress"] == 0 and response.json()["state"]["message"] == "Karaoke draft ready"
    (store.job_dir(job_id) / "karaoke.mp4").write_bytes(b"mp4")
    response = client.get(f"/api/jobs/{job_id}/assets/karaoke")
    assert response.status_code == 200 and response.content == b"mp4"


def test_background_is_canonicalized_and_increments_revision(monkeypatch, tmp_path) -> None:
    store, job_id, project = _completed_karaoke_job(tmp_path)
    monkeypatch.setattr(main, "job_store", store)
    source = io.BytesIO()
    Image.new("RGB", (320, 180), "red").save(source, format="JPEG")
    response = client.post(f"/api/jobs/{job_id}/karaoke/background", files={"file": ("cover.jpg", source.getvalue(), "image/jpeg")})
    assert response.status_code == 200
    saved = store.get(job_id)
    assert saved and saved.karaoke_project_revision and saved.karaoke_project_revision > project.revision
    assert response.json()["project"]["visual"]["background"] == "custom"
    assert (store.job_dir(job_id) / "karaoke-background.png").is_file()
    assert not list(store.job_dir(job_id).glob(".karaoke-background-*"))


def test_background_commit_rolls_back_after_replace_failure(monkeypatch, tmp_path) -> None:
    store, job_id, project = _completed_karaoke_job(tmp_path)
    job_dir = store.job_dir(job_id)
    old_background = job_dir / "karaoke-background.png"
    old_background.write_bytes(b"old-image")
    project_path = job_dir / "karaoke-project.json"
    metadata_path = job_dir / "job.json"
    old_project_bytes = project_path.read_bytes()
    old_metadata_bytes = metadata_path.read_bytes()
    staged = job_dir / ".karaoke-background-staged.png"
    staged.write_bytes(b"new-image")
    candidate = project.model_copy(update={"title": "New title"})
    monkeypatch.setattr(store, "_write", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk")))

    with pytest.raises(KaraokeCommitError):
        store.commit_karaoke_revision(job_id, candidate, background_temp=staged)

    assert old_background.read_bytes() == b"old-image"
    assert project_path.read_bytes() == old_project_bytes
    assert metadata_path.read_bytes() == old_metadata_bytes
    assert not staged.exists()
    assert not list(job_dir.glob(".karaoke-background-*"))
    assert not list(job_dir.glob("*.tmp"))


def test_stale_karaoke_revision_rejects_background_without_mutation(tmp_path) -> None:
    store, job_id, project = _completed_karaoke_job(tmp_path)
    job_dir = store.job_dir(job_id)
    old_background = job_dir / "karaoke-background.png"
    old_background.write_bytes(b"current-image")
    current, _ = store.commit_karaoke_revision(job_id, project.model_copy(update={"title": "Current title"}))
    project_path = job_dir / "karaoke-project.json"
    metadata_path = job_dir / "job.json"
    current_project_bytes = project_path.read_bytes()
    current_metadata_bytes = metadata_path.read_bytes()
    staged = job_dir / ".karaoke-background-staged.png"
    staged.write_bytes(b"stale-image")

    with pytest.raises(KaraokeCommitConflict):
        store.commit_karaoke_revision(job_id, project.model_copy(update={"title": "Stale title"}), background_temp=staged)

    assert project_path.read_bytes() == current_project_bytes
    assert metadata_path.read_bytes() == current_metadata_bytes
    assert old_background.read_bytes() == b"current-image"
    assert staged.read_bytes() == b"stale-image"
    assert current.title == "Current title"
    staged.unlink()


def test_background_validation_always_cleans_staging_files(monkeypatch, tmp_path) -> None:
    store, job_id, _ = _completed_karaoke_job(tmp_path)
    monkeypatch.setattr(main, "job_store", store)
    job_dir = store.job_dir(job_id)
    oversized = b"x" * (10 * 1024 * 1024 + 1)
    response = client.post(f"/api/jobs/{job_id}/karaoke/background", files={"file": ("large.png", oversized, "image/png")})
    assert response.status_code == 413
    assert not list(job_dir.glob(".karaoke-background-*"))

    response = client.post(f"/api/jobs/{job_id}/karaoke/background", files={"file": ("invalid.png", b"not an image", "image/png")})
    assert response.status_code == 415
    assert not list(job_dir.glob(".karaoke-background-*"))


def test_job_manager_render_success_and_failure_states(monkeypatch, tmp_path) -> None:
    store, job_id, project = _completed_karaoke_job(tmp_path)
    store.update(job_id, karaoke_status="queued")
    manager = JobManager(store)
    monkeypatch.setattr("app.karaoke.render_job", lambda *args: None)
    manager._run_render(job_id)
    completed = store.get(job_id)
    assert completed and completed.karaoke_status == "completed" and completed.karaoke_rendered_revision == project.revision
    store.update(job_id, karaoke_status="queued")
    monkeypatch.setattr("app.karaoke.render_job", lambda *args: (_ for _ in ()).throw(OSError("/Users/test/Karaoke Box/file")))
    manager._run_render(job_id)
    failed = store.get(job_id)
    assert failed and failed.karaoke_status == "failed" and failed.karaoke_error == "Karaoke render failed. See karaoke-render.log for local diagnostics."
    manager.shutdown()


@pytest.mark.parametrize("message", [
    "ffprobe is required to render a karaoke video.",
    "ffprobe timed out while reading instrumental duration.",
    "FFmpeg encoder probe timed out.",
    "This FFmpeg build does not include the required libx264 encoder.",
    "Choose and upload a custom background image before rendering.",
    "Instrumental duration is outside the supported range.",
    "Not enough free disk space for a karaoke render.",
    "This karaoke project has too many render states.",
    "FFmpeg could not render the karaoke video. See karaoke-render.log.",
])
def test_render_error_exposes_only_fixed_safe_messages(message: str, tmp_path) -> None:
    manager = JobManager(JobStore(tmp_path / "jobs"))
    assert manager._render_error(RuntimeError(message)) == message
    assert manager._render_error(OSError("/Users/test/Karaoke Box/private path")) == "Karaoke render failed. See karaoke-render.log for local diagnostics."
    manager.shutdown()


def test_karaoke_commit_rechecks_active_state_and_delete_remains_blocked(tmp_path) -> None:
    store, job_id, project = _completed_karaoke_job(tmp_path)
    queued = store.queue_karaoke_render(job_id)
    assert queued and queued.karaoke_status == "queued"
    with pytest.raises(RuntimeError, match="active"):
        store.commit_karaoke_revision(job_id, project)
    with pytest.raises(RuntimeError, match="active"):
        store.delete(job_id)


def test_submit_render_failure_rolls_back_queue(monkeypatch, tmp_path) -> None:
    store, job_id, _ = _completed_karaoke_job(tmp_path)
    monkeypatch.setattr(main, "job_store", store)
    monkeypatch.setattr(main.job_manager, "submit_render", lambda *_: (_ for _ in ()).throw(RuntimeError("executor")))
    response = client.post(f"/api/jobs/{job_id}/karaoke/render")
    assert response.status_code == 503
    current = store.get(job_id)
    assert current and current.karaoke_status == "draft" and current.karaoke_progress == 0


def test_render_queue_is_duplicate_safe_and_preserves_prior_asset(monkeypatch, tmp_path) -> None:
    store, job_id, project = _completed_karaoke_job(tmp_path)
    monkeypatch.setattr(main, "job_store", store)
    submitted: list[str] = []
    monkeypatch.setattr(main.job_manager, "submit_render", submitted.append)
    first = client.post(f"/api/jobs/{job_id}/karaoke/render")
    second = client.post(f"/api/jobs/{job_id}/karaoke/render")
    assert first.status_code == 202 and second.status_code == 409
    assert submitted == [job_id]
    assert store.get(job_id).karaoke_status == "queued"


def test_jobs_can_be_listed_after_a_browser_reload(monkeypatch, tmp_path) -> None:
    store = JobStore(tmp_path / "jobs")
    first = store.create("first.wav", "source.wav", 10)
    second = store.create("second.wav", "source.wav", 20)
    monkeypatch.setattr(main, "job_store", store)

    response = client.get("/api/jobs?limit=10")

    assert response.status_code == 200
    assert {job["id"] for job in response.json()} == {first.id, second.id}

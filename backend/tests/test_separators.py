import json
from pathlib import Path

import pytest

from app.jobs import ACTIVE_STATUSES, Job, JobStore
from app.separators import demucs
from app.separators.base import ProcessingError
from app.separators.catalog import MELBAND_ROFORMER_MODEL, resolve_selection


def _legacy_job_payload(quality: str = "standard") -> dict[str, object]:
    return {
        "id": "legacy-job",
        "original_filename": "track.wav",
        "source_filename": "source.wav",
        "size_bytes": 10,
        "quality": quality,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }


def test_legacy_job_json_derives_demucs_selection() -> None:
    job = Job.model_validate(_legacy_job_payload())

    assert job.separator_engine == "demucs"
    assert job.separator_model == "htdemucs"
    assert job.quality == "standard"


def test_new_jobs_persist_exact_engine_and_model(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    job = store.create(
        "track.wav",
        "source.wav",
        10,
        quality="preserve",
        separator_engine="melband_roformer",
    )

    persisted = json.loads((store.job_dir(job.id) / "job.json").read_text())
    assert persisted["separator_engine"] == "melband_roformer"
    assert persisted["separator_model"] == MELBAND_ROFORMER_MODEL


def test_melband_only_supports_preserve() -> None:
    with pytest.raises(ValueError, match="only supports the preserve"):
        resolve_selection("melband_roformer", "best")


def test_preparing_jobs_are_active() -> None:
    assert "preparing" in ACTIVE_STATUSES


def test_demucs_prepare_rejects_missing_module_before_popen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        demucs.importlib.util,
        "find_spec",
        lambda name: None if name == "demucs" else object(),
    )
    popen_called = False

    def unexpected_popen(*args: object, **kwargs: object) -> None:
        nonlocal popen_called
        popen_called = True

    monkeypatch.setattr(demucs.subprocess, "Popen", unexpected_popen)

    with pytest.raises(ProcessingError, match="Missing required tool: demucs"):
        demucs.DemucsAdapter().prepare(
            job_dir=tmp_path,
            source=tmp_path / "source.wav",
            update=lambda **changes: None,
            quality="preserve",
            model="htdemucs",
        )

    assert not popen_called

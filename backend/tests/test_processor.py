from pathlib import Path

import pytest

from app import processor


def test_probe_audio_rejects_a_file_without_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    class Result:
        returncode = 0
        stdout = '{"format":{"duration":"3.5"},"streams":[{"codec_type":"video"}]}'
        stderr = ""

    monkeypatch.setattr(processor.subprocess, "run", lambda *args, **kwargs: Result())

    with pytest.raises(processor.ProcessingError, match="audio stream"):
        processor.probe_audio(Path("fixture.mp4"))


def test_probe_audio_returns_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    class Result:
        returncode = 0
        stdout = '{"format":{"duration":"12.3456"},"streams":[{"codec_type":"audio"}]}'
        stderr = ""

    monkeypatch.setattr(processor.subprocess, "run", lambda *args, **kwargs: Result())

    assert processor.probe_audio(Path("fixture.wav"))["duration_seconds"] == 12.346


def test_progress_tracker_combines_multiple_model_passes() -> None:
    tracker = processor.DemucsProgressTracker(expected_passes=1)
    assert tracker.feed("Selected model is a bag of 4 models.") is None

    first_done = tracker.feed(
        "100%|########| 10.0/10.0 [00:02<00:00, 5.0seconds/s]"
    )
    second_start = tracker.feed(
        "  0%|        | 0.0/10.0 [00:00<?, ?seconds/s]"
    )
    second_half = tracker.feed(
        " 50%|####    | 5.0/10.0 [00:01<00:01, 5.0seconds/s]"
    )

    assert first_done is not None and first_done.fraction == 0.25
    assert second_start is not None and second_start.current_pass == 2
    assert second_half is not None and second_half.fraction == 0.375


@pytest.mark.parametrize(
    ("quality", "expected_model", "expected_method", "expected_stem"),
    [
        ("preserve", "htdemucs", "minus", "minus_vocals"),
        ("best", "htdemucs_ft", "minus", "minus_vocals"),
        ("standard", "htdemucs", "add", "no_vocals"),
    ],
)
def test_process_job_uses_the_selected_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    quality: str,
    expected_model: str,
    expected_method: str,
    expected_stem: str,
) -> None:
    (tmp_path / "source.wav").write_bytes(b"fixture")
    command_used: list[str] = []

    class FakeProcess:
        def __init__(self, command):
            command_used.extend(command)
            output = tmp_path / "demucs-output" / expected_model / "source"
            output.mkdir(parents=True)
            (output / f"{expected_stem}.wav").write_bytes(b"instrumental")
            (output / "vocals.wav").write_bytes(b"vocals")
            self.stdout = iter(
                [
                    "Selected model is a bag of 1 models.\n",
                    "  0%|        | 0.0/10.0 [00:00<?, ?seconds/s]\n",
                    " 50%|####    | 5.0/10.0 [00:01<00:01, 5.0seconds/s]\n",
                    "100%|########| 10.0/10.0 [00:02<00:00, 5.0seconds/s]\n",
                ]
            )

        def wait(self):
            return 0

    def fake_popen(command, **kwargs):
        return FakeProcess(command)

    monkeypatch.setattr(processor, "ensure_tools", lambda: None)
    monkeypatch.setattr(
        processor,
        "probe_audio",
        lambda source: {"duration_seconds": 3.0, "metadata": {}},
    )
    monkeypatch.setattr(processor.subprocess, "Popen", fake_popen)

    updates: list[dict] = []
    processor.process_job(
        tmp_path,
        "source.wav",
        lambda **changes: updates.append(changes),
        quality=quality,
    )

    assert command_used[command_used.index("--device") + 1] == "cpu"
    assert command_used[command_used.index("--name") + 1] == expected_model
    assert command_used[command_used.index("--other-method") + 1] == expected_method
    assert (tmp_path / "instrumental.wav").read_bytes() == b"instrumental"
    assert (tmp_path / "vocals.wav").read_bytes() == b"vocals"

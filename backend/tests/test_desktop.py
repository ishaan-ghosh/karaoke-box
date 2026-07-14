from __future__ import annotations

from pathlib import Path

import pytest

from app import desktop


def test_internal_separator_dispatch_preserves_private_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[list[str]] = []
    monkeypatch.setattr(
        desktop,
        "_run_internal_separator",
        lambda arguments: received.append(arguments) or 7,
    )

    assert desktop.main(["--internal-separator", "--probe"]) == 7
    assert received == [["--probe"]]


def test_desktop_environment_sets_model_root_and_preserves_cpu_caches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import platformdirs

    data_root = tmp_path / "Karaoke Box"
    monkeypatch.setattr(platformdirs, "user_data_path", lambda *args, **kwargs: data_root)
    for name in (
        "KARAOKE_DATA_DIR",
        "KARAOKE_MODEL_DIR",
        "KARAOKE_DESKTOP_LOG",
        "TORCH_HOME",
        "HF_HOME",
        "KARAOKE_SESSION_TOKEN",
        "KARAOKE_CORS_ORIGINS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "some-device")

    assert desktop._configure_desktop_environment() == data_root
    model_root = data_root / "models"
    assert desktop.os.environ["KARAOKE_DATA_DIR"] == str(data_root)
    assert desktop.os.environ["KARAOKE_MODEL_DIR"] == str(model_root)
    assert desktop.os.environ["TORCH_HOME"] == str(model_root / "torch")
    assert desktop.os.environ["HF_HOME"] == str(model_root / "huggingface")
    assert desktop.os.environ["CUDA_VISIBLE_DEVICES"] == ""
    assert model_root.is_dir()


def test_separator_probe_uses_private_worker_command_without_model_arguments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr(
        desktop,
        "subprocess",
        type(
            "Subprocess",
            (),
            {
                "run": staticmethod(
                    lambda command, **kwargs: calls.append((command, kwargs))
                    or type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
                )
            },
        ),
    )
    monkeypatch.setattr(
        "app.runtime.separator_worker_command",
        lambda: ["python", "-u", "-m", "app.separators.worker"],
    )
    monkeypatch.setattr("app.runtime.separator_worker_cwd", lambda: tmp_path)

    desktop._run_separator_probe()

    assert calls == [
        (
            ["python", "-u", "-m", "app.separators.worker", "--probe"],
            {"capture_output": True, "text": True, "check": False, "cwd": tmp_path},
        )
    ]


def test_separator_probe_launches_real_worker_from_repository_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(repository_root)
    # Ensure this child test proves cwd handling rather than inheriting an
    # import path that happens to make ``app`` visible.
    monkeypatch.delenv("PYTHONPATH", raising=False)

    desktop._run_separator_probe()

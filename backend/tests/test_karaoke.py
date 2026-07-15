from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.karaoke import KaraokeProject, LineModel, VisualModel, load_project, save_project
from app import karaoke_renderer
from app.karaoke_renderer import SUPPORTED_SYMBOL_GLYPHS, _background, _cue_events, _font, _font_for_text, _font_runs, _safe_log
from app.lyrics import LyricsRecord, LyricLine, LyricWord, line_intervals, word_intervals


def project() -> KaraokeProject:
    return KaraokeProject(
        record={"id": 3, "title": "Song", "artist": "Artist", "album": "Album", "duration_seconds": 5, "has_word_timing": True},
        fetched_at="now",
        lines=[LineModel(text="One two", start_ms=1000, end_ms=3000, words=[{"text": "One ", "start_ms": 1000, "end_ms": 1800}, {"text": "two", "start_ms": 1800, "end_ms": 3000}])],
        visual=VisualModel(),
    )


def test_project_save_is_atomic_and_increments_revision(tmp_path: Path) -> None:
    saved = save_project(tmp_path, project())
    assert saved.revision == 2
    assert load_project(tmp_path) == saved
    assert not (tmp_path / "karaoke-project.tmp").exists()


def test_cues_include_line_and_word_boundaries_with_offset() -> None:
    value = project().model_copy(update={"offset_ms": 100})
    cues = _cue_events(value, 5)
    assert (1100, 3100, 0) in cues
    assert (1100, 1900, 0) in cues


def test_renderer_selected_faces_have_real_basic_latin_glyphs() -> None:
    characters = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    for family in ("sans", "display", "mono"):
        font = _font(24, False, family)
        missing = font.getmask("\U0010FFFF")
        notdef = (missing.size, missing.getbbox(), bytes(missing))
        for character in characters:
            mask = font.getmask(character)
            assert mask.getbbox(), (family, character)
            assert (mask.size, mask.getbbox(), bytes(mask)) != notdef, (family, character)


def test_renderer_supported_symbols_have_real_glyphs() -> None:
    font = _font_for_text("★", 24, False, "display")
    missing = font.getmask("\U0010FFFF")
    notdef = (missing.size, missing.getbbox(), bytes(missing))
    for character in SUPPORTED_SYMBOL_GLYPHS:
        mask = font.getmask(character)
        assert mask.getbbox(), character
        assert (mask.size, mask.getbbox(), bytes(mask)) != notdef, character


def test_renderer_selects_bundled_non_latin_fallback() -> None:
    for family in ("sans", "display", "mono"):
        symbol_font = _font_for_text("★", 20, False, family)
        assert symbol_font.getname()[0] == "Noto Sans Symbols2" and symbol_font.getmask("★").getbbox()
        assert _font_for_text("We’re", 20, False, family).getname()[0] == "Noto Sans"
        assert _font_for_text("→", 20, False, family).getname()[0] == "Noto Sans"
        runs = _font_runs("We’re ready ★", 20, False, family)
        assert [run for run, _ in runs] == ["We", "’", "re ready ", "★"]
        assert runs[0][1].getname()[0] == _font(20, False, family).getname()[0]
        assert runs[1][1].getname()[0] == "Noto Sans"
        assert runs[-1][1].getname()[0] == "Noto Sans Symbols2"


def test_custom_background_is_not_silently_replaced_by_gradient(tmp_path: Path) -> None:
    value = project().model_copy(update={"visual": VisualModel(background="custom")})
    with pytest.raises(RuntimeError, match="upload a custom background"):
        _background(value, tmp_path / "missing.png")


def test_render_log_redacts_space_containing_paths(tmp_path: Path) -> None:
    from io import StringIO
    log = StringIO()
    _safe_log(log, 'open /Users/test/Karaoke Box/jobs/one/file.wav: [Errno 2] missing\n')
    assert "Karaoke Box" not in log.getvalue()
    assert "<local-path>" in log.getvalue()


def test_missing_word_end_uses_next_word_start() -> None:
    line = LyricLine("a b", 0, 1000, (LyricWord("a ", 0), LyricWord("b", 500)))
    assert word_intervals(line, 1000, 1000) == ((0, 500, 0), (500, 1000, 1))


def test_terminal_implicit_intervals_apply_offset_once() -> None:
    line = LyricLine("a b", 1000, None, (LyricWord("a ", 1000), LyricWord("b", 1800)))
    assert line_intervals([line], 5000, 500) == ((1500, 5000, 0),)
    assert word_intervals(line, 5000, 5000, 500)[-1] == (2300, 5000, 1)
    assert line_intervals([line], 5000, -500) == ((500, 5000, 0),)
    assert word_intervals(line, 5000, 5000, -500)[-1] == (1300, 5000, 1)


def test_line_intervals_preserve_gaps_and_clip_duration() -> None:
    lines = [LyricLine("a", 100, 200), LyricLine("b", 500, None)]
    assert line_intervals(lines, 600) == ((100, 200, 0), (500, 600, 1))


def test_project_rejects_unsupported_version() -> None:
    with pytest.raises(ValueError):
        KaraokeProject(version=2, record={}, fetched_at="now", lines=[{"text": "x", "start_ms": 0}])


def test_renderer_uses_relative_manifest_and_preserves_prior_output(monkeypatch, tmp_path: Path) -> None:
    job = tmp_path
    (job / "instrumental.wav").write_bytes(b"wav")
    project_value = project()
    (job / "karaoke.mp4").write_bytes(b"prior")
    captured: dict[str, object] = {}
    progress: list[dict] = []

    class FakeProcess:
        stdout = ["out_time_ms=500000\n", "progress=end\n"]

        def __init__(self, command, cwd, **kwargs):
            captured["command"] = command
            captured["cwd"] = cwd
            captured["manifest"] = (Path(cwd) / "overlays.txt").read_text()
            Path(cwd, command[-1]).write_bytes(b"new")

        def wait(self):
            return 0

    monkeypatch.setattr(karaoke_renderer, "resolve_tool", lambda name: name)
    monkeypatch.setattr(karaoke_renderer, "_probe_duration", lambda path: 1.0)
    monkeypatch.setattr(karaoke_renderer.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="libx264"))
    monkeypatch.setattr(karaoke_renderer.subprocess, "Popen", FakeProcess)
    karaoke_renderer.render_video(job, project_value, lambda **changes: progress.append(changes))
    command = captured["command"]
    assert "-safe" in command and command[command.index("-safe") + 1] == "1"
    assert all(line.startswith("file 'overlay-") for line in str(captured["manifest"]).splitlines() if line.startswith("file"))
    assert progress and progress[-1]["progress"] == 100
    assert (job / "karaoke.mp4").read_bytes() == b"new"


def test_renderer_encoder_probe_timeout_is_actionable(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "instrumental.wav").write_bytes(b"wav")
    monkeypatch.setattr(karaoke_renderer, "resolve_tool", lambda name: name)
    monkeypatch.setattr(karaoke_renderer.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(karaoke_renderer.subprocess.TimeoutExpired("ffmpeg", 15)))
    with pytest.raises(RuntimeError, match="encoder probe timed out"):
        karaoke_renderer.render_video(tmp_path, project(), lambda **_: None)


def test_renderer_waits_for_child_when_progress_callback_fails(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "instrumental.wav").write_bytes(b"wav")
    events: list[str] = []
    class CallbackFailureProcess:
        stdout = ["out_time_ms=500000\n"]
        def __init__(self, *args, **kwargs): pass
        def terminate(self): events.append("terminate")
        def wait(self, *args, **kwargs): events.append("wait"); return 1
    monkeypatch.setattr(karaoke_renderer, "resolve_tool", lambda name: name)
    monkeypatch.setattr(karaoke_renderer, "_probe_duration", lambda path: 1.0)
    monkeypatch.setattr(karaoke_renderer.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="libx264"))
    monkeypatch.setattr(karaoke_renderer.subprocess, "Popen", CallbackFailureProcess)
    def fail(**_): raise OSError("disk full")
    with pytest.raises(OSError):
        karaoke_renderer.render_video(tmp_path, project(), fail)
    assert events[:2] == ["terminate", "wait"]


def test_renderer_failure_keeps_prior_output(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "instrumental.wav").write_bytes(b"wav")
    (tmp_path / "karaoke.mp4").write_bytes(b"prior")
    class Failed:
        stdout = ["fatal\n"]
        def __init__(self, *args, **kwargs): pass
        def wait(self): return 1
    monkeypatch.setattr(karaoke_renderer, "resolve_tool", lambda name: name)
    monkeypatch.setattr(karaoke_renderer, "_probe_duration", lambda path: 1.0)
    monkeypatch.setattr(karaoke_renderer.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="libx264"))
    monkeypatch.setattr(karaoke_renderer.subprocess, "Popen", Failed)
    with pytest.raises(RuntimeError):
        karaoke_renderer.render_video(tmp_path, project(), lambda **_: None)
    assert (tmp_path / "karaoke.mp4").read_bytes() == b"prior"


def test_project_rejects_unordered_lines() -> None:
    with pytest.raises(ValueError):
        KaraokeProject(
            record={}, fetched_at="now",
            lines=[{"text": "two", "start_ms": 2}, {"text": "one", "start_ms": 1}],
        )

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .karaoke import KARAOKE_MAX_EVENTS, KaraokeProject
from .lyrics import line_intervals, word_intervals
from .runtime import resource_root, resolve_tool

WIDTH, HEIGHT, FPS = 1920, 1080, 30
MAX_RENDER_LOG_BYTES = 256 * 1024
SUPPORTED_SYMBOL_GLYPHS = frozenset({"★", "☆", "✓", "▶"})
FONT_FILES = {
    "sans": ("Archivo-Variable.woff2", "Archivo-Variable.woff2"),
    "display": ("Doto-Variable.woff2", "Doto-Variable.woff2"),
    "mono": ("SplineSansMono-Variable.woff2", "SplineSansMono-Variable.woff2"),
}


def _assets_dir() -> Path:
    root = resource_root()
    return (root / "app" if (root / "app").is_dir() else root / "backend" / "app") / "karaoke_assets" / "fonts"


def _font(size: int, bold: bool = False, family: str = "sans"):
    name = FONT_FILES.get(family, FONT_FILES["sans"])[1 if bold else 0]
    path = _assets_dir() / name
    if not path.is_file():
        path = _assets_dir() / ("NotoSans-Bold.ttf" if bold else "NotoSans-Regular.ttf")
    if not path.is_file():
        raise RuntimeError("Bundled karaoke font assets are missing.")
    font = ImageFont.truetype(str(path), size)
    if hasattr(font, "set_variation_by_name"):
        try:
            font.set_variation_by_name("Bold" if bold else "Regular")
        except (AttributeError, OSError, ValueError):
            pass
    return font


def _font_for_text(text: str, size: int, bold: bool, family: str):
    """Return the bundled face appropriate for a homogeneous text run."""
    if any(char in SUPPORTED_SYMBOL_GLYPHS for char in text):
        path = _assets_dir() / "NotoSansSymbols2-Regular.ttf"
    elif any(not char.isascii() for char in text):
        path = _assets_dir() / ("NotoSans-Bold.ttf" if bold else "NotoSans-Regular.ttf")
    else:
        return _font(size, bold, family)
    if not path.is_file():
        return _font(size, bold, family)
    return ImageFont.truetype(str(path), size)


def _font_runs(text: str, size: int, bold: bool, family: str) -> list[tuple[str, ImageFont.FreeTypeFont]]:
    runs: list[tuple[str, ImageFont.FreeTypeFont]] = []
    current_key: str | None = None
    current: list[str] = []
    for char in text:
        key = "symbol" if char in SUPPORTED_SYMBOL_GLYPHS else "fallback" if not char.isascii() else "primary"
        if key != current_key and current:
            runs.append(("".join(current), _font_for_text("".join(current), size, bold, family)))
            current = []
        current_key = key
        current.append(char)
    if current:
        runs.append(("".join(current), _font_for_text("".join(current), size, bold, family)))
    return runs


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _background(project: KaraokeProject, custom: Path | None) -> Image.Image:
    if project.visual.background == "custom" and (custom is None or not custom.is_file()):
        raise RuntimeError("Choose and upload a custom background image before rendering.")
    if project.visual.background == "custom" and custom and custom.is_file():
        with Image.open(custom) as source:
            image = source.convert("RGB")
        scale = max(WIDTH / image.width, HEIGHT / image.height)
        image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
        left, top = (image.width - WIDTH) // 2, (image.height - HEIGHT) // 2
        image = image.crop((left, top, left + WIDTH, top + HEIGHT))
    elif project.visual.background == "solid":
        image = Image.new("RGB", (WIDTH, HEIGHT), _rgb(project.visual.solid_color))
    else:
        start, end = _rgb(project.visual.gradient_start), _rgb(project.visual.gradient_end)
        image = Image.new("RGB", (WIDTH, HEIGHT))
        pixels = image.load()
        for y in range(HEIGHT):
            ratio = y / max(1, HEIGHT - 1)
            color = tuple(round(start[i] * (1 - ratio) + end[i] * ratio) for i in range(3))
            for x in range(WIDTH):
                pixels[x, y] = color
    return Image.alpha_composite(image.convert("RGBA"), Image.new("RGBA", (WIDTH, HEIGHT), (8, 6, 10, 110))).convert("RGB")


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split() or [""]:
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current or not lines:
        lines.append(current)
    return lines


def _draw_centered(draw: ImageDraw.ImageDraw, text: str, y: int, font, fill: tuple[int, int, int], max_width: int = WIDTH - 320, family: str | None = None, bold: bool = False) -> None:
    family = family or "sans"
    measure_font = _font(font.size, bold, family)
    lines = _wrap(draw, text, measure_font, max_width)
    height = max(40, font.getbbox("Ag")[3] - font.getbbox("Ag")[1] + 12)
    top = y - ((len(lines) - 1) * height) // 2
    for index, line in enumerate(lines):
        line_runs = _font_runs(line, font.size, bold, family)
        total = sum(draw.textlength(part, font=part_font) for part, part_font in line_runs)
        cursor = WIDTH / 2 - total / 2
        for part, part_font in line_runs:
            draw.text((cursor, top + index * height), part, font=part_font, fill=fill, anchor="lm", stroke_width=3, stroke_fill=(0, 0, 0, 210))
            cursor += draw.textlength(part, font=part_font)


def _draw_word_line(draw: ImageDraw.ImageDraw, words, y: int, font, inactive, highlight, family: str = "sans") -> None:
    rows: list[list[tuple[str, tuple[int, int, int], ImageFont.FreeTypeFont]]]=[[]]
    fonts = [_font_for_text(word.text, font.size, True, family) for word in words[0]]
    widths = [draw.textlength(word.text, font=word_font) for word, word_font in zip(words[0], fonts)]
    current_width = 0
    for index, word in enumerate(words[0]):
        width = widths[index]
        if rows[-1] and current_width + width > WIDTH - 320:
            rows.append([])
            current_width = 0
        rows[-1].append((word.text, highlight if index == words[1] else inactive, fonts[index]))
        current_width += width
    height = max(40, font.getbbox("Ag")[3] - font.getbbox("Ag")[1] + 12)
    top = y - ((len(rows) - 1) * height) // 2
    for row_index, row in enumerate(rows):
        total = sum(draw.textlength(text, font=word_font) for text, _, word_font in row)
        cursor = WIDTH / 2 - total / 2
        for text, color, _word_font in row:
            for part, part_font in _font_runs(text, font.size, True, family):
                draw.text((cursor, top + row_index * height), part, font=part_font, fill=color, anchor="lm", stroke_width=3, stroke_fill=(0, 0, 0, 220))
                cursor += draw.textlength(part, font=part_font)


def _render_overlay(project: KaraokeProject, active_line: int | None, active_word: int | None) -> Image.Image:
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    family = project.visual.font
    title_font = _font(48, True, family)
    line_font = _font(68, True, family)
    next_font = _font(38, False, family)
    subtitle_font = _font(27, False, family)
    inactive, highlight = _rgb(project.visual.inactive_color), _rgb(project.visual.highlight_color)
    _draw_centered(draw, project.title, 100, title_font, highlight, family=family, bold=True)
    if project.subtitle:
        _draw_centered(draw, project.subtitle, 155, subtitle_font, inactive, family=family)
    position = {"top": 260, "center": 540, "bottom": 790}[project.visual.position]
    current = project.lines[active_line] if active_line is not None and 0 <= active_line < len(project.lines) else None
    next_line = project.lines[active_line + 1] if current is not None and active_line + 1 < len(project.lines) else None
    if current:
        if current.words:
            _draw_word_line(draw, (current.words, active_word if active_word is not None else -1), position, line_font, inactive, highlight, family)
        else:
            _draw_centered(draw, current.text, position, line_font, highlight, family=family, bold=True)
    if next_line:
        _draw_centered(draw, next_line.text, position + 105, next_font, inactive, family=family)
    return overlay


def _probe_duration(path: Path) -> float:
    ffprobe = resolve_tool("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe is required to render a karaoke video.")
    try:
        result = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)], capture_output=True, text=True, check=False, timeout=15)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("ffprobe timed out while reading instrumental duration.") from exc
    if result.returncode != 0:
        raise RuntimeError("Could not read instrumental duration.")
    try:
        duration = float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OverflowError) as exc:
        raise RuntimeError("Could not read instrumental duration.") from exc
    if not math.isfinite(duration) or not 0 < duration <= 86_400:
        raise RuntimeError("Instrumental duration is outside the supported range.")
    return duration


def _cue_events(project: KaraokeProject, duration: float) -> list[tuple[int, int, int]]:
    duration_ms = round(duration * 1000)
    events: list[tuple[int, int, int]] = list(line_intervals(project.lines, duration_ms, project.offset_ms))
    for _, line_end, line_index in line_intervals(project.lines, duration_ms, project.offset_ms):
        events.extend((start, end, line_index) for start, end, _ in word_intervals(project.lines[line_index], line_end, duration_ms, project.offset_ms))
    return sorted(set(events))


def _active_state(project: KaraokeProject, time_ms: int, duration_ms: int) -> tuple[int | None, int | None]:
    intervals = line_intervals(project.lines, duration_ms, project.offset_ms)
    active = next(((start, end, index) for start, end, index in intervals if start <= time_ms < end), None)
    if active is None:
        return None, None
    _, line_end, line_index = active
    word = next((index for start, end, index in word_intervals(project.lines[line_index], line_end, duration_ms, project.offset_ms) if start <= time_ms < end), None)
    return line_index, word


def _safe_log(log, line: str) -> None:
    if log.tell() >= MAX_RENDER_LOG_BYTES:
        return
    line = re.sub(r'(?i)(?:"(?:[A-Za-z]:[\\/]|/)[^"]*"|(?:[A-Za-z]:[\\/]|/)[^\r\n]*?(?=\s+-[A-Za-z]|\s+\[Errno|$))', "<local-path>", line)
    log.write(line[: MAX_RENDER_LOG_BYTES - log.tell()])
    log.flush()


def _clean_render_artifacts(job_dir: Path) -> None:
    (job_dir / ".karaoke-render.partial.mp4").unlink(missing_ok=True)
    for path in job_dir.glob("karaoke-render-*"):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


def render_video(job_dir: Path, project: KaraokeProject, update) -> None:
    ffmpeg = resolve_tool("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required to render a karaoke video.")
    instrumental = job_dir / "instrumental.wav"
    if not instrumental.is_file():
        raise RuntimeError("The instrumental WAV is not available.")
    _clean_render_artifacts(job_dir)
    try:
        encoder_probe = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, check=False, timeout=15)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("FFmpeg encoder probe timed out.") from exc
    if encoder_probe.returncode != 0 or "libx264" not in encoder_probe.stdout:
        raise RuntimeError("This FFmpeg build does not include the required libx264 encoder.")
    duration = _probe_duration(instrumental)
    duration_ms = round(duration * 1000)
    cues = _cue_events(project, duration)
    boundaries = sorted({0, duration_ms, *(value for start, end, _ in cues for value in (start, end))})
    states = [_active_state(project, start, duration_ms) for start in boundaries[:-1]]
    state_count = sum(1 for index, state in enumerate(states) if index == 0 or state != states[index - 1])
    if state_count > KARAOKE_MAX_EVENTS:
        raise RuntimeError("This karaoke project has too many render states.")
    required_space = max(256 * 1024 * 1024, state_count * 8 * 1024 * 1024 + int(duration * 2 * 1024 * 1024) + 64 * 1024 * 1024)
    if shutil.disk_usage(job_dir).free < required_space:
        raise RuntimeError("Not enough free disk space for a karaoke render.")
    custom = job_dir / "karaoke-background.png" if project.visual.background == "custom" else None
    scratch = Path(tempfile.mkdtemp(prefix="karaoke-render-", dir=job_dir))
    partial = job_dir / ".karaoke-render.partial.mp4"
    try:
        _background(project, custom).save(scratch / "background.png", format="PNG", optimize=True)
        shutil.copyfile(instrumental, scratch / "instrumental.wav")
        manifest = scratch / "overlays.txt"
        previous: tuple[int | None, int | None] | None = None
        frame_path = scratch / "overlay-00000.png"
        with manifest.open("w", encoding="utf-8") as output:
            for frame_number, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
                state = states[frame_number]
                if state != previous:
                    frame_path = scratch / f"overlay-{frame_number:05d}.png"
                    _render_overlay(project, *state).save(frame_path, format="PNG", optimize=True)
                    previous = state
                output.write(f"file '{frame_path.name}'\n")
                output.write(f"duration {(end - start) / 1000:.6f}\n")
            output.write(f"file '{frame_path.name}'\n")
        log_path = job_dir / "karaoke-render.log"
        command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "warning", "-loop", "1", "-framerate", str(FPS), "-i", "background.png", "-f", "concat", "-safe", "1", "-i", "overlays.txt", "-i", "instrumental.wav", "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto[v]", "-map", "[v]", "-map", "2:a:0", "-t", f"{duration:.3f}", "-r", str(FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(partial)]
        with log_path.open("w", encoding="utf-8") as log:
            _safe_log(log, "$ " + " ".join(command) + "\n")
            process = subprocess.Popen(command, cwd=scratch, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            process_finished = False
            try:
                if process.stdout:
                    for line in process.stdout:
                        _safe_log(log, line)
                        if line.startswith("out_time_ms="):
                            try:
                                update(progress=min(99, max(1, round(float(line.split("=", 1)[1]) / 1_000_000 * 100 / duration))), message="Rendering karaoke video")
                            except (ValueError, ZeroDivisionError):
                                pass
                code = process.wait()
                process_finished = True
            finally:
                if not process_finished:
                    terminate = getattr(process, "terminate", None)
                    if terminate:
                        try:
                            terminate()
                        except OSError:
                            pass
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        kill = getattr(process, "kill", None)
                        if kill:
                            try:
                                kill()
                            except OSError:
                                pass
                        try:
                            process.wait(timeout=5)
                        except (subprocess.TimeoutExpired, OSError):
                            pass
                    except (TypeError, OSError):
                        try:
                            process.wait()
                        except OSError:
                            pass
        if code != 0 or not partial.is_file():
            raise RuntimeError("FFmpeg could not render the karaoke video. See karaoke-render.log.")
        partial.replace(job_dir / "karaoke.mp4")
        update(progress=100, message="Karaoke video is ready")
    finally:
        partial.unlink(missing_ok=True)
        shutil.rmtree(scratch, ignore_errors=True)

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from .lyrics import LyricLine, LyricsRecord, get_lyrics, normalize_record, public_record, search_lyrics

KARAOKE_VERSION = 1
KARAOKE_MAX_DURATION_MS = 86_400_000
KARAOKE_MAX_LINES = 1000
KARAOKE_MAX_WORDS = 10_000
KARAOKE_MAX_EVENTS = 20_000
KARAOKE_MAX_TEXT = 500_000
KaraokeStatus = Literal["empty", "draft", "queued", "rendering", "completed", "failed"]
KARAOKE_ACTIVE_STATUSES = {"queued", "rendering"}
BACKGROUND_MODES = Literal["neon", "solid", "gradient", "custom"]
FONT_IDS = Literal["sans", "display", "mono"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WordModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=500)
    start_ms: StrictInt = Field(ge=0, le=KARAOKE_MAX_DURATION_MS)
    end_ms: StrictInt | None = Field(default=None, ge=0, le=KARAOKE_MAX_DURATION_MS)


class LineModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=500)
    start_ms: StrictInt = Field(ge=0, le=KARAOKE_MAX_DURATION_MS)
    end_ms: StrictInt | None = Field(default=None, ge=0, le=KARAOKE_MAX_DURATION_MS)
    words: list[WordModel] = Field(default_factory=list, max_length=200)

    @field_validator("text")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Lyric text cannot be blank.")
        return value

    @model_validator(mode="after")
    def validate_timing(self):
        if self.end_ms is not None and self.end_ms < self.start_ms:
            raise ValueError("Line end must be after line start.")
        previous = self.start_ms
        for index, word in enumerate(self.words):
            if index and word.start_ms < previous:
                raise ValueError("Word timings must be ordered.")
            if word.start_ms < self.start_ms:
                raise ValueError("Word timing must be inside its line.")
            if self.end_ms is not None and word.start_ms > self.end_ms:
                raise ValueError("Word timing must be inside its line.")
            if word.end_ms is not None and (word.end_ms < word.start_ms or (self.end_ms is not None and word.end_ms > self.end_ms)):
                raise ValueError("Word end must be after its start and inside its line.")
            previous = word.start_ms
        if self.words and "".join(word.text for word in self.words) != self.text:
            raise ValueError("Word text must reconstruct its lyric line.")
        return self


class VisualModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    background: BACKGROUND_MODES = "neon"
    solid_color: str = Field(default="#11100f", pattern=r"^#[0-9a-fA-F]{6}$")
    gradient_start: str = Field(default="#24101d", pattern=r"^#[0-9a-fA-F]{6}$")
    gradient_end: str = Field(default="#0c111d", pattern=r"^#[0-9a-fA-F]{6}$")
    font: FONT_IDS = "sans"
    inactive_color: str = Field(default="#f7efe3", pattern=r"^#[0-9a-fA-F]{6}$")
    highlight_color: str = Field(default="#f2b13e", pattern=r"^#[0-9a-fA-F]{6}$")
    position: Literal["top", "center", "bottom"] = "center"


class KaraokeProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = KARAOKE_VERSION
    revision: int = Field(default=1, ge=1, le=1_000_000)
    record: dict[str, Any]
    fetched_at: str = Field(min_length=1, max_length=80)
    lines: list[LineModel] = Field(min_length=1, max_length=KARAOKE_MAX_LINES)
    offset_ms: StrictInt = Field(default=0, ge=-120_000, le=120_000)
    title: str = Field(default="", max_length=300)
    subtitle: str = Field(default="", max_length=300)
    visual: VisualModel = Field(default_factory=VisualModel)

    @field_validator("record")
    @classmethod
    def validate_record(cls, record: dict[str, Any]) -> dict[str, Any]:
        if len(record) > 12:
            raise ValueError("Lyrics provenance is invalid.")
        for key, value in record.items():
            if len(str(key)) > 50 or (isinstance(value, str) and len(value) > 500):
                raise ValueError("Lyrics provenance is too large.")
        return record

    @model_validator(mode="after")
    def validate_project(self):
        previous = -1
        text_size = 0
        word_count = 0
        event_count = len(self.lines)
        for line in self.lines:
            if line.start_ms < previous:
                raise ValueError("Lyric lines must be ordered.")
            previous = line.start_ms
            text_size += len(line.text)
            word_count += len(line.words)
            event_count += len(line.words)
        if text_size > KARAOKE_MAX_TEXT or word_count > KARAOKE_MAX_WORDS or event_count > KARAOKE_MAX_EVENTS:
            raise ValueError("The karaoke project is too large to render locally.")
        if self.lines and all(line.end_ms is not None and line.end_ms <= line.start_ms for line in self.lines):
            raise ValueError("The synchronized lyrics have no usable duration.")
        return self


class KaraokeState(BaseModel):
    status: KaraokeStatus = "empty"
    progress: int = Field(default=0, ge=0, le=100)
    message: str = ""
    error: str | None = None
    project_revision: int | None = None
    rendered_revision: int | None = None
    updated_at: str = ""


def _line_from_domain(line: LyricLine) -> LineModel:
    return LineModel(text=line.text, start_ms=line.start_ms, end_ms=line.end_ms, words=[WordModel.model_validate(word.__dict__) for word in line.words])


def project_from_record(record: LyricsRecord, *, revision: int = 1) -> KaraokeProject:
    lines = normalize_record(record)
    if not lines:
        raise ValueError("The selected record has no valid synchronized lyric lines.")
    return KaraokeProject(record=public_record(record), fetched_at=now(), revision=revision, lines=[_line_from_domain(line) for line in lines], title=record.title, subtitle=record.artist)


def project_path(job_dir: Path) -> Path:
    return job_dir / "karaoke-project.json"


def state_from_job(job: Any) -> KaraokeState:
    return KaraokeState(status=getattr(job, "karaoke_status", "empty"), progress=getattr(job, "karaoke_progress", 0), message=getattr(job, "karaoke_message", ""), error=getattr(job, "karaoke_error", None), project_revision=getattr(job, "karaoke_project_revision", None), rendered_revision=getattr(job, "karaoke_rendered_revision", None), updated_at=getattr(job, "karaoke_updated_at", "") or "")


def load_project(job_dir: Path) -> KaraokeProject | None:
    path = project_path(job_dir)
    if not path.is_file():
        return None
    try:
        return KaraokeProject.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def _atomic_write_project(job_dir: Path, project: KaraokeProject) -> KaraokeProject:
    path = project_path(job_dir)
    temporary = path.with_name(f".{path.name}.{id(project)}.tmp")
    temporary.write_text(project.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)
    return project


def save_project(job_dir: Path, project: KaraokeProject) -> KaraokeProject:
    existing = load_project(job_dir)
    revision = existing.revision + 1 if existing else max(1, project.revision + 1)
    return _atomic_write_project(job_dir, project.model_copy(update={"revision": revision}))


def select_record(job_dir: Path, record_id: int, *, persist: bool = True) -> KaraokeProject:
    existing = load_project(job_dir)
    revision = existing.revision + 1 if existing and persist else (existing.revision if existing else 1)
    project = project_from_record(get_lyrics(record_id), revision=revision)
    return _atomic_write_project(job_dir, project) if persist else project


def remove_background(job_dir: Path) -> None:
    for suffix in (".png", ".jpg", ".jpeg", ".webp"):
        (job_dir / f"karaoke-background{suffix}").unlink(missing_ok=True)


def background_path(job_dir: Path) -> Path | None:
    for suffix in (".png", ".jpg", ".jpeg", ".webp"):
        path = job_dir / f"karaoke-background{suffix}"
        if path.is_file():
            return path
    return None


def search(title: str, artist: str, album: str = "") -> list[dict[str, Any]]:
    return [public_record(record) for record in search_lyrics(title, artist, album)]


def render_job(job_dir: Path, project: KaraokeProject, update) -> None:
    from .karaoke_renderer import render_video
    render_video(job_dir, project, update)


__all__ = ["BACKGROUND_MODES", "FONT_IDS", "KARAOKE_ACTIVE_STATUSES", "KaraokeProject", "KaraokeState", "KaraokeStatus", "LineModel", "WordModel", "VisualModel", "background_path", "load_project", "project_from_record", "project_path", "remove_background", "render_job", "save_project", "search", "select_record", "state_from_job"]

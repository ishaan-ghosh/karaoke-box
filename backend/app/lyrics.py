from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

import yaml

MAX_LYRICS_RESPONSE_BYTES = 512 * 1024
MAX_LYRICS_LINES = 1000
MAX_LINE_TEXT = 500
MAX_WORDS_PER_LINE = 200
MAX_YAML_NODES = 5000
MAX_LYRICS_DURATION_MS = 86_400_000
MAX_RECORD_DURATION_SECONDS = MAX_LYRICS_DURATION_MS / 1000
LRCLIB_BASE_URL = "https://lrclib.net"
LRCLIB_USER_AGENT = "Karaoke Box/0.1.0 (https://github.com/ishaan-ghosh/karaoke-box)"


class LyricsError(RuntimeError):
    pass


class _BoundedLoader(yaml.SafeLoader):
    """SafeLoader with composition-time depth/node limits and no aliases."""

    def __init__(self, stream):
        super().__init__(stream)
        self._node_count = 0
        self._depth = 0

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise yaml.YAMLError("YAML aliases are not allowed")
        self._node_count += 1
        if self._node_count > MAX_YAML_NODES:
            raise yaml.YAMLError("YAML document is too large")
        self._depth += 1
        if self._depth > 40:
            self._depth -= 1
            raise yaml.YAMLError("YAML document is too deep")
        try:
            return super().compose_node(parent, index)
        finally:
            self._depth -= 1


@dataclass(frozen=True)
class LyricWord:
    text: str
    start_ms: int
    end_ms: int | None = None


@dataclass(frozen=True)
class LyricLine:
    text: str
    start_ms: int
    end_ms: int | None = None
    words: tuple[LyricWord, ...] = ()


@dataclass(frozen=True)
class LyricsRecord:
    record_id: int
    title: str
    artist: str
    album: str
    duration_seconds: float
    plain_lyrics: str | None
    synced_lyrics: str | None
    lyricsfile: str | None
    instrumental: bool = False


_TIMESTAMP = re.compile(r"^\[(\d{1,3}):(\d{1,2})(?:\.(\d{1,3}))?\]")
_OFFSET_TAG = re.compile(r"\[offset\s*:\s*([+-]?\d+)\]", re.IGNORECASE)


def _finite_int(value: Any, *, minimum: int, maximum: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if minimum <= number <= maximum else None


def _timestamp_ms(value: str) -> int:
    match = _TIMESTAMP.match(value)
    if not match:
        raise ValueError("invalid timestamp")
    minutes, seconds, fraction = match.groups()
    if int(seconds) >= 60:
        raise ValueError("invalid timestamp")
    millis = int((fraction or "0").ljust(3, "0")[:3])
    result = int(minutes) * 60_000 + int(seconds) * 1000 + millis
    if result > MAX_LYRICS_DURATION_MS:
        raise ValueError("timestamp exceeds duration limit")
    return result


def parse_lrc(text: str, *, offset_ms: int = 0) -> tuple[LyricLine, ...]:
    """Parse line-leading LRC timestamps with one file-wide offset."""
    file_offset = offset_ms
    for raw in text.splitlines():
        match = _OFFSET_TAG.search(raw)
        if match:
            try:
                parsed = int(match.group(1))
            except (TypeError, ValueError, OverflowError):
                parsed = None
            if parsed is not None and -120_000 <= parsed <= 120_000:
                file_offset += parsed
            break

    rows: list[LyricLine] = []
    for raw in text.splitlines():
        rest = raw.strip()
        stamps: list[int] = []
        while rest.startswith("["):
            match = _TIMESTAMP.match(rest)
            if not match:
                break
            try:
                start = _timestamp_ms(match.group(0)) + file_offset
            except ValueError:
                stamps.clear()
                break
            stamps.append(max(0, min(MAX_LYRICS_DURATION_MS, start)))
            rest = rest[match.end():]
        if stamps and rest.strip():
            rows.extend(LyricLine(rest.strip()[:MAX_LINE_TEXT], start) for start in stamps)
    rows.sort(key=lambda line: line.start_ms)
    return tuple(rows[:MAX_LYRICS_LINES])


def _bounded_text(value: Any, limit: int) -> str | None:
    if value is None or not isinstance(value, str):
        return None
    value = value.replace("\x00", "").strip()
    return value[:limit] if value else None


def _parse_words(value: Any, line_start: int, line_end: int | None, line_text: str) -> tuple[LyricWord, ...]:
    if not isinstance(value, list) or not value or len(value) > MAX_WORDS_PER_LINE:
        return ()
    words: list[LyricWord] = []
    previous = line_start
    for item in value:
        if not isinstance(item, dict):
            return ()
        raw_word = item.get("text")
        word = raw_word.replace("\x00", "")[:MAX_LINE_TEXT] if isinstance(raw_word, str) else None
        start = _finite_int(item.get("start_ms"), minimum=line_start, maximum=MAX_LYRICS_DURATION_MS)
        end_value = item.get("end_ms")
        end = None if end_value is None else _finite_int(end_value, minimum=line_start, maximum=MAX_LYRICS_DURATION_MS)
        if not word or start is None or start < previous:
            return ()
        if end_value is not None and end is None:
            return ()
        if end is not None and end < start:
            return ()
        if line_end is not None and (start > line_end or (end is not None and end > line_end)):
            return ()
        words.append(LyricWord(word, start, end))
        previous = start
    if "".join(word.text for word in words) != line_text:
        return ()
    return tuple(words)


def parse_lyricsfile(raw: str | None) -> tuple[LyricLine, ...]:
    if not raw or len(raw.encode("utf-8")) > MAX_LYRICS_RESPONSE_BYTES:
        return ()
    try:
        data = yaml.load(raw, Loader=_BoundedLoader)
        if not isinstance(data, dict) or data.get("version") != "1.0":
            return ()
        metadata = data.get("metadata")
        metadata_offset = 0
        if isinstance(metadata, dict) and "offset_ms" in metadata:
            metadata_offset = _finite_int(metadata.get("offset_ms"), minimum=-120_000, maximum=120_000)
            if metadata_offset is None:
                return ()
        lines = data.get("lines")
        if not isinstance(lines, list) or len(lines) > MAX_LYRICS_LINES:
            return ()
        result: list[LyricLine] = []
        previous = -1
        for item in lines:
            if not isinstance(item, dict):
                return ()
            text = _bounded_text(item.get("text"), MAX_LINE_TEXT)
            start_raw = _finite_int(item.get("start_ms"), minimum=0, maximum=MAX_LYRICS_DURATION_MS)
            if not text or start_raw is None:
                return ()
            start = max(0, min(MAX_LYRICS_DURATION_MS, start_raw + metadata_offset))
            end_value = item.get("end_ms")
            end_raw = None if end_value is None else _finite_int(end_value, minimum=0, maximum=MAX_LYRICS_DURATION_MS)
            if end_value is not None and end_raw is None:
                return ()
            if end_raw is not None and end_raw < start_raw:
                return ()
            end = None if end_raw is None else end_raw + metadata_offset
            if end is not None and not 0 <= end <= MAX_LYRICS_DURATION_MS:
                return ()
            if start < previous or (end is not None and end <= start):
                return ()
            words = _parse_words(item.get("words"), start_raw, end_raw, text)
            shifted_words: list[LyricWord] = []
            for word in words:
                shifted_start = word.start_ms + metadata_offset
                shifted_end = None if word.end_ms is None else word.end_ms + metadata_offset
                if not 0 <= shifted_start <= MAX_LYRICS_DURATION_MS or (shifted_end is not None and not 0 <= shifted_end <= MAX_LYRICS_DURATION_MS):
                    words = ()
                    break
                if shifted_start < start or (end is not None and shifted_start > end) or (shifted_end is not None and (shifted_end < shifted_start or (end is not None and shifted_end > end))):
                    words = ()
                    break
                shifted_words.append(LyricWord(word.text, shifted_start, shifted_end))
            else:
                words = tuple(shifted_words)
            result.append(LyricLine(text, start, end, words))
            previous = start
        if result and all(line.end_ms is not None and line.end_ms <= line.start_ms for line in result):
            return ()
        return tuple(result)
    except (yaml.YAMLError, RecursionError, ValueError, OverflowError, MemoryError):
        return ()


def _record(value: Any) -> LyricsRecord | None:
    if not isinstance(value, dict):
        return None
    raw_id = value.get("id")
    if isinstance(raw_id, bool) or not isinstance(raw_id, int) or raw_id <= 0:
        return None
    raw_duration = value.get("duration")
    if raw_duration is None:
        duration = 0.0
    elif isinstance(raw_duration, bool) or not isinstance(raw_duration, (int, float)):
        return None
    else:
        try:
            duration = float(raw_duration)
        except (TypeError, ValueError, OverflowError):
            return None
    if not math.isfinite(duration) or duration < 0 or duration > MAX_RECORD_DURATION_SECONDS:
        return None
    raw_instrumental = value.get("instrumental", False)
    if not isinstance(raw_instrumental, bool):
        return None
    for field in ("trackName", "name", "artistName", "albumName", "plainLyrics", "syncedLyrics", "lyricsfile"):
        raw_text = value.get(field)
        if raw_text is not None and not isinstance(raw_text, str):
            return None
    return LyricsRecord(
        raw_id,
        _bounded_text(value.get("trackName") or value.get("name"), 300) or "Unknown track",
        _bounded_text(value.get("artistName"), 300) or "Unknown artist",
        _bounded_text(value.get("albumName"), 300) or "",
        duration,
        _bounded_text(value.get("plainLyrics"), MAX_LYRICS_RESPONSE_BYTES),
        _bounded_text(value.get("syncedLyrics"), MAX_LYRICS_RESPONSE_BYTES),
        _bounded_text(value.get("lyricsfile"), MAX_LYRICS_RESPONSE_BYTES),
        raw_instrumental,
    )


_ORIGINAL_URLOPEN = urllib.request.urlopen


class _StrictRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        source = urllib.parse.urlsplit(req.full_url)
        target = urllib.parse.urlsplit(newurl)
        if source.scheme != "https" or target.scheme != "https" or target.hostname != "lrclib.net" or target.port not in (None, 443):
            raise urllib.error.HTTPError(req.full_url, code, "Unsafe LRCLIB redirect", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(request: urllib.request.Request):
    if urllib.request.urlopen is not _ORIGINAL_URLOPEN:
        return urllib.request.urlopen(request, timeout=10)
    return urllib.request.build_opener(_StrictRedirectHandler()).open(request, timeout=10)


def _request(path: str, params: dict[str, str]) -> Any:
    query = urllib.parse.urlencode(params)
    url = f"{LRCLIB_BASE_URL}{path}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": LRCLIB_USER_AGENT, "Accept": "application/json"})
    try:
        with _open(request) as response:
            payload = response.read(MAX_LYRICS_RESPONSE_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LyricsError("LRCLIB could not be reached.") from exc
    if len(payload) > MAX_LYRICS_RESPONSE_BYTES:
        raise LyricsError("LRCLIB returned an oversized response.")
    def bounded_int(raw: str) -> int:
        if len(raw) > 20:
            raise ValueError("numeric value is too large")
        return int(raw)

    def bounded_float(raw: str) -> float:
        if len(raw) > 32:
            raise ValueError("numeric value is too large")
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError("numeric value is not finite")
        return value

    def reject_constant(raw: str) -> Any:
        raise ValueError(f"invalid numeric constant: {raw}")

    try:
        return json.loads(payload.decode("utf-8"), parse_int=bounded_int, parse_float=bounded_float, parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError, MemoryError) as exc:
        raise LyricsError("LRCLIB returned invalid JSON.") from exc


def normalize_record(record: LyricsRecord) -> tuple[LyricLine, ...]:
    lyricsfile_lines = parse_lyricsfile(record.lyricsfile) if record.lyricsfile else ()
    return lyricsfile_lines or parse_lrc(record.synced_lyrics or "")


def _has_timed_lines(record: LyricsRecord) -> bool:
    return not record.instrumental and bool(normalize_record(record))


def search_lyrics(title: str, artist: str, album: str = "") -> list[LyricsRecord]:
    data = _request("/api/search", {"track_name": title[:300], "artist_name": artist[:300], "album_name": album[:300]})
    if not isinstance(data, list):
        raise LyricsError("LRCLIB returned an invalid search result.")
    return [record for item in data[:20] if (record := _record(item)) is not None and _has_timed_lines(record)]


def get_lyrics(record_id: int) -> LyricsRecord:
    if record_id <= 0:
        raise LyricsError("Invalid LRCLIB record ID.")
    record = _record(_request(f"/api/get/{record_id}", {}))
    if record is None or not _has_timed_lines(record):
        raise LyricsError("This LRCLIB record has no valid synchronized lyrics.")
    return record


def line_intervals(lines: tuple[LyricLine, ...] | list[LyricLine], duration_ms: int, offset_ms: int = 0) -> tuple[tuple[int, int, int], ...]:
    bounded_duration = max(0, int(duration_ms))
    intervals: list[tuple[int, int, int]] = []
    for index, line in enumerate(lines):
        start = max(0, min(bounded_duration, line.start_ms + offset_ms))
        next_start = lines[index + 1].start_ms + offset_ms if index + 1 < len(lines) else bounded_duration
        end = (line.end_ms if line.end_ms is not None else next_start) + (offset_ms if line.end_ms is not None else 0)
        end = max(start, min(bounded_duration, end))
        if end > start:
            intervals.append((start, end, index))
    return tuple(intervals)


def word_intervals(line: LyricLine, line_end_ms: int, duration_ms: int, offset_ms: int = 0) -> tuple[tuple[int, int, int], ...]:
    duration = max(0, int(duration_ms))
    result: list[tuple[int, int, int]] = []
    for index, word in enumerate(line.words):
        start = max(0, min(duration, word.start_ms + offset_ms))
        next_start = line.words[index + 1].start_ms + offset_ms if index + 1 < len(line.words) else line_end_ms
        end = (word.end_ms if word.end_ms is not None else next_start) + (offset_ms if word.end_ms is not None else 0)
        end = max(start, min(duration, end))
        if end > start:
            result.append((start, end, index))
    return tuple(result)


def public_record(record: LyricsRecord) -> dict[str, Any]:
    lines = normalize_record(record)
    return {"id": record.record_id, "title": record.title, "artist": record.artist, "album": record.album, "duration_seconds": record.duration_seconds, "has_word_timing": any(line.words for line in lines), "instrumental": record.instrumental}

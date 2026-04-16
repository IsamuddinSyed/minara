from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(slots=True)
class SubtitleWord:
    text: str
    start: float
    end: float


@dataclass(slots=True)
class SubtitleCue:
    start: float
    end: float
    text: str


def _normalize_word(text: str) -> str:
    return " ".join((text or "").strip().split())


def _escape_ass_text(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def _format_ass_timestamp(seconds: float) -> str:
    clamped = max(0.0, seconds)
    hours = int(clamped // 3600)
    minutes = int((clamped % 3600) // 60)
    secs = clamped % 60
    centiseconds = int(round((secs - int(secs)) * 100))
    whole_seconds = int(secs)

    if centiseconds >= 100:
        centiseconds = 0
        whole_seconds += 1
    if whole_seconds >= 60:
        whole_seconds = 0
        minutes += 1
    if minutes >= 60:
        minutes = 0
        hours += 1

    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}"


def words_for_clip(
    words: Sequence[SubtitleWord],
    *,
    clip_start: float,
    clip_end: float,
) -> list[SubtitleWord]:
    clip_words: list[SubtitleWord] = []
    for word in words:
        if word.end <= clip_start or word.start >= clip_end:
            continue
        start = max(0.0, word.start - clip_start)
        end = min(clip_end, word.end) - clip_start
        text = _normalize_word(word.text)
        if not text or end <= start:
            continue
        clip_words.append(SubtitleWord(text=text, start=start, end=end))
    return clip_words


def build_phrase_cues(words: Sequence[SubtitleWord]) -> list[SubtitleCue]:
    cues: list[SubtitleCue] = []
    current: list[SubtitleWord] = []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        text = " ".join(item.text for item in current).strip()
        if text:
            cues.append(
                SubtitleCue(
                    start=current[0].start,
                    end=current[-1].end,
                    text=text,
                )
            )
        current = []

    for word in words:
        if not current:
            current.append(word)
            continue

        gap = word.start - current[-1].end
        current_text = " ".join(item.text for item in current)
        should_flush = (
            len(current) >= 6
            or len(current_text) >= 34
            or gap >= 0.6
            or current_text.endswith((".", "?", "!", ",", ";", ":"))
        )
        if should_flush:
            flush()
        current.append(word)

    flush()
    return [cue for cue in cues if cue.end > cue.start and cue.text]


def render_ass_subtitles(cues: Sequence[SubtitleCue]) -> str:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,DejaVu Sans,72,&H00F9F6F0,&H00F9F6F0,&H002B2014,&H64000000,-1,0,0,0,100,100,0,0,1,4,0,2,120,120,360,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for cue in cues:
        events.append(
            "Dialogue: 0,"
            f"{_format_ass_timestamp(cue.start)},"
            f"{_format_ass_timestamp(cue.end)},"
            f"Caption,,0,0,0,,{_escape_ass_text(cue.text)}"
        )
    return header + "\n".join(events) + ("\n" if events else "")


def write_ass_subtitles(path: Path, cues: Sequence[SubtitleCue]) -> None:
    path.write_text(render_ass_subtitles(cues), encoding="utf-8")

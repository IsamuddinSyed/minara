from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import re
from typing import Sequence

from caption_styling import select_power_word

logger = logging.getLogger(__name__)


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
    highlighted_word: str | None = None


def _normalize_word(text: str) -> str:
    return " ".join((text or "").strip().split())


def _escape_ass_text(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def _is_valid_ass_event_text(text: str) -> bool:
    balance = 0
    for char in text:
        if char == "{":
            balance += 1
        elif char == "}":
            balance -= 1
        if balance < 0:
            return False
    return balance == 0


def _highlight_ass_text(text: str, highlighted_word: str | None) -> str:
    escaped = _escape_ass_text(text)
    if not highlighted_word:
        return escaped

    try:
        match = re.search(rf"\b{re.escape(highlighted_word)}\b", text, flags=re.IGNORECASE)
        if not match:
            return escaped

        before = _escape_ass_text(text[: match.start()])
        matched = _escape_ass_text(text[match.start() : match.end()])
        after = _escape_ass_text(text[match.end() :])

        # ASS per-word boxing is brittle across renderers, so Phase B uses a
        # reliable high-contrast color + outline + bold fallback for one word.
        highlighted = (
            r"{\1c&H0071CC2E&\3c&H00161B2B&\b1\fscx112\fscy112}"
            + matched
            + r"{\1c&H00F9F6F0&\3c&H002B2014&\b0\fscx100\fscy100}"
        )
        candidate = before + highlighted + after
        if _is_valid_ass_event_text(candidate):
            return candidate

        logger.warning(
            "ASS highlight validation failed; falling back to plain cue text",
            extra={"highlighted_word": highlighted_word},
        )
    except re.error as exc:
        logger.warning(
            "ASS highlight regex failed; falling back to plain cue text: %s",
            exc,
        )

    return escaped


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


def _cue_animation_tags(cue: SubtitleCue) -> str:
    duration_ms = max(1, int(round((cue.end - cue.start) * 1000)))
    pop_in_peak = min(100, duration_ms)
    pop_in_settle = min(150, duration_ms)
    exit_start = max(0, duration_ms - 120)

    return (
        r"{\an5\pos(540,1140)\fsp1"
        r"\fscx0\fscy0"
        rf"\t(0,{pop_in_peak},\fscx110\fscy110)"
        rf"\t({pop_in_peak},{pop_in_settle},\fscx100\fscy100)"
        rf"\t({exit_start},{duration_ms},\fscx92\fscy92\alpha&HFF&)"
        r"}"
    )


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
                    highlighted_word=select_power_word(text),
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
            len(current) >= 3
            or len(current_text) >= 18
            or gap >= 0.35
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
Style: Caption,DejaVu Sans,70,&H00F9F6F0,&H00F9F6F0,&H00161B2B,&HAA102418,-1,0,0,0,100,100,0.3,0,3,2,0,5,120,120,320,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for cue in cues:
        events.append(
            "Dialogue: 0,"
            f"{_format_ass_timestamp(cue.start)},"
            f"{_format_ass_timestamp(cue.end)},"
            "Caption,,0,0,0,,"
            f"{_cue_animation_tags(cue)}"
            f"{_highlight_ass_text(cue.text, cue.highlighted_word)}"
        )
    return header + "\n".join(events) + ("\n" if events else "")


def write_ass_subtitles(path: Path, cues: Sequence[SubtitleCue]) -> None:
    logger.info("Writing ASS subtitles to %s", path)
    path.write_text(render_ass_subtitles(cues), encoding="utf-8")

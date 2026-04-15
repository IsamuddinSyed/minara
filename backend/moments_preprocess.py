from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol


class WordLike(Protocol):
    word: str
    start: float
    end: float


@dataclass(slots=True)
class SentenceUnit:
    sentence_id: int
    text: str
    start_time: float
    end_time: float


_TERMINAL_PUNCTUATION = (".", "?", "!")
_HARD_PAUSE_SECONDS = 1.0
_MIN_WORDS_BEFORE_PAUSE_SPLIT = 6


def _normalize_token(token: str) -> str:
    return " ".join((token or "").strip().split())


def _join_tokens(tokens: list[str]) -> str:
    text = ""
    for token in tokens:
        if not token:
            continue
        if not text:
            text = token
            continue
        if token[0] in ",.;:!?)]}" or token in {"n't", "'s", "'re", "'ve", "'ll", "'m", "'d"}:
            text += token
        else:
            text += f" {token}"
    return text.strip()


def _is_sentence_boundary(token: str) -> bool:
    return token.endswith(_TERMINAL_PUNCTUATION)


def build_sentence_units(words: Iterable[WordLike]) -> list[SentenceUnit]:
    """Build sentence units from word-level timestamps with light spoken-boundary heuristics."""
    sentence_units: list[SentenceUnit] = []
    current_tokens: list[str] = []
    current_start: float | None = None
    last_end: float | None = None
    sentence_id = 1

    for raw_word in words:
        token = _normalize_token(raw_word.word)
        if not token:
            continue

        start = float(raw_word.start)
        end = float(raw_word.end)
        if end <= start:
            continue

        if current_start is None:
            current_start = start

        pause_split = (
            last_end is not None
            and (start - last_end) >= _HARD_PAUSE_SECONDS
            and len(current_tokens) >= _MIN_WORDS_BEFORE_PAUSE_SPLIT
        )
        if pause_split:
            sentence_text = _join_tokens(current_tokens)
            if sentence_text:
                sentence_units.append(
                    SentenceUnit(
                        sentence_id=sentence_id,
                        text=sentence_text,
                        start_time=current_start,
                        end_time=last_end,
                    )
                )
                sentence_id += 1
            current_tokens = []
            current_start = start

        current_tokens.append(token)
        last_end = end

        if _is_sentence_boundary(token):
            sentence_text = _join_tokens(current_tokens)
            if sentence_text and current_start is not None:
                sentence_units.append(
                    SentenceUnit(
                        sentence_id=sentence_id,
                        text=sentence_text,
                        start_time=current_start,
                        end_time=end,
                    )
                )
                sentence_id += 1
            current_tokens = []
            current_start = None
            last_end = end

    if current_tokens and current_start is not None and last_end is not None:
        sentence_text = _join_tokens(current_tokens)
        if sentence_text:
            sentence_units.append(
                SentenceUnit(
                    sentence_id=sentence_id,
                    text=sentence_text,
                    start_time=current_start,
                    end_time=last_end,
                )
            )

    if not sentence_units:
        return []

    # Ensure strictly increasing IDs and monotonic non-negative timing.
    cleaned: list[SentenceUnit] = []
    next_id = 1
    for unit in sentence_units:
        if unit.end_time <= unit.start_time:
            continue
        cleaned.append(
            SentenceUnit(
                sentence_id=next_id,
                text=unit.text.strip(),
                start_time=max(0.0, unit.start_time),
                end_time=max(0.0, unit.end_time),
            )
        )
        next_id += 1
    return cleaned

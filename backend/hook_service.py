from __future__ import annotations

import re


def _clean_whitespace(text: str) -> str:
    return " ".join((text or "").strip().split())


def _sentence_head(text: str) -> str:
    cleaned = _clean_whitespace(text)
    if not cleaned:
        return ""
    return re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)[0].strip()


def _clip_words(text: str, max_words: int = 6) -> str:
    words = _clean_whitespace(text).split()
    if not words:
        return ""
    clipped = " ".join(words[:max_words]).strip(" .,!?:;")
    return clipped


def derive_hook_headline(
    *,
    title: str,
    takeaway: str,
    transcript_excerpt: str = "",
) -> str | None:
    title_text = _clean_whitespace(title).strip(" .")
    if title_text and len(title_text) <= 48 and len(title_text.split()) <= 7:
        return title_text

    takeaway_head = _sentence_head(takeaway)
    if takeaway_head:
        clipped = _clip_words(takeaway_head)
        if clipped:
            return clipped

    excerpt_head = _sentence_head(transcript_excerpt)
    if excerpt_head:
        clipped = _clip_words(excerpt_head)
        if clipped:
            return clipped

    return title_text or None

from __future__ import annotations

import re


_POWER_WORD_SCORES: dict[str, int] = {
    "allah": 10,
    "tawbah": 10,
    "repentance": 9,
    "sincerity": 9,
    "mercy": 9,
    "guidance": 9,
    "prayer": 9,
    "patience": 8,
    "truth": 8,
    "arrogance": 8,
    "forgiveness": 8,
    "barakah": 8,
    "taqwa": 8,
    "jannah": 8,
    "iman": 8,
    "dua": 8,
    "quran": 8,
    "rahmah": 8,
    "salah": 8,
    "dhikr": 7,
    "humility": 7,
    "heedless": 7,
    "hearts": 7,
    "heart": 7,
    "justice": 7,
    "hope": 7,
    "fear": 7,
    "faith": 7,
    "obedience": 7,
    "paradise": 7,
    "jahannam": 7,
    "halal": 6,
    "haram": 6,
    "purify": 6,
    "purification": 6,
    "discipline": 6,
    "reward": 6,
    "punishment": 6,
    "remember": 5,
    "protect": 5,
    "change": 5,
    "save": 5,
}

_TOKEN_RE = re.compile(r"[A-Za-z']+")


def _normalize_token(token: str) -> str:
    return re.sub(r"[^a-z]", "", token.lower())


def select_power_word(text: str) -> str | None:
    best_token: str | None = None
    best_score = 0

    for raw_token in _TOKEN_RE.findall(text):
        normalized = _normalize_token(raw_token)
        if not normalized:
            continue
        score = _POWER_WORD_SCORES.get(normalized, 0)

        # Slightly prefer longer content words as a fallback heuristic.
        if score == 0 and len(normalized) >= 8:
            score = 2
        elif score == 0 and len(normalized) >= 6:
            score = 1

        if score > best_score:
            best_score = score
            best_token = raw_token

    return best_token if best_score > 0 else None

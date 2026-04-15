from __future__ import annotations

import json
from dataclasses import dataclass

from openai import OpenAI


@dataclass(slots=True)
class CandidateClip:
    rank: int
    start_sentence_id: int
    end_sentence_id: int
    title: str
    takeaway: str
    reason: str
    confidence: float


def _to_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def select_candidate_sentence_ranges(
    *,
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_message: str,
) -> list[CandidateClip]:
    completion = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    raw = completion.choices[0].message.content
    if not raw:
        raise ValueError("OpenAI returned an empty response.")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model returned invalid JSON: {exc}") from exc

    clips_raw = parsed.get("clips")
    if not isinstance(clips_raw, list):
        raise ValueError("Model output must contain a 'clips' array.")

    candidates: list[CandidateClip] = []
    for idx, item in enumerate(clips_raw, start=1):
        if not isinstance(item, dict):
            continue
        candidates.append(
            CandidateClip(
                rank=_to_int(item.get("rank"), idx),
                start_sentence_id=_to_int(item.get("start_sentence_id")),
                end_sentence_id=_to_int(item.get("end_sentence_id")),
                title=str(item.get("title", "")).strip(),
                takeaway=str(item.get("takeaway", "")).strip(),
                reason=str(item.get("reason", "")).strip(),
                confidence=_to_float(item.get("confidence"), 0.0),
            )
        )
    return candidates

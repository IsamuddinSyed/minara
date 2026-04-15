from __future__ import annotations

import json
from typing import Any

from moments_preprocess import SentenceUnit


IDENTIFY_MOMENTS_SYSTEM = """You select high-quality Islamic teaching clips from numbered sentence units.

Return only complete mini-lessons that are standalone and understandable without prior context.
Reject partial setup, trivia, or clips where a concept is named but not explained.

Hard rules:
- Output 2 to 5 clips.
- Duration must be 35 to 90 seconds (ideal 45 to 70).
- Start/end must be natural sentence boundaries.
- Never start mid-idea and never end before payoff.

Return JSON only:
{
  "clips": [
    {
      "rank": number,
      "start_sentence_id": number,
      "end_sentence_id": number,
      "title": "string",
      "takeaway": "string",
      "reason": "string",
      "confidence": number
    }
  ]
}

confidence must be 0..1."""


def build_candidate_reasoning_input(
    sentence_units: list[SentenceUnit], meta: dict[str, Any]
) -> str:
    compact_sentences = [
        {
            "id": unit.sentence_id,
            "t": unit.text,
            "s": round(unit.start_time, 3),
            "e": round(unit.end_time, 3),
        }
        for unit in sentence_units
    ]
    compact_meta = {
        "language": meta.get("language"),
        "duration_seconds": meta.get("duration"),
        "sentence_count": len(sentence_units),
    }
    return (
        f"meta={json.dumps(compact_meta, ensure_ascii=False, separators=(',', ':'))}\n"
        f"sentences={json.dumps(compact_sentences, ensure_ascii=False, separators=(',', ':'))}"
    )

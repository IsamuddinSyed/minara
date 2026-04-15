from __future__ import annotations

from dataclasses import dataclass

from moments_llm import CandidateClip
from moments_preprocess import SentenceUnit

MIN_DURATION_SECONDS = 35.0
MAX_DURATION_SECONDS = 90.0
MIN_CLIPS = 2
MAX_CLIPS = 5
MAX_OVERLAP_RATIO = 0.7


@dataclass(slots=True)
class FinalClip:
    rank: int
    start_time: float
    end_time: float
    duration: float
    title: str
    takeaway: str
    reason: str
    confidence_score: float
    transcript_excerpt: str
    start_sentence_id: int
    end_sentence_id: int


def _is_weak_text(text: str) -> bool:
    return len(text.strip()) < 8


def _clip_score(clip: FinalClip) -> float:
    quality_bonus = 0.0
    if 45.0 <= clip.duration <= 70.0:
        quality_bonus += 0.08
    if len(clip.takeaway.split()) >= 7:
        quality_bonus += 0.04
    return max(0.0, min(1.0, clip.confidence_score + quality_bonus))


def _overlap_ratio_seconds(a: FinalClip, b: FinalClip) -> float:
    overlap = max(0.0, min(a.end_time, b.end_time) - max(a.start_time, b.start_time))
    if overlap <= 0.0:
        return 0.0
    shorter = max(1e-6, min(a.duration, b.duration))
    return overlap / shorter


def _build_sentence_index(sentence_units: list[SentenceUnit]) -> dict[int, SentenceUnit]:
    return {unit.sentence_id: unit for unit in sentence_units}


def _range_text(sentence_units: list[SentenceUnit], start_id: int, end_id: int) -> str:
    return " ".join(
        unit.text
        for unit in sentence_units
        if start_id <= unit.sentence_id <= end_id and unit.text.strip()
    ).strip()


def validate_and_build_final_clips(
    candidates: list[CandidateClip], sentence_units: list[SentenceUnit]
) -> list[FinalClip]:
    sentence_index = _build_sentence_index(sentence_units)
    prelim: list[FinalClip] = []

    for item in candidates:
        if item.start_sentence_id <= 0 or item.end_sentence_id <= 0:
            continue
        if item.start_sentence_id > item.end_sentence_id:
            continue
        if item.start_sentence_id not in sentence_index or item.end_sentence_id not in sentence_index:
            continue
        if not (0.0 <= item.confidence <= 1.0):
            continue
        if _is_weak_text(item.title) or _is_weak_text(item.takeaway) or _is_weak_text(item.reason):
            continue

        start_unit = sentence_index[item.start_sentence_id]
        end_unit = sentence_index[item.end_sentence_id]
        start_time = start_unit.start_time
        end_time = end_unit.end_time
        duration = end_time - start_time
        if duration < MIN_DURATION_SECONDS or duration > MAX_DURATION_SECONDS:
            continue

        excerpt = _range_text(sentence_units, item.start_sentence_id, item.end_sentence_id)
        if _is_weak_text(excerpt):
            continue

        prelim.append(
            FinalClip(
                rank=item.rank,
                start_time=start_time,
                end_time=end_time,
                duration=duration,
                title=item.title,
                takeaway=item.takeaway,
                reason=item.reason,
                confidence_score=item.confidence,
                transcript_excerpt=excerpt,
                start_sentence_id=item.start_sentence_id,
                end_sentence_id=item.end_sentence_id,
            )
        )

    prelim.sort(key=lambda c: (_clip_score(c), -c.rank), reverse=True)

    deduped: list[FinalClip] = []
    for clip in prelim:
        too_similar = False
        for kept in deduped:
            if _overlap_ratio_seconds(clip, kept) >= MAX_OVERLAP_RATIO:
                too_similar = True
                break
        if not too_similar:
            deduped.append(clip)
        if len(deduped) >= MAX_CLIPS:
            break

    if len(deduped) < MIN_CLIPS:
        raise ValueError(
            "Could not produce enough high-quality clips after validation. "
            "Need at least 2 valid clips in the 35-90 second range."
        )

    # Normalize rank for stable final ordering.
    deduped.sort(key=lambda c: (_clip_score(c), c.start_time), reverse=True)
    final: list[FinalClip] = []
    for idx, clip in enumerate(deduped[:MAX_CLIPS], start=1):
        final.append(
            FinalClip(
                rank=idx,
                start_time=clip.start_time,
                end_time=clip.end_time,
                duration=clip.duration,
                title=clip.title,
                takeaway=clip.takeaway,
                reason=clip.reason,
                confidence_score=max(0.0, min(1.0, clip.confidence_score)),
                transcript_excerpt=clip.transcript_excerpt,
                start_sentence_id=clip.start_sentence_id,
                end_sentence_id=clip.end_sentence_id,
            )
        )
    return final

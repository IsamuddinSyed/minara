from __future__ import annotations

import logging
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from media_paths import clip_output_dir, preview_url_for, stable_clip_filename
from shortform_service import (
    ProcessedClipAsset,
    ShortformProcessingError,
    render_shortform_clip,
)
from subtitles_service import SubtitleWord
from video_source import SourceVideoAsset

logger = logging.getLogger(__name__)


class ClipGenerationSetupError(RuntimeError):
    """Raised when clip generation cannot start due to server setup."""


@dataclass(slots=True)
class ClipMomentSpec:
    rank: int
    start_time: float
    end_time: float
    title: str
    takeaway: str
    reason: str


@dataclass(slots=True)
class GeneratedClip:
    clip_id: str
    video_id: str
    start_time: float
    end_time: float
    duration: float
    title: str
    takeaway: str
    reason: str
    raw_file_path: str
    raw_preview_url: str
    preview_url: str
    processed_file_path: str | None = None
    processed_preview_url: str | None = None
    width: int | None = None
    height: int | None = None
    subtitle_file_path: str | None = None
    hook_headline: str | None = None


@dataclass(slots=True)
class ClipGenerationError:
    clip_id: str
    rank: int
    title: str
    detail: str


def _validate_clip_window(moment: ClipMomentSpec, source_duration: float | None) -> float:
    if not math.isfinite(moment.start_time) or not math.isfinite(moment.end_time):
        raise ValueError("Clip timestamps must be finite numbers.")
    if moment.start_time < 0:
        raise ValueError("Clip start_time must be non-negative.")
    if moment.end_time <= moment.start_time:
        raise ValueError("Clip end_time must be greater than start_time.")

    duration = moment.end_time - moment.start_time
    if duration <= 0:
        raise ValueError("Clip duration must be greater than zero.")

    if source_duration is not None and moment.end_time > (source_duration + 0.05):
        raise ValueError(
            f"Clip end_time {moment.end_time:.3f}s exceeds source duration {source_duration:.3f}s."
        )

    return duration


def _coerce_transcript_words(words: Sequence[object] | None) -> list[SubtitleWord]:
    normalized: list[SubtitleWord] = []
    if not words:
        return normalized

    for item in words:
        text = getattr(item, "text", None)
        if text is None:
            text = getattr(item, "word", None)
        start = getattr(item, "start", None)
        end = getattr(item, "end", None)
        if text is None or start is None or end is None:
            continue
        try:
            normalized.append(
                SubtitleWord(
                    text=str(text),
                    start=float(start),
                    end=float(end),
                )
            )
        except (TypeError, ValueError):
            continue
    return normalized


def _run_ffmpeg_clip(
    *,
    ffmpeg_bin: str,
    source_path: Path,
    output_path: Path,
    start_time: float,
    duration: float,
) -> None:
    proc = subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start_time:.3f}",
            "-i",
            str(source_path),
            "-t",
            f"{duration:.3f}",
            "-map",
            "0:v:0?",
            "-map",
            "0:a:0?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "ffmpeg exited with a non-zero status.")


def generate_clips(
    *,
    source_video: SourceVideoAsset,
    moments: Sequence[ClipMomentSpec],
    transcript_words: Sequence[SubtitleWord] | None = None,
) -> tuple[list[GeneratedClip], list[ClipGenerationError]]:
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise ClipGenerationSetupError("FFmpeg is not installed or not available on PATH.")

    clips: list[GeneratedClip] = []
    errors: list[ClipGenerationError] = []
    output_dir = clip_output_dir(source_video.video_id)
    normalized_words = _coerce_transcript_words(transcript_words)

    for index, moment in enumerate(moments, start=1):
        rank = moment.rank if moment.rank > 0 else index
        clip_id = f"{source_video.video_id}_{rank}"
        output_path = output_dir / stable_clip_filename(
            video_id=source_video.video_id,
            rank=rank,
            start_time=moment.start_time,
            end_time=moment.end_time,
        )
        try:
            duration = _validate_clip_window(moment, source_video.duration)
            _run_ffmpeg_clip(
                ffmpeg_bin=ffmpeg_bin,
                source_path=source_video.source_path,
                output_path=output_path,
                start_time=moment.start_time,
                duration=duration,
            )
            processed_asset: ProcessedClipAsset | None = None
            processing_detail: str | None = None
            if transcript_words is not None:
                try:
                    processed_asset = render_shortform_clip(
                        video_id=source_video.video_id,
                        rank=rank,
                        raw_clip_path=output_path,
                        start_time=moment.start_time,
                        end_time=moment.end_time,
                        transcript_words=normalized_words,
                        title=moment.title,
                        takeaway=moment.takeaway,
                        transcript_excerpt="",
                    )
                except ShortformProcessingError as exc:
                    processing_detail = str(exc)

            preview_url = (
                processed_asset.preview_url if processed_asset else preview_url_for(output_path)
            )
            logger.info(
                "Clip %s preview selection: %s",
                clip_id,
                "processed" if processed_asset else "raw",
            )
            clips.append(
                GeneratedClip(
                    clip_id=clip_id,
                    video_id=source_video.video_id,
                    start_time=moment.start_time,
                    end_time=moment.end_time,
                    duration=duration,
                    title=moment.title,
                    takeaway=moment.takeaway,
                    reason=moment.reason,
                    raw_file_path=str(output_path),
                    raw_preview_url=preview_url_for(output_path),
                    processed_file_path=processed_asset.file_path if processed_asset else None,
                    processed_preview_url=processed_asset.preview_url if processed_asset else None,
                    width=processed_asset.width if processed_asset else None,
                    height=processed_asset.height if processed_asset else None,
                    subtitle_file_path=(
                        processed_asset.subtitle_file_path if processed_asset else None
                    ),
                    hook_headline=processed_asset.hook_headline if processed_asset else None,
                    preview_url=preview_url,
                )
            )
            if processing_detail:
                errors.append(
                    ClipGenerationError(
                        clip_id=clip_id,
                        rank=rank,
                        title=moment.title,
                        detail=processing_detail,
                    )
                )
        except Exception as exc:
            output_path.unlink(missing_ok=True)
            errors.append(
                ClipGenerationError(
                    clip_id=clip_id,
                    rank=rank,
                    title=moment.title,
                    detail=str(exc),
                )
            )

    return clips, errors

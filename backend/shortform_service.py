from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from hook_service import derive_hook_headline
from media_paths import (
    preview_url_for,
    processed_clip_output_dir,
    stable_hook_filename,
    stable_processed_clip_filename,
    stable_subtitle_filename,
    subtitles_output_dir,
)
from render_container import RenderContainerError, host_media_path_to_container, run_in_render_container
from subtitles_service import (
    SubtitleCue,
    SubtitleWord,
    build_phrase_cues,
    words_for_clip,
    write_ass_subtitles,
)

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920

logger = logging.getLogger(__name__)


class ShortformProcessingError(RuntimeError):
    """Raised when a short-form render cannot be produced."""


@dataclass(slots=True)
class ProcessedClipAsset:
    file_path: str
    preview_url: str
    width: int
    height: int
    subtitle_file_path: str
    hook_headline: str | None = None


def _probe_dimensions(path: Path) -> tuple[int, int]:
    container_path = host_media_path_to_container(path)
    try:
        proc = run_in_render_container(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0:s=x",
                container_path,
            ]
        )
    except RenderContainerError as exc:
        raise ShortformProcessingError(str(exc)) from exc

    raw = proc.stdout.strip()
    try:
        width_str, height_str = raw.split("x", maxsplit=1)
        width = int(width_str)
        height = int(height_str)
    except Exception as exc:
        raise ShortformProcessingError("Could not parse clip dimensions from docker ffprobe.") from exc

    if width <= 0 or height <= 0:
        raise ShortformProcessingError("Clip dimensions must be positive.")
    return width, height


def _validate_processed_dimensions(path: Path) -> None:
    width, height = _probe_dimensions(path)
    if width != TARGET_WIDTH or height != TARGET_HEIGHT:
        raise ShortformProcessingError(
            f"Processed output must be {TARGET_WIDTH}x{TARGET_HEIGHT}, got {width}x{height}."
        )


def _escape_filter_path(path: str) -> str:
    return path.replace("\\", "\\\\").replace(":", r"\:")


def _build_hook_filter(hook_text_path: str) -> str:
    safe_path = _escape_filter_path(hook_text_path)
    return (
        "drawtext="
        f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        f"textfile='{safe_path}':"
        "reload=0:"
        "fontcolor=white:"
        "fontsize=78:"
        "line_spacing=8:"
        "x='if(lt(t,0.18),(w-text_w)/2+((0.18-t)/0.18)*90,if(lt(t,2.35),(w-text_w)/2,(w-text_w)/2+((t-2.35)/0.65)*260))':"
        "y='if(lt(t,0.18),150+((t/0.18)*40),if(lt(t,2.35),190,190-((t-2.35)/0.65)*60))':"
        "box=1:"
        "boxcolor=black@0.6:"
        "boxborderw=30:"
        "borderw=3:"
        "bordercolor=black@0.5:"
        "shadowx=0:"
        "shadowy=10:"
        "shadowcolor=black@0.22:"
        "alpha='if(lt(t,0.18),t/0.18,if(lt(t,2.35),1,max(0,(3-t)/0.65)))':"
        "enable='lt(t,3)'"
    )


def _build_video_filter(
    width: int,
    height: int,
    subtitle_path: str,
    hook_text_path: str | None,
) -> str:
    source_ratio = width / height
    target_ratio = TARGET_WIDTH / TARGET_HEIGHT

    if source_ratio > target_ratio:
        crop_height = height
        crop_width = int(round(height * target_ratio))
        crop_width = min(crop_width, width)
        crop_x = max(0, (width - crop_width) // 2)
        crop_y = 0
    else:
        crop_width = width
        crop_height = int(round(width / target_ratio))
        crop_height = min(crop_height, height)
        crop_x = 0
        crop_y = max(0, (height - crop_height) // 2)

    filters = (
        f"crop={crop_width}:{crop_height}:{crop_x}:{crop_y},"
        f"scale={TARGET_WIDTH}:{TARGET_HEIGHT},"
        "setsar=1,"
        f"subtitles='{_escape_filter_path(subtitle_path)}'"
    )
    if hook_text_path:
        filters += "," + _build_hook_filter(hook_text_path)
    return filters


def _run_shortform_render(
    *,
    raw_clip_path: Path,
    output_path: Path,
    video_filter: str,
) -> None:
    container_input = host_media_path_to_container(raw_clip_path)
    container_output = host_media_path_to_container(output_path)
    logger.info("Starting short-form render to %s", output_path)
    logger.info("Short-form FFmpeg filter graph: %s", video_filter)

    try:
        proc = run_in_render_container(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                container_input,
                "-vf",
                video_filter,
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
                container_output,
            ]
        )
    except RenderContainerError as exc:
        raise ShortformProcessingError(str(exc)) from exc

    if proc.returncode != 0:
        raise ShortformProcessingError(
            proc.stderr.strip() or "Docker FFmpeg short-form render failed."
        )
    if not output_path.exists():
        raise ShortformProcessingError("Render completed but processed output file was not created.")
    _validate_processed_dimensions(output_path)


def render_shortform_clip(
    *,
    video_id: str,
    rank: int,
    raw_clip_path: Path,
    start_time: float,
    end_time: float,
    transcript_words: Sequence[SubtitleWord],
    title: str,
    takeaway: str,
    transcript_excerpt: str = "",
) -> ProcessedClipAsset:
    if not raw_clip_path.exists():
        raise ShortformProcessingError(f"Raw clip file does not exist: {raw_clip_path}")
    if not transcript_words:
        raise ShortformProcessingError("Missing subtitle timing data for clip processing.")
    if not math.isfinite(start_time) or not math.isfinite(end_time) or end_time <= start_time:
        raise ShortformProcessingError("Invalid clip timestamps for short-form processing.")

    clip_words = words_for_clip(
        transcript_words,
        clip_start=start_time,
        clip_end=end_time,
    )
    if not clip_words:
        raise ShortformProcessingError("No transcript words were found for this clip range.")

    cues: list[SubtitleCue] = build_phrase_cues(clip_words)
    if not cues:
        raise ShortformProcessingError("Could not build subtitle phrases for this clip.")

    subtitles_dir = subtitles_output_dir(video_id)
    subtitle_path = subtitles_dir / stable_subtitle_filename(
        video_id=video_id,
        rank=rank,
        start_time=start_time,
        end_time=end_time,
    )
    try:
        write_ass_subtitles(subtitle_path, cues)
    except Exception as exc:
        raise ShortformProcessingError(f"Subtitle generation failed: {exc}") from exc
    logger.info("Generated subtitle file for clip render: %s", subtitle_path)

    hook_headline = derive_hook_headline(
        title=title,
        takeaway=takeaway,
        transcript_excerpt=transcript_excerpt,
    )
    hook_text_path: Path | None = None
    if hook_headline:
        hook_text_path = subtitles_dir / stable_hook_filename(
            video_id=video_id,
            rank=rank,
            start_time=start_time,
            end_time=end_time,
        )
        try:
            hook_text_path.write_text(hook_headline, encoding="utf-8")
        except Exception as exc:
            raise ShortformProcessingError(f"Hook generation failed: {exc}") from exc

    width, height = _probe_dimensions(raw_clip_path)
    output_dir = processed_clip_output_dir(video_id)
    output_path = output_dir / stable_processed_clip_filename(
        video_id=video_id,
        rank=rank,
        start_time=start_time,
        end_time=end_time,
    )

    try:
        container_subtitle_path = host_media_path_to_container(subtitle_path)
        container_hook_path = (
            host_media_path_to_container(hook_text_path) if hook_text_path else None
        )
        filter_graph = _build_video_filter(
            width,
            height,
            container_subtitle_path,
            container_hook_path,
        )
        _run_shortform_render(
            raw_clip_path=raw_clip_path,
            output_path=output_path,
            video_filter=filter_graph,
        )
    except Exception:
        output_path.unlink(missing_ok=True)
        raise

    return ProcessedClipAsset(
        file_path=str(output_path),
        preview_url=preview_url_for(output_path),
        width=TARGET_WIDTH,
        height=TARGET_HEIGHT,
        subtitle_file_path=str(subtitle_path),
        hook_headline=hook_headline,
    )

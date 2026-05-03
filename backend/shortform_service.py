from __future__ import annotations

import logging
import json
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
    # FFmpeg filter args use backslash escaping even inside quoted values.
    escaped = path.replace("\\", "\\\\")
    for char in ("'", ":", ",", ";", "[", "]"):
        escaped = escaped.replace(char, rf"\{char}")
    return escaped


def _split_hook_title(headline: str) -> tuple[str, str]:
    words = " ".join((headline or "").split()).split()
    if not words:
        return "", ""
    if len(words) <= 2:
        return "A reminder", " ".join(words)

    main_word_count = 1 if len(words[-1]) >= 6 else 2
    main_words = words[-main_word_count:]
    support_words = words[:-main_word_count]
    return " ".join(support_words), " ".join(main_words)


def _build_title_text_filter(
    *,
    text_path: str,
    font_size: int,
    font_color: str,
    y_expression: str,
) -> str:
    safe_path = _escape_filter_path(text_path)
    return (
        "drawtext="
        "font='Montserrat Bold':"
        f"textfile='{safe_path}':"
        "reload=0:"
        f"fontcolor={font_color}:"
        f"fontsize={font_size}:"
        "x='(w-text_w)/2':"
        f"y='if(lt(t,0.25),{y_expression}+((0.25-t)/0.25)*52,if(lt(t,2.58),{y_expression},{y_expression}-((t-2.58)/0.32)*52))':"
        "borderw=4:"
        "bordercolor=black@0.42:"
        "shadowx=0:"
        "shadowy=8:"
        "shadowcolor=black@0.28:"
        "alpha='if(lt(t,0.2),t/0.2,if(lt(t,2.58),1,max(0,(2.9-t)/0.32)))':"
        "enable='lt(t,3)'"
    )


def _build_hook_filter(support_text_path: str, main_text_path: str) -> str:
    support_filter = _build_title_text_filter(
        text_path=support_text_path,
        font_size=44,
        font_color="0xC9A84C",
        y_expression="h/3-100",
    )
    main_filter = _build_title_text_filter(
        text_path=main_text_path,
        font_size=90,
        font_color="0xC9A84C",
        y_expression="h/3-42",
    )
    return f"{support_filter},{main_filter}"


def _build_video_filter(
    width: int,
    height: int,
    subtitle_path: str,
    hook_text_paths: tuple[str, str] | None,
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
    if hook_text_paths:
        filters += "," + _build_hook_filter(*hook_text_paths)
    return filters


def _write_camera_timing_file(path: Path) -> None:
    path.write_text(
        json.dumps({"high_impact_ranges": []}, ensure_ascii=True),
        encoding="utf-8",
    )


def _run_face_tracking_camera(
    *,
    raw_clip_path: Path,
    output_path: Path,
    camera_timing_path: Path,
) -> None:
    container_input = host_media_path_to_container(raw_clip_path)
    container_output = host_media_path_to_container(output_path)
    container_timing = host_media_path_to_container(camera_timing_path)
    logger.info("Starting face-tracking camera pass to %s", output_path)

    try:
        proc = run_in_render_container(
            [
                "python3",
                "/opt/minara/face_track.py",
                "--input",
                container_input,
                "--output",
                container_output,
                "--high-impact-ranges",
                container_timing,
            ]
        )
    except RenderContainerError as exc:
        raise ShortformProcessingError(str(exc)) from exc

    if proc.returncode != 0:
        raise ShortformProcessingError(
            proc.stderr.strip() or "Face-tracking camera pass failed."
        )
    if not output_path.exists():
        raise ShortformProcessingError(
            "Face-tracking camera pass completed but no output file was created."
        )
    _validate_processed_dimensions(output_path)


def _run_shortform_render(
    *,
    raw_clip_path: Path,
    video_input_path: Path,
    output_path: Path,
    video_filter: str,
) -> None:
    container_video_input = host_media_path_to_container(video_input_path)
    container_audio_input = host_media_path_to_container(raw_clip_path)
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
                container_video_input,
                "-i",
                container_audio_input,
                "-vf",
                video_filter,
                "-map",
                "0:v:0",
                "-map",
                "1:a:0?",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-shortest",
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
    hook_support_text_path: Path | None = None
    hook_main_text_path: Path | None = None
    if hook_headline:
        hook_text_path = subtitles_dir / stable_hook_filename(
            video_id=video_id,
            rank=rank,
            start_time=start_time,
            end_time=end_time,
        )
        hook_support, hook_main = _split_hook_title(hook_headline)
        hook_support_text_path = hook_text_path.with_name(f"{hook_text_path.stem}_support.txt")
        hook_main_text_path = hook_text_path.with_name(f"{hook_text_path.stem}_main.txt")
        try:
            hook_text_path.write_text(hook_headline, encoding="utf-8")
            hook_support_text_path.write_text(hook_support, encoding="utf-8")
            hook_main_text_path.write_text(hook_main, encoding="utf-8")
        except Exception as exc:
            raise ShortformProcessingError(f"Hook generation failed: {exc}") from exc

    output_dir = processed_clip_output_dir(video_id)
    output_path = output_dir / stable_processed_clip_filename(
        video_id=video_id,
        rank=rank,
        start_time=start_time,
        end_time=end_time,
    )
    tracked_video_path = output_path.with_name(f"{output_path.stem}_camera.mp4")
    camera_timing_path = subtitle_path.with_name(f"{subtitle_path.stem}_camera.json")

    try:
        _write_camera_timing_file(camera_timing_path)
        _run_face_tracking_camera(
            raw_clip_path=raw_clip_path,
            output_path=tracked_video_path,
            camera_timing_path=camera_timing_path,
        )
        container_subtitle_path = host_media_path_to_container(subtitle_path)
        container_hook_paths = (
            (
                host_media_path_to_container(hook_support_text_path),
                host_media_path_to_container(hook_main_text_path),
            )
            if hook_support_text_path and hook_main_text_path
            else None
        )
        filter_graph = _build_video_filter(
            TARGET_WIDTH,
            TARGET_HEIGHT,
            container_subtitle_path,
            container_hook_paths,
        )
        _run_shortform_render(
            raw_clip_path=raw_clip_path,
            video_input_path=tracked_video_path,
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

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from media_paths import SOURCE_VIDEOS_DIR, ensure_media_directories, sanitize_path_component


class SourceVideoError(Exception):
    """Base exception for source-video resolution failures."""


class MissingSourceVideoError(SourceVideoError):
    """Raised when the requested source video cannot be located."""


class SourceVideoDownloadError(SourceVideoError):
    """Raised when source video download fails."""


@dataclass(slots=True)
class SourceVideoAsset:
    video_id: str
    title: str
    source_path: Path
    duration: float | None = None
    youtube_url: str | None = None


def _to_float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def probe_duration_seconds(path: Path) -> float | None:
    ffprobe_bin = shutil.which("ffprobe")
    if not ffprobe_bin:
        return None

    proc = subprocess.run(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None

    return _to_float_or_none(proc.stdout.strip())


def _find_existing_download(video_id: str) -> Path | None:
    matches = sorted(SOURCE_VIDEOS_DIR.glob(f"{video_id}.*"))
    for match in matches:
        if match.is_file():
            return match
    return None


def _fetch_youtube_info(youtube_url: str) -> dict[str, Any]:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
    except DownloadError as exc:
        raise SourceVideoDownloadError(
            f"Could not inspect YouTube video: {exc}"
        ) from exc
    except Exception as exc:
        raise SourceVideoDownloadError(
            f"Failed to inspect YouTube video: {exc}"
        ) from exc

    if not isinstance(info, dict):
        raise SourceVideoDownloadError("YouTube metadata lookup returned no video information.")
    return info


def _download_youtube_video(youtube_url: str, video_id: str) -> Path:
    ensure_media_directories()
    outtmpl = str(SOURCE_VIDEOS_DIR / f"{video_id}.%(ext)s")
    opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    try:
        with YoutubeDL(opts) as ydl:
            ydl.download([youtube_url])
    except DownloadError as exc:
        raise SourceVideoDownloadError(
            f"Could not download source video from YouTube: {exc}"
        ) from exc
    except Exception as exc:
        raise SourceVideoDownloadError(
            f"Source video download failed (is ffmpeg installed?): {exc}"
        ) from exc

    downloaded = _find_existing_download(video_id)
    if not downloaded:
        raise SourceVideoDownloadError("Download completed but no source video file was created.")
    return downloaded


def resolve_source_video(
    *,
    youtube_url: str | None = None,
    source_video_path: str | None = None,
    video_id: str | None = None,
) -> SourceVideoAsset:
    ensure_media_directories()

    if source_video_path:
        source_path = Path(source_video_path).expanduser().resolve()
        if not source_path.exists() or not source_path.is_file():
            raise MissingSourceVideoError(f"Source video does not exist: {source_path}")
        resolved_video_id = sanitize_path_component(video_id or source_path.stem, fallback="video")
        return SourceVideoAsset(
            video_id=resolved_video_id,
            title=source_path.stem,
            source_path=source_path,
            duration=probe_duration_seconds(source_path),
        )

    if not youtube_url or not youtube_url.strip():
        raise MissingSourceVideoError("Provide either youtube_url or source_video_path.")

    info = _fetch_youtube_info(youtube_url.strip())
    resolved_video_id = sanitize_path_component(str(info.get("id", "")).strip(), fallback="video")
    title = str(info.get("title") or resolved_video_id)
    duration = _to_float_or_none(info.get("duration"))

    existing = _find_existing_download(resolved_video_id)
    source_path = existing or _download_youtube_video(youtube_url.strip(), resolved_video_id)
    if duration is None:
        duration = probe_duration_seconds(source_path)

    return SourceVideoAsset(
        video_id=resolved_video_id,
        title=title,
        source_path=source_path,
        duration=duration,
        youtube_url=youtube_url.strip(),
    )

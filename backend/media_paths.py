from __future__ import annotations

import re
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
MEDIA_ROOT = BACKEND_DIR / "media"
SOURCE_VIDEOS_DIR = MEDIA_ROOT / "source-videos"
GENERATED_CLIPS_DIR = MEDIA_ROOT / "generated-clips"


def ensure_media_directories() -> None:
    SOURCE_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_CLIPS_DIR.mkdir(parents=True, exist_ok=True)


def sanitize_path_component(value: str, fallback: str = "item") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-.")
    return cleaned or fallback


def clip_output_dir(video_id: str) -> Path:
    directory = GENERATED_CLIPS_DIR / sanitize_path_component(video_id, fallback="video")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def stable_clip_filename(
    video_id: str,
    rank: int,
    start_time: float,
    end_time: float,
) -> str:
    start_ms = int(round(start_time * 1000))
    end_ms = int(round(end_time * 1000))
    safe_video_id = sanitize_path_component(video_id, fallback="video")
    return f"{safe_video_id}_{rank:02d}_{start_ms}_{end_ms}.mp4"


def preview_url_for(path: Path) -> str:
    relative = path.relative_to(MEDIA_ROOT)
    return f"/media/{relative.as_posix()}"

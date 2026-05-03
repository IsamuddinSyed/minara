from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np


TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
BASE_ZOOM = 1.15
PUNCH_ZOOM = 1.30
FOLLOW_LERP = 0.15
DEADZONE_WIDTH_RATIO = 0.0
EYE_Y_RATIO = 0.30
DRIFT_AMPLITUDE_PX = 5.0
DRIFT_FREQUENCY_HZ = 0.8


def _hash_noise(index: int, seed: int) -> float:
    value = (index * 374761393 + seed * 668265263) & 0xFFFFFFFF
    value = (value ^ (value >> 13)) * 1274126177
    value = (value ^ (value >> 16)) & 0xFFFFFFFF
    return (value / 0xFFFFFFFF) * 2.0 - 1.0


def _smooth_value_noise(value: float, seed: int) -> float:
    base = math.floor(value)
    fraction = value - base
    eased = fraction * fraction * (3.0 - 2.0 * fraction)
    left = _hash_noise(base, seed)
    right = _hash_noise(base + 1, seed)
    return left + (right - left) * eased


def _load_high_impact_ranges(path: Path | None) -> list[tuple[float, float]]:
    if not path or not path.exists():
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    ranges = payload.get("high_impact_ranges", []) if isinstance(payload, dict) else []
    normalized: list[tuple[float, float]] = []
    for item in ranges:
        if not isinstance(item, dict):
            continue
        try:
            start_time = float(item.get("start_time"))
            end_time = float(item.get("end_time"))
        except (TypeError, ValueError):
            continue
        if start_time >= 0 and end_time > start_time:
            normalized.append((start_time, end_time))
    return sorted(normalized)


def _zoom_for_time(frame_time: float, high_impact_ranges: list[tuple[float, float]]) -> float:
    for start_time, end_time in high_impact_ranges:
        if start_time <= frame_time <= end_time:
            return PUNCH_ZOOM
    return BASE_ZOOM


def _detect_eye_anchor(
    detector: mp.solutions.face_mesh.FaceMesh,
    frame_bgr,
) -> tuple[float, float] | None:
    height, width = frame_bgr.shape[:2]
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    results = detector.process(frame_rgb)
    if not results.multi_face_landmarks:
        return None

    landmarks = results.multi_face_landmarks[0].landmark
    left_eye = landmarks[33]
    right_eye = landmarks[263]
    nose_tip = landmarks[1]
    return (
        ((left_eye.x + right_eye.x) * 0.5) * width,
        ((left_eye.y + right_eye.y + nose_tip.y) / 3.0) * height,
    )


def _probe_initial_detection(
    capture: cv2.VideoCapture,
    detector: mp.solutions.face_mesh.FaceMesh,
) -> None:
    original_position = capture.get(cv2.CAP_PROP_POS_FRAMES)
    detections: list[tuple[int, tuple[float, float] | None]] = []

    for test_frame_index in (0, 30, 60):
        capture.set(cv2.CAP_PROP_POS_FRAMES, test_frame_index)
        ok, frame = capture.read()
        anchor = _detect_eye_anchor(detector, frame) if ok else None
        detections.append((test_frame_index, anchor))
        print(
            f"Test frame {test_frame_index}: detection {anchor}",
            file=sys.stderr,
            flush=True,
        )

    if all(anchor is None for _, anchor in detections):
        print(
            "WARNING: Face detector returned no results on first 3 test frames. "
            "Check input video format or lighting conditions.",
            file=sys.stderr,
            flush=True,
        )

    capture.set(cv2.CAP_PROP_POS_FRAMES, original_position)


def _resize_cover(frame, scale: float):
    height, width = frame.shape[:2]
    scaled_width = max(TARGET_WIDTH, int(round(width * scale)))
    scaled_height = max(TARGET_HEIGHT, int(round(height * scale)))
    return cv2.resize(frame, (scaled_width, scaled_height), interpolation=cv2.INTER_LINEAR)


def _crop_with_camera(frame, anchor: tuple[float, float], zoom: float, frame_time: float):
    height, width = frame.shape[:2]
    cover_scale = max(TARGET_WIDTH / width, TARGET_HEIGHT / height)
    scale = cover_scale * zoom
    resized = _resize_cover(frame, scale)
    resized_height, resized_width = resized.shape[:2]

    anchor_x = anchor[0] * scale
    anchor_y = anchor[1] * scale
    drift_x = DRIFT_AMPLITUDE_PX * _smooth_value_noise(
        frame_time * DRIFT_FREQUENCY_HZ,
        seed=17,
    )
    drift_y = DRIFT_AMPLITUDE_PX * _smooth_value_noise(
        frame_time * DRIFT_FREQUENCY_HZ,
        seed=43,
    )

    crop_x = anchor_x - (TARGET_WIDTH * 0.5) + drift_x
    crop_y = anchor_y - (TARGET_HEIGHT * EYE_Y_RATIO) + drift_y
    max_x = max(0, resized_width - TARGET_WIDTH)
    max_y = max(0, resized_height - TARGET_HEIGHT)
    crop_x = int(round(min(max(crop_x, 0), max_x)))
    crop_y = int(round(min(max(crop_y, 0), max_y)))
    return resized[crop_y : crop_y + TARGET_HEIGHT, crop_x : crop_x + TARGET_WIDTH]


def _open_ffmpeg_writer(output_path: Path, fps: float) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{TARGET_WIDTH}x{TARGET_HEIGHT}",
            "-r",
            f"{fps:.6f}",
            "-i",
            "-",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def process_video(
    input_path: Path,
    output_path: Path,
    high_impact_ranges_path: Path | None,
) -> None:
    capture = cv2.VideoCapture(str(input_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open input video: {input_path}")

    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    high_impact_ranges = _load_high_impact_ranges(high_impact_ranges_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = _open_ffmpeg_writer(output_path, fps)
    if writer.stdin is None:
        capture.release()
        raise RuntimeError("Could not open FFmpeg stdin for face-tracking output.")

    smoothed_anchor: tuple[float, float] | None = None
    last_anchor: tuple[float, float] | None = None
    frame_index = 0
    detection_window_hits = 0

    with mp.solutions.face_mesh.FaceMesh(
        static_image_mode=False,
        max_num_faces=1,
        refine_landmarks=False,
        min_detection_confidence=0.4,
        min_tracking_confidence=0.4,
    ) as detector:
        _probe_initial_detection(capture, detector)
        while True:
            ok, frame = capture.read()
            if not ok:
                break

            height, width = frame.shape[:2]

            detected_anchor = _detect_eye_anchor(detector, frame)
            if detected_anchor is not None:
                detection_window_hits += 1
                last_anchor = detected_anchor
            elif last_anchor is None:
                last_anchor = (width * 0.5, height * EYE_Y_RATIO)

            if smoothed_anchor is None:
                smoothed_anchor = last_anchor
            else:
                dx = last_anchor[0] - smoothed_anchor[0]
                dy = last_anchor[1] - smoothed_anchor[1]
                smoothed_anchor = (
                    smoothed_anchor[0] + dx * FOLLOW_LERP,
                    smoothed_anchor[1] + dy * FOLLOW_LERP,
                )

            frame_time = frame_index / fps
            zoom = _zoom_for_time(frame_time, high_impact_ranges)
            output_frame = _crop_with_camera(frame, smoothed_anchor, zoom, frame_time)
            writer.stdin.write(np.ascontiguousarray(output_frame).tobytes())
            frame_index += 1
            if frame_index % 30 == 0:
                print(
                    f"Frame {frame_index}: detection {detection_window_hits}/30 frames",
                    file=sys.stderr,
                    flush=True,
                )
                detection_window_hits = 0

    capture.release()
    writer.stdin.close()
    stderr = writer.stderr.read().decode("utf-8", errors="replace") if writer.stderr else ""
    return_code = writer.wait()
    if return_code != 0:
        raise RuntimeError(stderr.strip() or "FFmpeg failed to encode face-tracked video.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply Minara face-tracking camera motion.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--high-impact-ranges")
    args = parser.parse_args()

    high_impact_ranges_path = (
        Path(args.high_impact_ranges) if args.high_impact_ranges else None
    )
    process_video(Path(args.input), Path(args.output), high_impact_ranges_path)


if __name__ == "__main__":
    main()

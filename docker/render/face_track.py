from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np


TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
MIN_ZOOM = 1.0
MAX_ZOOM = 1.14
PUNCH_ZOOM_BOOST = 1.04
TARGET_FACE_HEIGHT_RATIO = 0.15
HEADROOM_Y_RATIO = 1.0 / 3.0
HEAD_TOP_PADDING_RATIO = 0.45
FOLLOW_LERP_X = 0.08
FOLLOW_LERP_Y = 0.045
ZOOM_LERP = 0.06
HORIZONTAL_DEADZONE_RATIO = 0.018
MAX_HORIZONTAL_MOVE_RATIO = 0.018
VERTICAL_DEADZONE_RATIO = 0.035
MAX_VERTICAL_MOVE_RATIO = 0.008
DRIFT_X_AMPLITUDE_PX = 0.0
DRIFT_Y_AMPLITUDE_PX = 1.5
DRIFT_FREQUENCY_HZ = 0.8


@dataclass(slots=True)
class FaceTarget:
    center_x: float
    head_top_y: float
    face_height: float


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


def _is_high_impact_time(frame_time: float, high_impact_ranges: list[tuple[float, float]]) -> bool:
    for start_time, end_time in high_impact_ranges:
        if start_time <= frame_time <= end_time:
            return True
    return False


def _target_zoom_for_face(
    *,
    frame_width: int,
    frame_height: int,
    face_height: float,
    high_impact: bool,
) -> float:
    if face_height <= 0:
        return MIN_ZOOM

    cover_scale = max(TARGET_WIDTH / frame_width, TARGET_HEIGHT / frame_height)
    desired_zoom = (TARGET_HEIGHT * TARGET_FACE_HEIGHT_RATIO) / (face_height * cover_scale)
    if high_impact:
        desired_zoom *= PUNCH_ZOOM_BOOST
    return min(MAX_ZOOM, max(MIN_ZOOM, desired_zoom))


def _detect_eye_anchor(
    detector: mp.solutions.face_mesh.FaceMesh,
    frame_bgr,
) -> FaceTarget | None:
    height, width = frame_bgr.shape[:2]
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    results = detector.process(frame_rgb)
    if not results.multi_face_landmarks:
        return None

    landmarks = results.multi_face_landmarks[0].landmark
    left_eye = landmarks[33]
    right_eye = landmarks[263]
    ys = [landmark.y for landmark in landmarks]
    face_top_y = max(0.0, min(ys) * height)
    face_bottom_y = min(float(height), max(ys) * height)
    face_height = max(1.0, face_bottom_y - face_top_y)
    head_top_y = max(0.0, face_top_y - (face_height * HEAD_TOP_PADDING_RATIO))
    return FaceTarget(
        center_x=((left_eye.x + right_eye.x) * 0.5) * width,
        head_top_y=head_top_y,
        face_height=face_height,
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


def _crop_with_camera(frame, target: FaceTarget, zoom: float, frame_time: float):
    height, width = frame.shape[:2]
    cover_scale = max(TARGET_WIDTH / width, TARGET_HEIGHT / height)
    scale = cover_scale * zoom
    resized = _resize_cover(frame, scale)
    resized_height, resized_width = resized.shape[:2]

    anchor_x = target.center_x * scale
    head_top_y = target.head_top_y * scale
    drift_x = DRIFT_X_AMPLITUDE_PX * _smooth_value_noise(
        frame_time * DRIFT_FREQUENCY_HZ,
        seed=17,
    )
    drift_y = DRIFT_Y_AMPLITUDE_PX * _smooth_value_noise(
        frame_time * DRIFT_FREQUENCY_HZ,
        seed=43,
    )

    crop_x = anchor_x - (TARGET_WIDTH * 0.5) + drift_x
    crop_y = head_top_y - (TARGET_HEIGHT * HEADROOM_Y_RATIO) + drift_y
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

    smoothed_target: FaceTarget | None = None
    last_target: FaceTarget | None = None
    smoothed_zoom: float | None = None
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

            detected_target = _detect_eye_anchor(detector, frame)
            if detected_target is not None:
                detection_window_hits += 1
                last_target = detected_target
            elif last_target is None:
                last_target = FaceTarget(
                    center_x=width * 0.5,
                    head_top_y=height * HEADROOM_Y_RATIO,
                    face_height=height * 0.18,
                )

            if smoothed_target is None:
                smoothed_target = last_target
            else:
                dx = last_target.center_x - smoothed_target.center_x
                if abs(dx) < width * HORIZONTAL_DEADZONE_RATIO:
                    dx = 0.0
                else:
                    max_horizontal_move = width * MAX_HORIZONTAL_MOVE_RATIO
                    dx = max(-max_horizontal_move, min(max_horizontal_move, dx))

                dy = last_target.head_top_y - smoothed_target.head_top_y
                if abs(dy) < height * VERTICAL_DEADZONE_RATIO:
                    dy = 0.0
                else:
                    max_vertical_move = height * MAX_VERTICAL_MOVE_RATIO
                    dy = max(-max_vertical_move, min(max_vertical_move, dy))
                smoothed_target = FaceTarget(
                    center_x=smoothed_target.center_x + dx * FOLLOW_LERP_X,
                    head_top_y=smoothed_target.head_top_y + dy * FOLLOW_LERP_Y,
                    face_height=(
                        smoothed_target.face_height
                        + (last_target.face_height - smoothed_target.face_height) * ZOOM_LERP
                    ),
                )

            frame_time = frame_index / fps
            target_zoom = _target_zoom_for_face(
                frame_width=width,
                frame_height=height,
                face_height=smoothed_target.face_height,
                high_impact=_is_high_impact_time(frame_time, high_impact_ranges),
            )
            if smoothed_zoom is None:
                smoothed_zoom = target_zoom
            else:
                smoothed_zoom += (target_zoom - smoothed_zoom) * ZOOM_LERP
            output_frame = _crop_with_camera(frame, smoothed_target, smoothed_zoom, frame_time)
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

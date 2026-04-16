#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"
docker compose -f docker-compose.yml run --rm -T render sh -lc 'ffmpeg -version && ffprobe -version && ffmpeg -filters | grep subtitles'

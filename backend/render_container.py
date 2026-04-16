from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Sequence

from media_paths import MEDIA_ROOT


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCKER_COMPOSE_FILE = PROJECT_ROOT / "docker-compose.yml"
RENDER_SERVICE = "render"
CONTAINER_MEDIA_ROOT = Path("/workspace/media")


class RenderContainerError(RuntimeError):
    """Raised when the Docker render environment cannot be used."""


def _docker_binary() -> str:
    docker_bin = shutil.which("docker")
    if not docker_bin:
        raise RenderContainerError("Docker is not installed or not available on PATH.")
    return docker_bin


def host_media_path_to_container(path: Path) -> str:
    resolved = path.resolve()
    media_root = MEDIA_ROOT.resolve()
    try:
        relative = resolved.relative_to(media_root)
    except ValueError as exc:
        raise RenderContainerError(
            f"Path is outside the shared media directory: {resolved}"
        ) from exc
    return str(CONTAINER_MEDIA_ROOT / relative)


def run_in_render_container(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    docker_bin = _docker_binary()
    if not DOCKER_COMPOSE_FILE.exists():
        raise RenderContainerError(
            f"Docker compose file is missing: {DOCKER_COMPOSE_FILE}"
        )

    proc = subprocess.run(
        [
            docker_bin,
            "compose",
            "-f",
            str(DOCKER_COMPOSE_FILE),
            "run",
            "--rm",
            "-T",
            RENDER_SERVICE,
            *args,
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(PROJECT_ROOT),
    )

    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        if "Cannot connect to the Docker daemon" in stderr:
            raise RenderContainerError("Docker is installed but the Docker daemon is not running.")
        if "No such service" in stderr:
            raise RenderContainerError("Docker render service is not available in docker-compose.yml.")
        if "pull access denied" in stderr or "not found" in stderr:
            raise RenderContainerError(
                "Render image is not available yet. Build it with scripts/render-build.sh first."
            )
        raise RenderContainerError(stderr or "Docker render command failed.")

    return proc

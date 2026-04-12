import os
import shutil
import tempfile
from pathlib import Path

import assemblyai as aai
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

_BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(_BACKEND_DIR / ".env")

YOUTUBE_HINTS = (
    "youtube.com/",
    "youtu.be/",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
)

app = FastAPI(title="Minara API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TranscribeRequest(BaseModel):
    youtube_url: str = Field(..., min_length=1)

    @field_validator("youtube_url")
    @classmethod
    def youtube_url_must_look_valid(cls, v: str) -> str:
        s = v.strip()
        if not any(h in s for h in YOUTUBE_HINTS):
            raise ValueError("URL must be a YouTube link")
        return s


def download_youtube_audio(url: str) -> tuple[Path, str]:
    """Download best audio as m4a. Returns (audio_path, tmpdir). Caller must delete tmpdir."""
    tmpdir = tempfile.mkdtemp(prefix="minara_audio_")
    outtmpl = str(Path(tmpdir) / "audio.%(ext)s")
    opts: dict = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
                "preferredquality": "192",
            }
        ],
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    try:
        with YoutubeDL(opts) as ydl:
            ydl.download([url])
    except DownloadError as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(
            status_code=502,
            detail=f"Could not download audio from YouTube: {e}",
        ) from e
    except Exception as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(
            status_code=502,
            detail=f"Download failed (is ffmpeg installed?): {e}",
        ) from e

    for name in os.listdir(tmpdir):
        if name.endswith(".m4a"):
            return Path(tmpdir) / name, tmpdir

    shutil.rmtree(tmpdir, ignore_errors=True)
    raise HTTPException(
        status_code=500,
        detail="Download finished but no .m4a file was produced.",
    )


def _language_to_str(code) -> str:
    if code is None:
        return ""
    if hasattr(code, "value"):
        return str(code.value)
    return str(code)


def assemblyai_transcript_to_openai_shape(transcript: aai.Transcript) -> dict:
    """
    Map AssemblyAI result to the same JSON shape the OpenAI verbose_json + words
    path produced (task, language, duration, text, words, segments).
    Word start/end are in seconds (AssemblyAI uses milliseconds).
    """
    if transcript.status == aai.TranscriptStatus.error:
        raise HTTPException(
            status_code=500,
            detail=transcript.error or "AssemblyAI transcription failed",
        )

    words_out: list[dict] = []
    for w in transcript.words or []:
        words_out.append(
            {
                "word": w.text,
                "start": w.start / 1000.0,
                "end": w.end / 1000.0,
            }
        )

    duration = transcript.audio_duration
    duration_f = float(duration) if duration is not None else 0.0

    return {
        "task": "transcribe",
        "language": _language_to_str(transcript.language_code),
        "duration": duration_f,
        "text": transcript.text or "",
        "words": words_out,
        "segments": [],
    }


@app.post("/transcribe")
def transcribe(body: TranscribeRequest):
    api_key = os.getenv("ASSEMBLYAI_API_KEY")
    if not api_key or not api_key.strip():
        raise HTTPException(
            status_code=500,
            detail=(
                "ASSEMBLYAI_API_KEY is missing or empty. Set it in backend/.env "
                "(same folder as main.py), then restart the API server."
            ),
        )

    audio_path: Path | None = None
    tmpdir: str | None = None
    try:
        audio_path, tmpdir = download_youtube_audio(body.youtube_url)

        aai.settings.api_key = api_key.strip()
        config = aai.TranscriptionConfig(
            speech_models=["universal-3-pro", "universal-2"],
        )
        transcript = aai.Transcriber().transcribe(str(audio_path), config=config)
        return assemblyai_transcript_to_openai_shape(transcript)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Transcription failed: {e}",
        ) from e
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)

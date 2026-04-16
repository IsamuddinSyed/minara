import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional

import assemblyai as aai
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel, Field, field_validator, model_validator
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
from clip_service import (
    ClipGenerationSetupError,
    ClipMomentSpec,
    generate_clips,
)
from media_paths import MEDIA_ROOT, ensure_media_directories
from moments_llm import select_candidate_sentence_ranges
from moments_preprocess import build_sentence_units
from moments_prompt import IDENTIFY_MOMENTS_SYSTEM, build_candidate_reasoning_input
from moments_validate import validate_and_build_final_clips
from video_source import (
    MissingSourceVideoError,
    SourceVideoDownloadError,
    resolve_source_video,
)

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
ensure_media_directories()
app.mount("/media", StaticFiles(directory=str(MEDIA_ROOT)), name="media")

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


class WordSpan(BaseModel):
    word: str
    start: float
    end: float


class TranscriptIn(BaseModel):
    """Same shape as POST /transcribe response; extras are ignored for prompting."""

    text: str
    words: list[WordSpan] = Field(default_factory=list)
    task: Optional[str] = None
    language: Optional[str] = None
    duration: Optional[float] = None
    segments: Optional[list[Any]] = None

    @model_validator(mode="after")
    def transcript_must_have_content(self) -> "TranscriptIn":
        if not self.text or not self.text.strip():
            raise ValueError("text must not be empty")
        if not self.words:
            raise ValueError("words must not be empty for moment alignment")
        return self


class Clip(BaseModel):
    start_time: float
    end_time: float
    duration: float
    title: str
    takeaway: str
    reason: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    transcript_excerpt: str


class MomentsResponse(BaseModel):
    clips: list[Clip] = Field(min_length=2, max_length=5)


class ClipGenerationMomentIn(BaseModel):
    rank: int | None = None
    start_time: float
    end_time: float
    title: str
    takeaway: str
    reason: str

    @field_validator("title", "takeaway", "reason")
    @classmethod
    def text_fields_must_not_be_blank(cls, v: str) -> str:
        text = v.strip()
        if not text:
            raise ValueError("Text fields must not be empty")
        return text


class GenerateClipsRequest(BaseModel):
    youtube_url: Optional[str] = None
    source_video_path: Optional[str] = None
    video_id: Optional[str] = None
    moments: list[ClipGenerationMomentIn] = Field(default_factory=list)
    transcript_words: list[WordSpan] = Field(default_factory=list)

    @model_validator(mode="after")
    def request_must_have_source_and_moments(self) -> "GenerateClipsRequest":
        if not self.youtube_url and not self.source_video_path:
            raise ValueError("Provide youtube_url or source_video_path.")
        if not self.moments:
            raise ValueError("moments must contain at least one clip range.")
        return self


class GeneratedClipOut(BaseModel):
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
    processed_file_path: Optional[str] = None
    processed_preview_url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    subtitle_file_path: Optional[str] = None
    hook_headline: Optional[str] = None
    preview_url: str


class ClipGenerationErrorOut(BaseModel):
    clip_id: str
    rank: int
    title: str
    detail: str


class GenerateClipsResponse(BaseModel):
    video_id: str
    source_title: str
    source_video_path: str
    source_duration: Optional[float] = None
    clips: list[GeneratedClipOut] = Field(default_factory=list)
    errors: list[ClipGenerationErrorOut] = Field(default_factory=list)


@app.post("/identify-moments")
def identify_moments(body: TranscriptIn):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or not api_key.strip():
        raise HTTPException(
            status_code=500,
            detail=(
                "OPENAI_API_KEY is missing or empty. Set it in backend/.env "
                "(same folder as main.py), then restart the API server."
            ),
        )

    try:
        sentence_units = build_sentence_units(body.words)
        if len(sentence_units) < 3:
            raise HTTPException(
                status_code=422,
                detail="Transcript could not be segmented into enough sentence units.",
            )

        user_message = build_candidate_reasoning_input(
            sentence_units=sentence_units,
            meta={"language": body.language, "duration": body.duration},
        )
        client = OpenAI(api_key=api_key.strip())
        candidates = select_candidate_sentence_ranges(
            client=client,
            model="gpt-4o",
            system_prompt=IDENTIFY_MOMENTS_SYSTEM,
            user_message=user_message,
        )
        final_clips = validate_and_build_final_clips(candidates, sentence_units)
        payload = {
            "clips": [
                {
                    "start_time": clip.start_time,
                    "end_time": clip.end_time,
                    "duration": clip.duration,
                    "title": clip.title,
                    "takeaway": clip.takeaway,
                    "reason": clip.reason,
                    "confidence_score": clip.confidence_score,
                    "transcript_excerpt": clip.transcript_excerpt,
                }
                for clip in final_clips
            ]
        }
        validated = MomentsResponse.model_validate(payload)
        return validated.model_dump(mode="json")
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Invalid clip selection: {e}") from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Key moment identification failed: {e}",
        ) from e


@app.post("/generate-clips")
def generate_clips_endpoint(body: GenerateClipsRequest):
    try:
        source_video = resolve_source_video(
            youtube_url=body.youtube_url,
            source_video_path=body.source_video_path,
            video_id=body.video_id,
        )
        moments = [
            ClipMomentSpec(
                rank=item.rank or index,
                start_time=item.start_time,
                end_time=item.end_time,
                title=item.title,
                takeaway=item.takeaway,
                reason=item.reason,
            )
            for index, item in enumerate(body.moments, start=1)
        ]
        generated_clips, generation_errors = generate_clips(
            source_video=source_video,
            moments=moments,
            transcript_words=body.transcript_words,
        )
        payload = {
            "video_id": source_video.video_id,
            "source_title": source_video.title,
            "source_video_path": str(source_video.source_path),
            "source_duration": source_video.duration,
            "clips": [
                {
                    "clip_id": clip.clip_id,
                    "video_id": clip.video_id,
                    "start_time": clip.start_time,
                    "end_time": clip.end_time,
                    "duration": clip.duration,
                    "title": clip.title,
                    "takeaway": clip.takeaway,
                    "reason": clip.reason,
                    "raw_file_path": clip.raw_file_path,
                    "raw_preview_url": clip.raw_preview_url,
                    "processed_file_path": clip.processed_file_path,
                    "processed_preview_url": clip.processed_preview_url,
                    "width": clip.width,
                    "height": clip.height,
                    "subtitle_file_path": clip.subtitle_file_path,
                    "hook_headline": clip.hook_headline,
                    "preview_url": clip.preview_url,
                }
                for clip in generated_clips
            ],
            "errors": [
                {
                    "clip_id": err.clip_id,
                    "rank": err.rank,
                    "title": err.title,
                    "detail": err.detail,
                }
                for err in generation_errors
            ],
        }
        validated = GenerateClipsResponse.model_validate(payload)
        return validated.model_dump(mode="json")
    except MissingSourceVideoError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except SourceVideoDownloadError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except ClipGenerationSetupError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Clip generation failed: {e}",
        ) from e


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

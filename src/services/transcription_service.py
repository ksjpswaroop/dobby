"""
Local speech-to-text (OW row 48 — Next Task 8).

Audio is the most private material a user has, so this never leaves the
machine. Three backends are tried in order, and whichever is present is used:

1. **whisper.cpp** (`whisper-cli`) — a compiled binary with Metal/CUDA support.
   Fast, and the one most likely to already be installed via Homebrew.
2. **faster-whisper** — the Python package, if importable.
3. Nothing — an honest error naming exactly what to install.

Models are GGML `.bin` files kept in `~/.dobby/models/whisper/`. They are a
network download, so fetching one goes through the approval gate like any other
outbound action: the app does not quietly pull 140 MB because a page was opened.

`ffmpeg` converts whatever the user has into the 16 kHz mono WAV whisper wants.
Without it only WAV input works, which is stated rather than discovered.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

MODEL_DIR = Path.home() / ".dobby" / "models" / "whisper"
MAX_AUDIO_BYTES = 200 * 1024 * 1024
TRANSCRIBE_TIMEOUT = 1800          # 30 min; long recordings are the point

AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".mp4", ".aac", ".flac", ".ogg",
                  ".opus", ".webm", ".mov", ".mkv"}

# ggml models, smallest first. Sizes are the real download sizes.
MODELS = [
    {"id": "tiny.en", "size_mb": 75, "blurb": "Fastest. English only. Good for clean speech."},
    {"id": "base.en", "size_mb": 142, "blurb": "Recommended. English only, noticeably better."},
    {"id": "small.en", "size_mb": 466, "blurb": "Slower, more accurate English."},
    {"id": "base", "size_mb": 142, "blurb": "Multilingual, base quality."},
    {"id": "small", "size_mb": 466, "blurb": "Multilingual, better quality."},
]

_HF_BASE = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"


class TranscriptionError(Exception):
    """Message is user-facing."""


@dataclass
class Segment:
    start: float
    end: float
    text: str

    def to_dict(self) -> Dict[str, Any]:
        return {"start": self.start, "end": self.end, "text": self.text}


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
def _whisper_cli() -> Optional[str]:
    for name in ("whisper-cli", "whisper-cpp", "main"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _has_faster_whisper() -> bool:
    try:
        import faster_whisper  # noqa: F401

        return True
    except ImportError:
        return False


def installed_models() -> List[Dict[str, Any]]:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for path in sorted(MODEL_DIR.glob("ggml-*.bin")):
        model_id = path.stem.replace("ggml-", "")
        out.append({"id": model_id, "path": str(path),
                    "size_mb": round(path.stat().st_size / 1_048_576)})
    return out


def capabilities() -> Dict[str, Any]:
    """What is actually available, so the UI can say so before the user tries."""
    cli = _whisper_cli()
    models = installed_models()
    return {
        "whisper_cli": cli,
        "faster_whisper": _has_faster_whisper(),
        "ffmpeg": shutil.which("ffmpeg"),
        "models": models,
        "available_models": MODELS,
        "ready": bool((cli or _has_faster_whisper()) and models),
        "reason": _readiness_reason(cli, models),
    }


def _readiness_reason(cli: Optional[str], models: List[Dict[str, Any]]) -> str:
    if not cli and not _has_faster_whisper():
        return ("No transcription engine found. Install whisper.cpp "
                "(`brew install whisper-cpp`) or `pip install faster-whisper`.")
    if not models:
        return "No speech model downloaded yet. Pick one below to get started."
    return ""


# ---------------------------------------------------------------------------
# Model download
# ---------------------------------------------------------------------------
async def download_model(db, project_id: str, model_id: str,
                         skip_approval: bool = False) -> Dict[str, Any]:
    """Fetch a GGML model, with consent — it is a real network download."""
    spec = next((m for m in MODELS if m["id"] == model_id), None)
    if not spec:
        raise TranscriptionError(
            f"Unknown model. Choose one of: {', '.join(m['id'] for m in MODELS)}"
        )

    target = MODEL_DIR / f"ggml-{model_id}.bin"
    if target.exists():
        return {"downloaded": True, "cached": True, "path": str(target)}

    if not skip_approval:
        from src.services import inbox_service as inbox

        verdict = await inbox.require(
            db, project_id, "net.fetch", "huggingface.co",
            title=f"Download the {model_id} speech model?",
            detail=(f"{spec['size_mb']} MB from huggingface.co, stored in "
                    f"{MODEL_DIR}. Once downloaded, transcription runs entirely "
                    "on this machine — no audio ever leaves it."),
            risk="medium", source="transcription", timeout=180,
        )
        if not verdict["allowed"]:
            return {"downloaded": False, "reason": verdict["reason"],
                    "ask_id": verdict.get("ask_id")}

    import httpx

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    url = f"{_HF_BASE}/ggml-{model_id}.bin"
    # Download to a temp name so an interrupted fetch never looks like a
    # complete model on the next run.
    partial = target.with_suffix(".partial")
    try:
        async with httpx.AsyncClient(timeout=None, follow_redirects=True) as c:
            async with c.stream("GET", url) as r:
                r.raise_for_status()
                with partial.open("wb") as f:
                    async for chunk in r.aiter_bytes(1024 * 256):
                        f.write(chunk)
        partial.rename(target)
    except Exception as e:
        partial.unlink(missing_ok=True)
        raise TranscriptionError(f"Could not download {model_id}: {e}")

    logger.info("whisper_model_downloaded", model=model_id,
                mb=round(target.stat().st_size / 1_048_576))
    return {"downloaded": True, "cached": False, "path": str(target),
            "size_mb": round(target.stat().st_size / 1_048_576)}


def delete_model(model_id: str) -> bool:
    target = MODEL_DIR / f"ggml-{model_id}.bin"
    if not target.exists():
        return False
    target.unlink()
    return True


# ---------------------------------------------------------------------------
# Audio preparation
# ---------------------------------------------------------------------------
def _to_wav(source: Path) -> Path:
    """16 kHz mono WAV — what every whisper build expects."""
    if source.suffix.lower() == ".wav":
        return source
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise TranscriptionError(
            f"Converting {source.suffix} needs ffmpeg (`brew install ffmpeg`). "
            "WAV files work without it."
        )
    out = source.with_suffix(".converted.wav")
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", str(source), "-ar", "16000", "-ac", "1",
             "-c:a", "pcm_s16le", str(out)],
            capture_output=True, timeout=600, check=True,
        )
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or b"").decode(errors="replace")[-300:]
        raise TranscriptionError(f"ffmpeg could not read that file. {detail}")
    except subprocess.TimeoutExpired:
        raise TranscriptionError("Converting the audio took too long.")
    return out


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------
_TIMESTAMP = re.compile(
    r"\[(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})\.(\d{3})\]\s*(.*)"
)


def _parse_cli_output(text: str) -> List[Segment]:
    segments: List[Segment] = []
    for line in text.splitlines():
        m = _TIMESTAMP.match(line.strip())
        if not m:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2, body = m.groups()
        start = int(h1) * 3600 + int(m1) * 60 + int(s1) + int(ms1) / 1000
        end = int(h2) * 3600 + int(m2) * 60 + int(s2) + int(ms2) / 1000
        body = body.strip()
        if body:
            segments.append(Segment(start, end, body))
    return segments


async def _run_cli(cli: str, model: Path, wav: Path,
                   language: str = "") -> List[Segment]:
    # `-np` suppresses the progress banner; timestamps stay on so the output
    # can be split into segments rather than one undifferentiated block.
    args = [cli, "-m", str(model), "-f", str(wav), "-np"]
    if language:
        args += ["-l", language]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(),
                                                timeout=TRANSCRIBE_TIMEOUT)
    except asyncio.TimeoutError:
        raise TranscriptionError("Transcription took too long and was stopped.")
    except OSError as e:
        raise TranscriptionError(f"Could not run the transcription engine: {e}")

    if proc.returncode != 0:
        detail = (stderr or b"").decode(errors="replace")[-400:]
        raise TranscriptionError(f"Transcription failed. {detail}")
    return _parse_cli_output((stdout or b"").decode(errors="replace"))


def _run_faster_whisper(model_id: str, wav: Path, language: str = "") -> List[Segment]:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_id.replace(".en", ""), device="auto",
                         compute_type="int8")
    segments, _ = model.transcribe(str(wav), language=language or None)
    return [Segment(s.start, s.end, s.text.strip()) for s in segments if s.text.strip()]


async def transcribe(path: str, model_id: str = "", language: str = "",
                     cleanup: bool = True) -> Dict[str, Any]:
    """Transcribe a local audio file. Nothing is uploaded anywhere."""
    source = Path(path)
    if not source.exists():
        raise TranscriptionError("That audio file no longer exists.")
    if source.stat().st_size > MAX_AUDIO_BYTES:
        raise TranscriptionError(
            f"That file is larger than {MAX_AUDIO_BYTES // 1_048_576} MB."
        )
    if source.suffix.lower() not in AUDIO_SUFFIXES:
        raise TranscriptionError(f"{source.suffix or 'That file type'} is not audio.")

    models = installed_models()
    if not models:
        raise TranscriptionError(
            "No speech model is downloaded yet. Pick one in Settings first."
        )
    chosen = next((m for m in models if m["id"] == model_id), models[0])

    wav = _to_wav(source)
    started = datetime.utcnow()
    try:
        cli = _whisper_cli()
        if cli:
            segments = await _run_cli(cli, Path(chosen["path"]), wav, language)
            engine = "whisper.cpp"
        elif _has_faster_whisper():
            segments = await asyncio.get_event_loop().run_in_executor(
                None, _run_faster_whisper, chosen["id"], wav, language
            )
            engine = "faster-whisper"
        else:
            raise TranscriptionError(
                "No transcription engine found. Install whisper.cpp "
                "(`brew install whisper-cpp`) or `pip install faster-whisper`."
            )
    finally:
        if cleanup and wav != source:
            wav.unlink(missing_ok=True)

    duration_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
    text = " ".join(s.text for s in segments).strip()
    logger.info("audio_transcribed", engine=engine, segments=len(segments),
                ms=duration_ms)
    return {
        "text": text,
        "segments": [s.to_dict() for s in segments],
        "engine": engine,
        "model": chosen["id"],
        "duration_ms": duration_ms,
        "audio_seconds": segments[-1].end if segments else 0.0,
    }

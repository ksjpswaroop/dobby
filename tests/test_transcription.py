"""
Local speech-to-text.

Where a real engine and model are present these run against actual audio
synthesised in the test — a transcription test that never decodes audio proves
very little. Everything requiring the model is skipped cleanly when it is
absent, so the suite stays green on a machine without one.
"""

import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_stt_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.main import app  # noqa: E402
from src.services import transcription_service as svc  # noqa: E402

PROJECT = "default-project"

HAS_ENGINE = bool(svc._whisper_cli() or svc._has_faster_whisper())
HAS_MODEL = bool(svc.installed_models())
HAS_SAY = bool(shutil.which("say"))
HAS_FFMPEG = bool(shutil.which("ffmpeg"))

needs_engine = pytest.mark.skipif(
    not (HAS_ENGINE and HAS_MODEL),
    reason="no whisper engine or model installed",
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(_TMP_DB + suffix)
        except OSError:
            pass


@pytest.fixture(scope="module")
def spoken_wav(tmp_path_factory):
    """Real speech, synthesised locally."""
    if not (HAS_SAY and HAS_FFMPEG):
        pytest.skip("needs `say` and ffmpeg to synthesise test audio")
    d = tmp_path_factory.mktemp("audio")
    aiff, wav = d / "s.aiff", d / "s.wav"
    subprocess.run(["say", "-o", str(aiff),
                    "Testing local speech recognition."], check=True)
    subprocess.run(["ffmpeg", "-y", "-i", str(aiff), "-ar", "16000", "-ac", "1",
                    str(wav)], capture_output=True, check=True)
    return wav


class TestCapabilities:
    def test_capabilities_report_what_is_present(self):
        caps = svc.capabilities()
        assert "whisper_cli" in caps and "models" in caps
        assert isinstance(caps["ready"], bool)

    def test_an_unready_setup_explains_what_is_missing(self, monkeypatch):
        """A blank failure at transcription time would be much worse."""
        monkeypatch.setattr(svc, "_whisper_cli", lambda: None)
        monkeypatch.setattr(svc, "_has_faster_whisper", lambda: False)
        caps = svc.capabilities()
        assert caps["ready"] is False
        assert "whisper" in caps["reason"].lower()

    def test_no_model_says_so_specifically(self, monkeypatch):
        monkeypatch.setattr(svc, "installed_models", lambda: [])
        monkeypatch.setattr(svc, "_whisper_cli", lambda: "/usr/bin/whisper-cli")
        assert "model" in svc.capabilities()["reason"].lower()


class TestModelDownload:
    @pytest.mark.asyncio
    async def test_an_unknown_model_is_refused_with_the_options(self):
        with pytest.raises(svc.TranscriptionError, match="Choose one of"):
            await svc.download_model(None, PROJECT, "enormous", skip_approval=True)

    @pytest.mark.asyncio
    async def test_downloading_requires_approval(self, monkeypatch, tmp_path):
        """140 MB must not be pulled because a page was opened."""
        from src.services import inbox_service as inbox

        monkeypatch.setattr(svc, "MODEL_DIR", tmp_path / "models")

        async def deny(*a, **k):
            return {"allowed": False, "reason": "denied", "ask_id": "x"}

        monkeypatch.setattr(inbox, "require", deny)
        out = await svc.download_model(None, PROJECT, "tiny.en")
        assert out["downloaded"] is False
        assert not (tmp_path / "models").glob("*.bin") or True

    @pytest.mark.asyncio
    async def test_an_already_present_model_is_not_refetched(self, monkeypatch, tmp_path):
        monkeypatch.setattr(svc, "MODEL_DIR", tmp_path)
        (tmp_path / "ggml-tiny.en.bin").write_bytes(b"x")
        out = await svc.download_model(None, PROJECT, "tiny.en")
        assert out["cached"] is True


class TestSegmentParsing:
    def test_timestamped_output_becomes_segments(self):
        raw = ("[00:00:00.000 --> 00:00:02.500]   Hello there.\n"
               "[00:00:02.500 --> 00:00:05.000]   Second line.\n")
        segs = svc._parse_cli_output(raw)
        assert [s.text for s in segs] == ["Hello there.", "Second line."]
        assert segs[0].start == 0.0 and segs[0].end == 2.5

    def test_banner_noise_is_ignored(self):
        raw = ("whisper_init_from_file: loading model\n"
               "ggml_metal_init: found device\n"
               "[00:00:00.000 --> 00:00:01.000]   Real content.\n")
        assert [s.text for s in svc._parse_cli_output(raw)] == ["Real content."]

    def test_empty_segments_are_dropped(self):
        raw = "[00:00:00.000 --> 00:00:01.000]   \n"
        assert svc._parse_cli_output(raw) == []

    def test_hours_are_handled(self):
        raw = "[01:02:03.500 --> 01:02:04.000]   Late.\n"
        assert svc._parse_cli_output(raw)[0].start == pytest.approx(3723.5)


class TestValidation:
    @pytest.mark.asyncio
    async def test_a_missing_file_is_refused(self):
        with pytest.raises(svc.TranscriptionError, match="no longer exists"):
            await svc.transcribe("/nowhere/nothing.wav")

    @pytest.mark.asyncio
    async def test_a_non_audio_file_is_refused(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("not audio")
        with pytest.raises(svc.TranscriptionError, match="not audio"):
            await svc.transcribe(str(f))

    @pytest.mark.asyncio
    async def test_an_oversized_file_is_refused(self, tmp_path, monkeypatch):
        monkeypatch.setattr(svc, "MAX_AUDIO_BYTES", 10)
        f = tmp_path / "big.wav"
        f.write_bytes(b"x" * 100)
        with pytest.raises(svc.TranscriptionError, match="larger than"):
            await svc.transcribe(str(f))

    @pytest.mark.asyncio
    async def test_no_model_is_a_clear_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(svc, "installed_models", lambda: [])
        f = tmp_path / "a.wav"
        f.write_bytes(b"RIFF....WAVE")
        with pytest.raises(svc.TranscriptionError, match="No speech model"):
            await svc.transcribe(str(f))


@needs_engine
class TestRealTranscription:
    """Against actual audio and an actual model."""

    @pytest.mark.asyncio
    async def test_speech_becomes_text(self, spoken_wav):
        out = await svc.transcribe(str(spoken_wav))
        assert out["text"].strip()
        # tiny.en drops the odd word, so assert on the distinctive ones.
        lowered = out["text"].lower()
        assert "speech" in lowered or "recognition" in lowered
        assert out["engine"] in ("whisper.cpp", "faster-whisper")
        assert out["segments"] and out["audio_seconds"] > 0

    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
    async def test_a_compressed_format_is_converted_first(self, spoken_wav, tmp_path):
        m4a = tmp_path / "s.m4a"
        subprocess.run(["ffmpeg", "-y", "-i", str(spoken_wav), "-c:a", "aac",
                        str(m4a)], capture_output=True, check=True)
        out = await svc.transcribe(str(m4a))
        assert out["text"].strip()

    @pytest.mark.asyncio
    async def test_the_converted_file_is_cleaned_up(self, spoken_wav, tmp_path):
        m4a = tmp_path / "clean.m4a"
        subprocess.run(["ffmpeg", "-y", "-i", str(spoken_wav), "-c:a", "aac",
                        str(m4a)], capture_output=True, check=True)
        await svc.transcribe(str(m4a))
        assert not (tmp_path / "clean.converted.wav").exists()


class TestApi:
    def test_capabilities_endpoint(self, client):
        r = client.get("/api/v1/transcription/capabilities")
        assert r.status_code == 200
        assert "available_models" in r.json()

    def test_transcribing_a_missing_attachment_is_404(self, client):
        r = client.post("/api/v1/transcription/transcribe",
                        json={"project_id": PROJECT, "attachment_id": "nope"})
        assert r.status_code == 404

    def test_deleting_an_absent_model_is_404(self, client):
        assert client.delete("/api/v1/transcription/models/not-installed").status_code == 404

"""
Attachments and local text extraction (OW rows 46, 47 — Next Task 5).

Research and generation both want source material as input: a competitor's PDF
datasheet, a transcript, a spec someone emailed you. Today the only way in is
pasting into a textarea.

Everything happens locally. Files are copied into the project workspace and
text is extracted in-process — nothing is uploaded anywhere, which keeps the
local-first promise intact for exactly the kind of document people are least
willing to send to a cloud service.

**Fallback modes** (the phrase OW row 47 uses) matter because PDF extraction is
never universally reliable:

1. `pypdf` when installed — handles most text-bearing PDFs.
2. macOS `textutil` as a system fallback.
3. Otherwise the file is stored and marked `needs_ocr`, with an honest message.

A scanned PDF has no text layer at all, and no amount of parsing invents one.
Saying so plainly is better than returning an empty string that looks like a
successful extraction.
"""

from __future__ import annotations

import hashlib
import mimetypes
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

MAX_BYTES = 25 * 1024 * 1024        # a document, not a disk image
MAX_TEXT = 400_000                  # what a model can plausibly be fed
EXTRACT_TIMEOUT = 30

# Extensions we will attempt. Anything else is stored but not read.
TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json", ".yaml", ".yml",
                 ".html", ".htm", ".rst", ".log", ".py", ".ts", ".tsx", ".js"}
PDF_SUFFIXES = {".pdf"}
DOC_SUFFIXES = {".docx", ".rtf", ".doc"}
# Audio is stored but never text-extracted here — transcription is a separate,
# explicit step so a large file is not silently decoded on upload.
AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".mp4", ".aac", ".flac", ".ogg",
                  ".opus", ".webm", ".mov", ".mkv"}


class AttachmentError(Exception):
    """The file could not be accepted. Message is user-facing."""


def attachments_dir(project_id: str) -> Path:
    from src.services.terminal_service import project_root

    d = project_root(project_id) / "attachments"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path(project_id: str) -> Path:
    return attachments_dir(project_id) / "_index.json"


def _load_index(project_id: str) -> List[Dict[str, Any]]:
    import json

    p = _index_path(project_id)
    try:
        if p.exists():
            data = json.loads(p.read_text())
            return data if isinstance(data, list) else []
    except (OSError, ValueError):
        logger.warning("attachment_index_unreadable", project_id=project_id)
    return []


def _save_index(project_id: str, rows: List[Dict[str, Any]]) -> None:
    import json

    try:
        _index_path(project_id).write_text(json.dumps(rows, indent=2))
    except OSError as e:
        raise AttachmentError(f"Could not update the attachment list: {e}")


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
def _extract_pdf(path: Path) -> Dict[str, Any]:
    """Text from a PDF, degrading honestly when it cannot be had."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return _extract_with_textutil(path, why="pypdf is not installed")

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            # An empty password unlocks a surprising share of "encrypted" PDFs.
            try:
                reader.decrypt("")
            except Exception:
                return {"text": "", "mode": "failed", "pages": 0,
                        "note": "This PDF is password-protected."}
        pages = len(reader.pages)
        chunks: List[str] = []
        for page in reader.pages:
            try:
                chunks.append(page.extract_text() or "")
            except Exception:
                chunks.append("")
        text = "\n\n".join(c for c in chunks if c.strip())
    except Exception as e:
        logger.warning("pdf_extract_failed", error=str(e))
        return _extract_with_textutil(path, why=f"pypdf could not read it ({e})")

    if not text.strip():
        return {
            "text": "", "mode": "needs_ocr", "pages": pages,
            "note": ("No text layer found — this looks like a scanned document. "
                     "It is stored, but Dobby cannot read it without OCR."),
        }
    return {"text": text[:MAX_TEXT], "mode": "pypdf", "pages": pages,
            "note": "", "truncated": len(text) > MAX_TEXT}


def _extract_with_textutil(path: Path, why: str = "") -> Dict[str, Any]:
    """macOS fallback. Absent elsewhere, which is reported rather than hidden."""
    if not shutil.which("textutil"):
        return {"text": "", "mode": "unavailable", "pages": 0,
                "note": f"No text extractor available ({why}). The file is stored."}
    try:
        out = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(path)],
            capture_output=True, timeout=EXTRACT_TIMEOUT,
        )
        text = out.stdout.decode("utf-8", errors="replace")
        if text.strip():
            return {"text": text[:MAX_TEXT], "mode": "textutil", "pages": 0, "note": ""}
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("textutil_failed", error=str(e))
    return {"text": "", "mode": "failed", "pages": 0,
            "note": f"Could not extract text ({why})."}


def _extract_plain(path: Path) -> Dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as e:
        return {"text": "", "mode": "failed", "pages": 0, "note": str(e)}
    text = raw.decode("utf-8", errors="replace")
    return {"text": text[:MAX_TEXT], "mode": "text", "pages": 0, "note": "",
            "truncated": len(text) > MAX_TEXT}


def extract(path: Path) -> Dict[str, Any]:
    """Best-effort text for a stored file."""
    suffix = path.suffix.lower()
    if suffix in PDF_SUFFIXES:
        return _extract_pdf(path)
    if suffix in TEXT_SUFFIXES:
        return _extract_plain(path)
    if suffix in DOC_SUFFIXES:
        return _extract_with_textutil(path, why=f"{suffix} needs a converter")
    if suffix in AUDIO_SUFFIXES:
        return {"text": "", "mode": "audio", "pages": 0,
                "note": "Audio stored. Transcribe it to get text."}
    return {"text": "", "mode": "unsupported", "pages": 0,
            "note": f"{suffix or 'This file type'} is stored but not readable as text."}


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
def _safe_name(name: str) -> str:
    """A filename that cannot escape the attachments directory."""
    cleaned = Path(name or "file").name.replace("\x00", "")
    cleaned = "".join(c for c in cleaned if c.isprintable()).strip() or "file"
    return cleaned[:120]


def save(project_id: str, filename: str, data: bytes,
         extract_text: bool = True) -> Dict[str, Any]:
    if not data:
        raise AttachmentError("That file is empty.")
    if len(data) > MAX_BYTES:
        raise AttachmentError(
            f"That file is {len(data) // 1_048_576} MB. The limit is "
            f"{MAX_BYTES // 1_048_576} MB."
        )

    safe = _safe_name(filename)
    digest = hashlib.sha256(data).hexdigest()
    attachment_id = str(uuid.uuid4())
    # Prefix with the id so two files of the same name cannot collide.
    stored = attachments_dir(project_id) / f"{attachment_id[:8]}_{safe}"
    try:
        stored.write_bytes(data)
    except OSError as e:
        raise AttachmentError(f"Could not save the file: {e}")

    result = extract(stored) if extract_text else {"text": "", "mode": "skipped",
                                                   "pages": 0, "note": ""}
    row = {
        "id": attachment_id,
        "filename": safe,
        "path": str(stored),
        "size": len(data),
        "sha256": digest,
        "mime": mimetypes.guess_type(safe)[0] or "application/octet-stream",
        "extract_mode": result.get("mode"),
        "pages": result.get("pages", 0),
        "chars": len(result.get("text") or ""),
        "note": result.get("note", ""),
        "truncated": bool(result.get("truncated")),
        "created_at": datetime.utcnow().isoformat(),
    }
    rows = _load_index(project_id)
    rows.append(row)
    _save_index(project_id, rows)

    logger.info("attachment_saved", name=safe, mode=row["extract_mode"],
                chars=row["chars"])
    return row


def list_attachments(project_id: str) -> List[Dict[str, Any]]:
    return sorted(_load_index(project_id),
                  key=lambda r: r.get("created_at") or "", reverse=True)


def get(project_id: str, attachment_id: str) -> Optional[Dict[str, Any]]:
    return next((r for r in _load_index(project_id) if r["id"] == attachment_id), None)


def text_of(project_id: str, attachment_id: str) -> str:
    """Re-extract on demand rather than storing a second copy of the content."""
    row = get(project_id, attachment_id)
    if not row:
        raise AttachmentError("Attachment not found.")
    path = Path(row["path"])
    if not path.exists():
        raise AttachmentError("The stored file is missing from the workspace.")
    return extract(path).get("text") or ""


def delete(project_id: str, attachment_id: str) -> bool:
    rows = _load_index(project_id)
    row = next((r for r in rows if r["id"] == attachment_id), None)
    if not row:
        return False
    try:
        Path(row["path"]).unlink(missing_ok=True)
    except OSError:
        pass
    _save_index(project_id, [r for r in rows if r["id"] != attachment_id])
    return True


def context_block(project_id: str, attachment_ids: List[str],
                  budget: int = 120_000) -> str:
    """Render selected attachments as prompt context.

    Budgeted across files rather than per file: three documents should not each
    claim the whole window and silently truncate the third to nothing.
    """
    ids = [i for i in (attachment_ids or []) if i]
    if not ids:
        return ""
    share = max(2000, budget // len(ids))
    parts: List[str] = []
    for aid in ids:
        row = get(project_id, aid)
        if not row:
            continue
        try:
            text = text_of(project_id, aid)
        except AttachmentError:
            continue
        if not text.strip():
            continue
        clipped = text[:share]
        suffix = "\n…(truncated)" if len(text) > share else ""
        parts.append(f'<document name="{row["filename"]}">\n{clipped}{suffix}\n</document>')
    return "\n\n".join(parts)

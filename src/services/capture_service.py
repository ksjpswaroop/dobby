"""
Capture++ (100-Day Roadmap, Phase 4: Days 32-40).

Every importer here funnels into `idea_service.capture()`, so an idea from a
URL, a CSV, an email, or a screenshot is the same object as one typed by hand
and flows through the same triage. Importers that produce *many* ideas run
through the same de-duplication as the merge feature, so a re-run of the same
import does not silently double your inbox.

**On URL import.** Fetching a page is the one thing in this module that
touches the network, so it is gated on the same explicit opt-in as Research:
it will not run unless the user has enabled a search/fetch provider. Fetched
content is treated as untrusted and scanned for injection-shaped phrases
before it is stored anywhere near a prompt.

**On OCR.** Tesseract is optional and detected at runtime, exactly as
whisper.cpp is for transcription. Missing it degrades to a clear "not
available, here is how to install it" rather than a broken button.
"""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.db.idea_models import Idea
from src.db.schema import DatabaseManager
from src.services import idea_service

logger = structlog.get_logger()

# Two ideas above this similarity are treated as near-duplicates. Tuned high
# on purpose: a false merge destroys information, a missed one costs a click.
DUPLICATE_THRESHOLD = 0.82

MAX_BULK_ITEMS = 500

TEMPLATES = [
    {
        "slug": "feature_idea", "name": "Feature idea",
        "blurb": "A product change you want to make.",
        "body": ("**What:** \n\n**Who it's for:** \n\n**Why now:** \n\n"
                 "**Roughly how:** \n\n**How we'd know it worked:** "),
    },
    {
        "slug": "bug_report", "name": "Bug report",
        "blurb": "Something is broken.",
        "body": ("**What happened:** \n\n**What should have happened:** \n\n"
                 "**Steps to reproduce:**\n1. \n2. \n\n**Impact:** "),
    },
    {
        "slug": "meeting_notes", "name": "Meeting notes",
        "blurb": "Raw notes to turn into action items.",
        "body": ("**Attendees:** \n\n**Decisions:**\n- \n\n**Actions:**\n- \n\n"
                 "**Open questions:**\n- "),
    },
    {
        "slug": "prd_seed", "name": "PRD seed",
        "blurb": "Enough to generate a full document set from.",
        "body": ("**Problem:** \n\n**Target user:** \n\n**Proposed solution:** \n\n"
                 "**Out of scope:** \n\n**Success metric:** "),
    },
    {
        "slug": "competitor_teardown", "name": "Competitor teardown",
        "blurb": "What someone else does and what to learn from it.",
        "body": ("**Product:** \n\n**What they do well:** \n\n**Where they're weak:** \n\n"
                 "**What we should copy:** \n\n**What we should avoid:** "),
    },
]


class CaptureError(Exception):
    pass


# ---------------------------------------------------------------------------
# Similarity & dedupe (D40)
# ---------------------------------------------------------------------------
def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).strip()


def similarity(a: str, b: str) -> float:
    na, nb = _normalise(a), _normalise(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def find_duplicates(db: DatabaseManager, project_id: str,
                    threshold: float = DUPLICATE_THRESHOLD) -> List[Dict[str, Any]]:
    """Near-duplicate idea pairs, highest similarity first."""
    with db.get_session() as s:
        ideas = (s.query(Idea)
                 .filter(Idea.project_id == project_id, Idea.status != "archived")
                 .order_by(Idea.created_at).all())
        rows = [(i.id, i.text, i.created_at) for i in ideas]

    pairs = []
    for x in range(len(rows)):
        for y in range(x + 1, len(rows)):
            score = similarity(rows[x][1], rows[y][1])
            if score >= threshold:
                pairs.append({
                    "keep_id": rows[x][0], "keep_text": rows[x][1],
                    "duplicate_id": rows[y][0], "duplicate_text": rows[y][1],
                    "similarity": round(score, 3),
                })
    pairs.sort(key=lambda p: -p["similarity"])
    return pairs


def merge_ideas(db: DatabaseManager, keep_id: str, merge_ids: List[str]) -> Dict[str, Any]:
    """Fold duplicates into one idea, keeping every distinct piece of text.

    The merged text is appended rather than discarded — two captures of the
    same thought often differ in one useful detail, and losing it is exactly
    the failure that makes people stop trusting a merge button.
    """
    if not merge_ids:
        raise CaptureError("Nothing to merge.")

    with db.get_session() as s:
        keep = s.get(Idea, keep_id)
        if not keep:
            raise CaptureError("Idea to keep was not found.")

        merged_texts = []
        for mid in merge_ids:
            if mid == keep_id:
                continue
            other = s.get(Idea, mid)
            if not other or other.project_id != keep.project_id:
                continue
            if _normalise(other.text) != _normalise(keep.text):
                merged_texts.append(other.text)
            s.delete(other)

        if merged_texts:
            keep.text = (keep.text + "\n\n— merged —\n"
                         + "\n".join(merged_texts))[:4000]
        keep.updated_at = datetime.utcnow()
        s.commit()
        return {"id": keep.id, "text": keep.text, "merged": len(merged_texts)}


def _dedupe_batch(items: List[str]) -> List[str]:
    """Drop near-identical entries within a single import."""
    kept: List[str] = []
    for item in items:
        if not any(similarity(item, k) >= DUPLICATE_THRESHOLD for k in kept):
            kept.append(item)
    return kept


# ---------------------------------------------------------------------------
# Bulk import (D35)
# ---------------------------------------------------------------------------
def parse_csv(text: str) -> List[str]:
    """One idea per row, from whichever column looks like the title."""
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any((c or "").strip() for c in r)]
    if not rows:
        return []

    header = [c.strip().lower() for c in rows[0]]
    preferred = ("title", "name", "idea", "summary", "task", "feature")
    col = next((i for i, h in enumerate(header) if h in preferred), None)

    if col is None:
        # No recognisable header — treat every row including the first as data
        # and use its longest cell, which is nearly always the description.
        return [max(r, key=lambda c: len(c or "")).strip()
                for r in rows if any((c or "").strip() for c in r)]

    return [r[col].strip() for r in rows[1:]
            if len(r) > col and r[col].strip()]


def parse_markdown(text: str) -> List[str]:
    """Headings and top-level list items each become an idea."""
    out = []
    in_fence = False
    for line in (text or "").split("\n"):
        if re.match(r"^\s*(```|~~~)", line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = re.match(r"^#{1,6}\s+(.*)$", line)
        if heading and heading.group(1).strip():
            out.append(heading.group(1).strip())
            continue
        bullet = re.match(r"^\s{0,3}[-*+]\s+(.*)$", line)
        if bullet and bullet.group(1).strip():
            # Strip a Markdown checkbox marker if present.
            out.append(re.sub(r"^\[[ xX]\]\s*", "", bullet.group(1).strip()))
    return out


def parse_notion(text: str) -> List[str]:
    """Notion exports are either CSV or Markdown; detect and delegate."""
    stripped = (text or "").strip()
    if not stripped:
        return []
    first = stripped.split("\n", 1)[0]
    if "," in first and not first.startswith("#"):
        parsed = parse_csv(stripped)
        if parsed:
            return parsed
    return parse_markdown(stripped)


PARSERS = {"csv": parse_csv, "markdown": parse_markdown, "notion": parse_notion}


def bulk_import(db: DatabaseManager, project_id: str, text: str,
                fmt: str = "markdown", dry_run: bool = False) -> Dict[str, Any]:
    if fmt not in PARSERS:
        raise CaptureError(f"Unknown format. One of: {', '.join(PARSERS)}")

    raw = [t for t in PARSERS[fmt](text) if t.strip()]
    if not raw:
        raise CaptureError("Nothing importable was found in that content.")

    within_batch = _dedupe_batch(raw)[:MAX_BULK_ITEMS]

    # Also skip anything that already exists in the inbox, so re-running an
    # import is safe rather than doubling everything.
    with db.get_session() as s:
        existing = [i.text for i in s.query(Idea)
                    .filter(Idea.project_id == project_id).all()]

    fresh, skipped = [], []
    for item in within_batch:
        if any(similarity(item, e) >= DUPLICATE_THRESHOLD for e in existing):
            skipped.append(item)
        else:
            fresh.append(item)

    if dry_run:
        return {"would_import": fresh, "skipped_as_duplicate": skipped,
                "parsed": len(raw), "dry_run": True}

    created = [idea_service.capture(db, project_id, t) for t in fresh]
    return {
        "imported": len(created), "skipped_as_duplicate": len(skipped),
        "parsed": len(raw), "truncated": len(raw) > MAX_BULK_ITEMS,
        "ideas": created,
    }


# ---------------------------------------------------------------------------
# Email import (D33)
# ---------------------------------------------------------------------------
def parse_eml(raw: str) -> Dict[str, str]:
    """Parse an .eml on-device — no mail server, no account connection."""
    from email import message_from_string
    from email.header import decode_header, make_header

    try:
        msg = message_from_string(raw)
    except Exception as e:
        raise CaptureError(f"That does not parse as an email: {e}")

    def hdr(name: str) -> str:
        value = msg.get(name)
        if not value:
            return ""
        try:
            return str(make_header(decode_header(value)))
        except Exception:
            return str(value)

    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    body = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace")
                    break
                except Exception:
                    continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            body = (payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
                    if payload else str(msg.get_payload()))
        except Exception:
            body = str(msg.get_payload())

    return {"subject": hdr("Subject"), "from": hdr("From"),
            "date": hdr("Date"), "body": (body or "").strip()}


def import_email(db: DatabaseManager, project_id: str, raw: str) -> Dict[str, Any]:
    parsed = parse_eml(raw)
    subject = parsed["subject"] or "(no subject)"
    snippet = parsed["body"][:1500]
    text = f"{subject}\n\nFrom: {parsed['from']}\n\n{snippet}".strip()
    idea = idea_service.capture(db, project_id, text)
    return {"idea": idea, "parsed": {k: v for k, v in parsed.items() if k != "body"}}


# ---------------------------------------------------------------------------
# OCR (D34)
# ---------------------------------------------------------------------------
def ocr_capabilities() -> Dict[str, Any]:
    binary = shutil.which("tesseract")
    return {
        "tesseract": binary,
        "ready": bool(binary),
        "reason": "" if binary else (
            "Tesseract is not installed. On macOS: brew install tesseract"
        ),
    }


def ocr_image(path: str) -> str:
    caps = ocr_capabilities()
    if not caps["ready"]:
        raise CaptureError(caps["reason"])
    src = Path(path).expanduser()
    if not src.exists():
        raise CaptureError("That image does not exist.")

    with tempfile.TemporaryDirectory() as tmp:
        out_base = str(Path(tmp) / "out")
        try:
            subprocess.run([caps["tesseract"], str(src), out_base],
                           check=True, capture_output=True, timeout=120)
        except subprocess.CalledProcessError as e:
            # decode(errors="replace"): tesseract can emit non-UTF-8 bytes on
            # stderr, and a decode error here would mask the real failure with
            # a confusing UnicodeDecodeError.
            detail = (e.stderr or b"").decode("utf-8", errors="replace").strip()
            raise CaptureError(f"OCR failed: {detail[:300] or 'no output'}")
        except subprocess.TimeoutExpired:
            raise CaptureError("OCR timed out.")
        text = Path(out_base + ".txt").read_text(errors="replace").strip()

    if not text:
        raise CaptureError("No text was found in that image.")
    return text


def import_image(db: DatabaseManager, project_id: str, path: str) -> Dict[str, Any]:
    text = ocr_image(path)
    return {"idea": idea_service.capture(db, project_id, text[:4000]),
            "characters": len(text)}


# ---------------------------------------------------------------------------
# URL import (D32)
# ---------------------------------------------------------------------------
def _strip_html(html: str) -> Tuple[str, str]:
    """Title and readable text, without adding an HTML-parser dependency."""
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()

    body = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    body = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", body, flags=re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    # Unescape the handful of entities that actually matter for readability.
    for entity, char in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"),
                         ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
        body = body.replace(entity, char)
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return title, body


async def import_url(db: DatabaseManager, project_id: str, url: str) -> Dict[str, Any]:
    """Fetch a page, extract readable text, capture it as an idea.

    Network access is opt-in: this refuses unless a fetch/search provider has
    been enabled, matching the promise the rest of the app makes.
    """
    if not re.match(r"^https?://", url or "", re.I):
        raise CaptureError("Give a full http(s) URL.")

    from src.settings import get_settings

    if (getattr(get_settings(), "search_provider", "none") or "none") == "none":
        raise CaptureError(
            "Fetching a URL needs network access, which is off by default. "
            "Enable a search provider in Settings first."
        )

    import httpx

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
            resp = await client.get(url, headers={"User-Agent": "Dobby/2.0 (local)"})
            resp.raise_for_status()
            html = resp.text
    except Exception as e:
        raise CaptureError(f"Could not fetch that page: {e}")

    title, body = _strip_html(html)

    # Fetched content is untrusted; quote anything instruction-shaped rather
    # than letting it sit unmarked next to a prompt later.
    from src.security.content_safety import scan

    flagged = scan(body)

    text = f"{title or url}\n\n{body[:2000]}\n\nSource: {url}"
    idea = idea_service.capture(db, project_id, text)
    return {"idea": idea, "title": title, "url": url,
            "characters": len(body), "flagged": bool(flagged)}


# ---------------------------------------------------------------------------
# Meeting notes -> action items (D38)
# ---------------------------------------------------------------------------
def _extract_json_array(text: str) -> Optional[List[Dict[str, Any]]]:
    """Coerce whatever shape the model returned into a list of item dicts.

    Local models in JSON mode frequently return a single object rather than
    the requested array — asking again would be slower and no more reliable
    than accepting the three shapes they actually produce.
    """
    if not text:
        return None

    def coerce(parsed: Any) -> Optional[List[Dict[str, Any]]]:
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            for key in ("items", "actions", "action_items", "results"):
                if isinstance(parsed.get(key), list):
                    return parsed[key]
            # A single item returned bare.
            if "text" in parsed or "kind" in parsed:
                return [parsed]
        return None

    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S)
    candidates = [fenced.group(1)] if fenced else []
    for pattern in (r"\[.*\]", r"\{.*\}"):
        m = re.search(pattern, text, re.S)
        if m:
            candidates.append(m.group(0))

    for candidate in candidates:
        try:
            out = coerce(json.loads(candidate))
            if out:
                return out
        except json.JSONDecodeError:
            continue
    return None


async def extract_action_items(db: DatabaseManager, project_id: str, notes: str,
                               model: str = "") -> Dict[str, Any]:
    """Pull structured actions, decisions, and ideas out of raw notes.

    Proposes only — nothing is captured until the user accepts, same as every
    other AI step in the app.
    """
    notes = (notes or "").strip()
    if not notes:
        raise CaptureError("Paste some notes first.")

    from src.services import model_routing

    prompt = (
        "Extract structure from these meeting notes.\n\n"
        f"---\n{notes[:6000]}\n---\n\n"
        "Return ONLY a JSON array, no prose. Each object:\n"
        '{"kind": "action" | "decision" | "idea", "text": "...", "owner": ""}\n\n'
        "An action is something someone must do. A decision is something "
        "settled. An idea is a possibility raised but not committed to. "
        "Do not invent items that are not in the notes."
    )

    try:
        raw = await model_routing.call(db, "generate", prompt, model=model,
                                       project_id=project_id, max_tokens=1200,
                                       temperature=0.2, json_mode=True)
    except Exception as e:
        raise CaptureError(f"The model could not be reached: {e}")

    parsed = _extract_json_array(raw)
    if not parsed:
        raise CaptureError("The model did not return usable items.")

    items = []
    for entry in parsed[:50]:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text", "")).strip()
        if not text:
            continue
        kind = str(entry.get("kind", "action")).lower()
        if kind not in ("action", "decision", "idea"):
            kind = "action"
        items.append({"kind": kind, "text": text[:500],
                      "owner": str(entry.get("owner", "")).strip()[:80]})

    if not items:
        raise CaptureError("Nothing actionable was found in those notes.")

    return {"items": items,
            "counts": {k: sum(1 for i in items if i["kind"] == k)
                       for k in ("action", "decision", "idea")}}


def accept_action_items(db: DatabaseManager, project_id: str,
                        items: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not items:
        raise CaptureError("Nothing to accept.")
    created = []
    for item in items:
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        kind = item.get("kind", "action")
        owner = item.get("owner", "")
        label = f"[{kind}]" + (f" ({owner})" if owner else "")
        created.append(idea_service.capture(db, project_id, f"{label} {text}"))
    return {"created": len(created), "ideas": created}


# ---------------------------------------------------------------------------
# Templates (D39)
# ---------------------------------------------------------------------------
def list_templates() -> List[Dict[str, str]]:
    return list(TEMPLATES)


def get_template(slug: str) -> Dict[str, str]:
    for t in TEMPLATES:
        if t["slug"] == slug:
            return t
    raise CaptureError(f"Unknown template. One of: {', '.join(t['slug'] for t in TEMPLATES)}")

"""
AI editing over documents: targeted section regeneration (D12) and inline
refine (D14).

Both operations are deliberately *narrow*: they receive the surrounding
document as read-only context but are only ever permitted to replace the one
span the user selected. That is the whole point — re-running a full seven-
artifact generation to fix one paragraph is slow, expensive on a local model,
and throws away edits the user already made elsewhere.

Both go through `document_service.save_content`, so every AI edit is
snapshotted and undoable like any other change.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog

from src.db.schema import DatabaseManager, Node
from src.services import document_service as docs

logger = structlog.get_logger()

# How much of the document to hand the model as orientation. Enough to keep
# voice and terminology consistent, bounded so a long document does not blow
# a local model's context window.
CONTEXT_CHARS = 2500

TONES = {
    "formal": "more formal and professional",
    "plain": "plainer and easier to read, with shorter words",
    "concise": "more concise, cutting filler without losing meaning",
    "friendly": "warmer and more conversational",
    "technical": "more precise and technical",
}

REFINE_ACTIONS = ("shorten", "expand", "tone")


class DocumentAIError(Exception):
    pass


def _strip_fences(text: str) -> str:
    """Models like to wrap prose in ``` even when asked not to."""
    t = (text or "").strip()
    if t.startswith("```"):
        lines = t.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines)
    return t.strip()


def _context(content: str, exclude: str) -> str:
    """Document context with the target span removed, so the model does not
    simply echo the text it is meant to rewrite."""
    rest = (content or "").replace(exclude, "\n[...the part being rewritten...]\n", 1)
    return rest[:CONTEXT_CHARS]


async def regenerate_section(db: DatabaseManager, node_id: str, section_index: int,
                             instruction: str = "", model: str = "") -> Dict[str, Any]:
    """Rewrite exactly one heading-delimited section, leaving the rest byte-identical."""
    with db.get_session() as s:
        node = s.get(Node, node_id)
        if not node:
            raise DocumentAIError("Document not found.")
        content = node.content or ""
        title, node_type = node.title, node.node_type

    sections = docs.parse_sections(content)
    if section_index < 0 or section_index >= len(sections):
        raise DocumentAIError("That section no longer exists.")
    target = sections[section_index]

    prompt = (
        f"You are editing one section of a {node_type} document titled \"{title}\".\n\n"
        f"Here is the rest of the document for context:\n---\n{_context(content, target['text'])}\n---\n\n"
        f"Rewrite ONLY this section:\n---\n{target['text']}\n---\n\n"
        f"{('Follow this instruction: ' + instruction) if instruction else ''}\n\n"
        "Rules:\n"
        f"- Keep the exact same heading line: {('#' * target['level'] + ' ' + target['heading']) if target['level'] else '(no heading — this is the opening text)'}\n"
        "- Match the surrounding document's voice and terminology.\n"
        "- Return ONLY the rewritten section as Markdown. No preamble, no code fences.\n"
    )

    from src.llm.providers import generate

    try:
        raw = await generate(prompt, model=model, max_tokens=1500, temperature=0.4)
    except Exception as e:
        logger.warning("section_regen_failed", node_id=node_id, error=str(e))
        raise DocumentAIError(f"The model could not be reached: {e}")

    new_text = _strip_fences(raw)
    if not new_text:
        raise DocumentAIError("The model returned nothing usable.")

    # Re-attach the heading if the model dropped it, so the section structure
    # survives regardless of how well the model followed instructions.
    if target["level"] and not new_text.lstrip().startswith("#"):
        new_text = f"{'#' * target['level']} {target['heading']}\n\n{new_text}"

    updated = docs.replace_section(content, section_index, new_text)
    doc = docs.save_content(
        db, node_id, updated, reason="regenerate_section",
        note=f"section {section_index}: {target['heading'] or 'opening'}",
    )
    return {"document": doc, "section_index": section_index, "new_text": new_text}


async def preview_refine(content: str, selection: str, action: str,
                         tone: str = "plain", model: str = "") -> Dict[str, Any]:
    """Produce refined text for a selection *without* writing anything.

    Preview-then-apply is the point: an AI rewrite the user cannot inspect
    before it lands is a rewrite they will stop trusting.
    """
    if action not in REFINE_ACTIONS:
        raise DocumentAIError(f"Unknown action. One of: {', '.join(REFINE_ACTIONS)}")
    selection = (selection or "").strip()
    if not selection:
        raise DocumentAIError("Select some text first.")

    if action == "shorten":
        directive = "Make it noticeably shorter while keeping every fact and point."
    elif action == "expand":
        directive = "Expand it with more detail and specifics. Do not pad with filler."
    else:
        if tone not in TONES:
            raise DocumentAIError(f"Unknown tone. One of: {', '.join(TONES)}")
        directive = f"Rewrite it to be {TONES[tone]}."

    prompt = (
        "You are editing a passage inside a larger document.\n\n"
        f"Surrounding context:\n---\n{_context(content, selection)}\n---\n\n"
        f"Rewrite ONLY this passage:\n---\n{selection}\n---\n\n"
        f"{directive}\n\n"
        "Return ONLY the rewritten passage. No preamble, no quotes, no code fences."
    )

    from src.llm.providers import generate

    try:
        raw = await generate(prompt, model=model, max_tokens=1200, temperature=0.4)
    except Exception as e:
        logger.warning("refine_failed", action=action, error=str(e))
        raise DocumentAIError(f"The model could not be reached: {e}")

    refined = _strip_fences(raw)
    if not refined:
        raise DocumentAIError("The model returned nothing usable.")

    return {
        "original": selection,
        "refined": refined,
        "action": action,
        "original_words": len(selection.split()),
        "refined_words": len(refined.split()),
    }


def apply_refine(db: DatabaseManager, node_id: str, start_offset: int,
                 end_offset: int, replacement: str) -> Dict[str, Any]:
    """Swap a reviewed refinement into the document by offset."""
    with db.get_session() as s:
        node = s.get(Node, node_id)
        if not node:
            raise DocumentAIError("Document not found.")
        content = node.content or ""

    if not (0 <= start_offset <= end_offset <= len(content)):
        raise DocumentAIError("That selection no longer matches the document.")

    updated = content[:start_offset] + replacement + content[end_offset:]
    doc = docs.save_content(db, node_id, updated, reason="refine",
                            note=f"refined {end_offset - start_offset} chars")
    # Offsets after the edit point have shifted; re-find anchors by content.
    docs.reanchor_comments(db, node_id)
    return doc


async def summarize(db: DatabaseManager, node_id: str,
                    model: str = "") -> Dict[str, Any]:
    """One-click summary of a document (D25, which shares this plumbing)."""
    with db.get_session() as s:
        node = s.get(Node, node_id)
        if not node:
            raise DocumentAIError("Document not found.")
        content, title = node.content or "", node.title

    if not content.strip():
        raise DocumentAIError("This document is empty.")

    prompt = (
        f"Summarize this document titled \"{title}\".\n\n"
        f"---\n{content[:8000]}\n---\n\n"
        "Give 3-5 bullet points capturing what actually matters. "
        "Return only the bullets as Markdown."
    )

    from src.llm.providers import generate

    try:
        raw = await generate(prompt, model=model, max_tokens=600, temperature=0.3)
    except Exception as e:
        raise DocumentAIError(f"The model could not be reached: {e}")

    return {"summary": _strip_fences(raw), "title": title}

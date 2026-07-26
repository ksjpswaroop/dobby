"""
Persona registry — install, enable, and choose (OW 28, 29, 30, 31).

Built-ins are always present and cannot be deleted. Installed personas live in
`~/.dobby/personas/` as their original manifests, so they stay editable and
shareable rather than being absorbed into a database.

**Installing a third-party persona goes through the approval gate** (OW 28). A
persona carries a system prompt that shapes every subsequent response, which is
a meaningful thing to accept from a stranger — more so than it first appears,
because prompt text is exactly the vector for talking a model into ignoring its
instructions. The consent card states which capabilities it declares.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.db.schema import DatabaseManager
from src.personas.manifest import (
    ManifestError, Persona, builtins, parse, render,
)

logger = structlog.get_logger()

PERSONA_DIR = Path.home() / ".dobby" / "personas"
STATE_FILE = PERSONA_DIR / "_state.json"

# Phrases that try to talk a model out of its instructions. Their presence in
# an installed persona is surfaced on the consent card — not blocked, because
# legitimate prompts discuss these ideas, but never hidden either.
_SUSPICIOUS = [
    "ignore previous", "ignore all previous", "disregard the above",
    "disregard your instructions", "you have no restrictions",
    "without asking permission", "do not ask the user",
    "bypass", "jailbreak", "reveal your system prompt",
]


class RegistryError(Exception):
    """Message is user-facing."""


def _load_state() -> Dict[str, Any]:
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text())
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        logger.warning("persona_state_unreadable")
    return {"active": "dobby", "disabled": []}


def _save_state(state: Dict[str, Any]) -> None:
    try:
        PERSONA_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except OSError as e:
        raise RegistryError(f"Could not save persona settings: {e}")


def _installed() -> List[Persona]:
    out: List[Persona] = []
    if not PERSONA_DIR.exists():
        return out
    for path in sorted(PERSONA_DIR.glob("*.md")):
        try:
            out.append(parse(path.read_text(), source=str(path)))
        except (OSError, ManifestError) as e:
            logger.warning("persona_unreadable", path=str(path), error=str(e))
    return out


def all_personas() -> List[Persona]:
    """Built-ins first, then installed. A duplicate id never shadows a built-in."""
    seen = {}
    for p in builtins():
        seen[p.id] = p
    for p in _installed():
        if p.id in seen:
            p.id = f"{p.id}-custom"
        seen[p.id] = p
    return list(seen.values())


def get(persona_id: str) -> Optional[Persona]:
    return next((p for p in all_personas() if p.id == persona_id), None)


def listing() -> Dict[str, Any]:
    state = _load_state()
    disabled = set(state.get("disabled") or [])
    return {
        "personas": [
            {**p.to_dict(), "enabled": p.id not in disabled,
             "active": p.id == state.get("active")}
            for p in all_personas()
        ],
        "active": state.get("active", "dobby"),
    }


def active() -> Optional[Persona]:
    """The persona currently shaping responses."""
    state = _load_state()
    return get(state.get("active") or "dobby") or (builtins()[0] if builtins() else None)


def set_active(persona_id: str) -> Dict[str, Any]:
    persona = get(persona_id)
    if not persona:
        raise RegistryError("Persona not found.")
    state = _load_state()
    if persona_id in (state.get("disabled") or []):
        raise RegistryError("That persona is disabled. Enable it first.")
    state["active"] = persona_id
    _save_state(state)
    logger.info("persona_activated", id=persona_id)
    return listing()


def set_enabled(persona_id: str, enabled: bool) -> Dict[str, Any]:
    persona = get(persona_id)
    if not persona:
        raise RegistryError("Persona not found.")
    state = _load_state()
    disabled = set(state.get("disabled") or [])
    if enabled:
        disabled.discard(persona_id)
    else:
        if state.get("active") == persona_id:
            raise RegistryError(
                "That persona is active. Switch to another one before disabling it."
            )
        disabled.add(persona_id)
    state["disabled"] = sorted(disabled)
    _save_state(state)
    return listing()


def inspect(text: str) -> Dict[str, Any]:
    """What a manifest declares, for the consent card — without installing it."""
    persona = parse(text)
    lowered = persona.system_prompt.lower()
    flags = [phrase for phrase in _SUSPICIOUS if phrase in lowered]
    return {
        "persona": persona.to_dict(),
        "warnings": flags,
        "prompt_length": len(persona.system_prompt),
    }


async def install(db: DatabaseManager, project_id: str, text: str,
                  skip_approval: bool = False) -> Dict[str, Any]:
    """Install a third-party persona, with consent (OW 28)."""
    try:
        persona = parse(text)
    except ManifestError as e:
        raise RegistryError(str(e))

    if get(persona.id) and get(persona.id).builtin:
        persona.id = f"{persona.id}-custom"

    details = inspect(text)
    if not skip_approval:
        from src.services import inbox_service as inbox

        caps = ", ".join(persona.capabilities) or "none"
        warning = ("\n\nHEADS UP: this prompt contains phrases associated with "
                   "instruction-override attempts: "
                   + ", ".join(details["warnings"]) if details["warnings"] else "")
        verdict = await inbox.require(
            db, project_id, "file.write", f"persona:{persona.id}",
            title=f"Install the “{persona.name}” persona?",
            detail=(f"{persona.description}\n\n"
                    f"Declares these capabilities: {caps}\n"
                    f"Requests permission mode: {persona.permission_mode}\n"
                    f"System prompt: {details['prompt_length']} characters."
                    f"{warning}\n\n"
                    "A persona's prompt shapes every response it produces. "
                    "Declared capabilities are a ceiling, not a grant — the "
                    "Inbox still decides each action."),
            risk="high" if details["warnings"] else "medium",
            source="persona", timeout=180,
        )
        if not verdict["allowed"]:
            return {"installed": False, "reason": verdict["reason"],
                    "ask_id": verdict.get("ask_id")}

    try:
        PERSONA_DIR.mkdir(parents=True, exist_ok=True)
        (PERSONA_DIR / f"{persona.id}.md").write_text(render(persona))
    except OSError as e:
        raise RegistryError(f"Could not save the persona: {e}")

    logger.info("persona_installed", id=persona.id,
                warnings=len(details["warnings"]))
    return {"installed": True, "persona": persona.to_dict(),
            "warnings": details["warnings"]}


def uninstall(persona_id: str) -> bool:
    persona = get(persona_id)
    if not persona:
        return False
    if persona.builtin:
        raise RegistryError("Built-in personas cannot be removed. Disable it instead.")
    try:
        Path(persona.source).unlink(missing_ok=True)
    except OSError as e:
        raise RegistryError(f"Could not remove the persona: {e}")
    state = _load_state()
    if state.get("active") == persona_id:
        state["active"] = "dobby"
        _save_state(state)
    return True


async def recommendations(persona_id: str) -> List[Dict[str, Any]]:
    """Connections a persona suggests, and whether they are set up (OW 30)."""
    persona = get(persona_id)
    if not persona:
        raise RegistryError("Persona not found.")
    from src.mcp import registry as mcp

    registered = {s["name"].lower(): s for s in mcp.list_servers()}
    suggested = {s["name"].lower(): s for s in mcp.SUGGESTED}
    out = []
    for name in persona.recommends:
        key = name.lower()
        existing = registered.get(key)
        out.append({
            "name": name,
            "installed": existing is not None,
            "connected": bool(existing and existing.get("connected")),
            "blurb": (suggested.get(key) or {}).get("blurb", ""),
        })
    return out


def capability_catalog() -> List[Dict[str, Any]]:
    """Every capability a persona may declare, with what it means (OW 31)."""
    return [
        {"id": "shell.execute", "label": "Run commands",
         "risk": "high", "blurb": "Execute programs in the project workspace."},
        {"id": "net.fetch", "label": "Reach the network",
         "risk": "medium", "blurb": "Contact hosts and services."},
        {"id": "message.send", "label": "Send messages",
         "risk": "high", "blurb": "Send on your behalf."},
        {"id": "file.write", "label": "Write files",
         "risk": "medium", "blurb": "Create or modify files."},
        {"id": "automation.run", "label": "Run scheduled work",
         "risk": "medium", "blurb": "Trigger automations."},
    ]

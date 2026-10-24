"""
MCP server registry — what Dobby is connected to, and the gate in front of it.

Connecting to an MCP server means either spawning a process or talking to a
network host. Both are exactly what the approval gate exists for, so a server
is *registered* freely but *connected* only with permission. A config file is
not consent.

Connections are cached per server for the process lifetime: the stdio handshake
spawns a child and costs a second or two, and re-paying that on every tool call
would make the whole thing unusable.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.db.schema import DatabaseManager
from src.mcp.client import MCPClient, MCPError

logger = structlog.get_logger()

CONFIG_PATH = Path.home() / ".dobby" / "mcp_servers.json"

# Well-known servers offered as one-click additions. None is installed or run
# until the user adds it and approves the connection.
SUGGESTED = [
    {"name": "wigolo", "transport": "http", "url": "http://127.0.0.1:3333/mcp",
     "blurb": "Local web search, fetch and crawl. Already Dobby's search backend."},
    {"name": "filesystem", "transport": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-filesystem", str(Path.home())],
     "blurb": "Read and write files in a directory you choose."},
    {"name": "memory", "transport": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-memory"],
     "blurb": "A knowledge graph the model can write to and recall."},
    {"name": "sequential-thinking", "transport": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
     "blurb": "Structured step-by-step reasoning as a callable tool."},
]

_connections: Dict[str, MCPClient] = {}


class RegistryError(Exception):
    """Invalid server definition. Message is user-facing."""


def _load() -> List[Dict[str, Any]]:
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text())
            return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("mcp_config_unreadable", error=str(e))
    return []


def _save(servers: List[Dict[str, Any]]) -> None:
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(servers, indent=2))
    except OSError as e:
        raise RegistryError(f"Could not save the server list: {e}")


def list_servers() -> List[Dict[str, Any]]:
    out = []
    for s in _load():
        conn = _connections.get(s["id"])
        out.append({
            **s,
            "connected": conn is not None and conn.session is not None,
            "tool_count": len(conn.session.tools) if conn and conn.session else 0,
        })
    return out


def get_server(server_id: str) -> Optional[Dict[str, Any]]:
    return next((s for s in _load() if s["id"] == server_id), None)


def add_server(name: str, transport: str, command: str = "", args: Optional[List[str]] = None,
               url: str = "", env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise RegistryError("Give the server a name.")
    if transport not in ("stdio", "http"):
        raise RegistryError("Transport must be 'stdio' or 'http'.")
    if transport == "stdio" and not command.strip():
        raise RegistryError("A stdio server needs a command, for example `npx`.")
    if transport == "http" and not url.strip():
        raise RegistryError("An http server needs a URL.")

    servers = _load()
    if any(s["name"].lower() == name.lower() for s in servers):
        raise RegistryError(f"A server called “{name}” is already registered.")

    entry = {
        "id": str(uuid.uuid4()), "name": name[:100], "transport": transport,
        "command": command.strip(), "args": args or [], "url": url.strip(),
        "env": env or {}, "added_at": datetime.utcnow().isoformat(),
    }
    servers.append(entry)
    _save(servers)
    logger.info("mcp_server_added", name=name, transport=transport)
    return entry


def remove_server(server_id: str) -> bool:
    servers = _load()
    remaining = [s for s in servers if s["id"] != server_id]
    if len(remaining) == len(servers):
        return False
    _save(remaining)
    _connections.pop(server_id, None)
    return True


def _build(entry: Dict[str, Any]) -> MCPClient:
    if entry["transport"] == "stdio":
        return MCPClient.stdio(entry["name"], entry["command"],
                               entry.get("args") or [], entry.get("env") or {})
    return MCPClient.http(entry["name"], entry["url"])


async def connect(db: DatabaseManager, project_id: str, server_id: str,
                  skip_approval: bool = False) -> Dict[str, Any]:
    """Connect to a registered server, asking permission first.

    `skip_approval` exists for tests and for callers that have already gated the
    action; it is never set from an HTTP route.
    """
    entry = get_server(server_id)
    if not entry:
        raise RegistryError("Server not found.")

    existing = _connections.get(server_id)
    if existing and existing.session:
        return {"connected": True, "cached": True,
                "session": _session_dict(existing)}

    if not skip_approval:
        from src.services import inbox_service as inbox

        # A stdio server is a process; an http server is a network peer. The
        # capability named must match what actually happens.
        if entry["transport"] == "stdio":
            capability = "shell.execute"
            target = entry["command"]
            detail = (f"Dobby will start `{entry['command']} "
                      f"{' '.join(entry.get('args') or [])}` and keep it running "
                      "for the session. It can expose tools that read or change "
                      "things on this machine.")
        else:
            capability = "net.fetch"
            target = entry["url"]
            detail = (f"Dobby will connect to {entry['url']} and may send tool "
                      "arguments to it.")

        verdict = await inbox.require(
            db, project_id, capability, target,
            title=f"Connect to the “{entry['name']}” MCP server?",
            detail=detail, risk="high", source="mcp", source_id=server_id,
            timeout=180,
        )
        if not verdict["allowed"]:
            return {"connected": False, "reason": verdict["reason"],
                    "ask_id": verdict.get("ask_id")}

    client = _build(entry)
    try:
        await client.connect()
    except MCPError as e:
        await client.close()
        raise RegistryError(str(e))

    _connections[server_id] = client
    logger.info("mcp_connected", name=entry["name"],
                tools=len(client.session.tools) if client.session else 0)
    return {"connected": True, "cached": False, "session": _session_dict(client)}


def _session_dict(client: MCPClient) -> Dict[str, Any]:
    s = client.session
    if not s:
        return {}
    return {
        "name": s.name, "transport": s.transport, "server_info": s.server_info,
        "capabilities": s.capabilities,
        "tools": [t.to_dict() for t in s.tools],
    }


async def disconnect(server_id: str) -> bool:
    client = _connections.pop(server_id, None)
    if not client:
        return False
    await client.close()
    return True


async def call_tool(db: DatabaseManager, project_id: str, server_id: str,
                    tool: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Invoke a tool on a connected server.

    Connecting was the gated step. Once a server is connected the user has
    already agreed to it running and being talked to, so individual calls are
    not re-prompted — that would be the approval fatigue the Inbox exists to
    avoid. Revoking the grant and disconnecting is the way back out.
    """
    client = _connections.get(server_id)
    if not client or not client.session:
        raise RegistryError("That server is not connected.")
    if not any(t.name == tool for t in client.session.tools):
        available = ", ".join(t.name for t in client.session.tools) or "none"
        raise RegistryError(f"“{tool}” is not offered by this server. Available: {available}")
    try:
        return await client.call_tool(tool, arguments or {})
    except MCPError as e:
        raise RegistryError(str(e))


async def all_tools() -> List[Dict[str, Any]]:
    """Every tool across every connected server, for a unified picker."""
    out: List[Dict[str, Any]] = []
    for server_id, client in _connections.items():
        if not client.session:
            continue
        for t in client.session.tools:
            out.append({**t.to_dict(), "server_id": server_id,
                        "server_name": client.session.name})
    return out


async def shutdown() -> None:
    """Close every connection — called from the app lifespan."""
    for client in list(_connections.values()):
        try:
            await client.close()
        except Exception:
            pass
    _connections.clear()

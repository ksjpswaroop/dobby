"""
Model Context Protocol client (OW rows 57, 31 — Next Task 4).

Dobby already consumes one MCP server (wigolo) through its REST side door.
Speaking MCP properly turns *every* MCP server into a Dobby capability, which
is why this is the highest-leverage item left on the roadmap: it is a week of
work that multiplies what the app can do rather than adding one more feature.

MCP is JSON-RPC 2.0. Two transports matter in practice:

* **stdio** — the server is a child process; frames are newline-delimited JSON
  on its stdin/stdout. This is how nearly every published MCP server ships
  (`npx -y some-server`).
* **http** — JSON-RPC POSTed to one endpoint. Used by remote and self-hosted
  servers, including wigolo's `/mcp`.

Both are implemented here behind one interface, because a caller should not
care how a server happens to be packaged.

Safety: spawning a process and talking to a network host are exactly the
actions the approval gate exists for, so `MCPRegistry` routes connections
through it rather than trusting a config file. Nothing here bypasses that.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx
import structlog

logger = structlog.get_logger()

PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "dobby", "version": "2.0.0"}

CONNECT_TIMEOUT = 30.0
CALL_TIMEOUT = 120.0
MAX_FRAME = 8 * 1024 * 1024      # a runaway server must not exhaust memory


class MCPError(Exception):
    """A protocol or transport failure. Message is user-facing."""


@dataclass
class MCPTool:
    name: str
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "input_schema": self.input_schema}


@dataclass
class MCPSession:
    """A live connection to one server."""

    name: str
    transport: str
    server_info: Dict[str, Any] = field(default_factory=dict)
    capabilities: Dict[str, Any] = field(default_factory=dict)
    tools: List[MCPTool] = field(default_factory=list)


class _Transport:
    async def request(self, method: str, params: Optional[Dict[str, Any]] = None,
                      timeout: float = CALL_TIMEOUT) -> Dict[str, Any]:
        raise NotImplementedError

    async def notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError


class StdioTransport(_Transport):
    """Newline-delimited JSON-RPC over a child process's stdio."""

    def __init__(self, command: str, args: List[str], env: Optional[Dict[str, str]] = None):
        self.command = command
        self.args = args
        self.env = env or {}
        self.proc: Optional[asyncio.subprocess.Process] = None
        self._id = 0
        # One request at a time. MCP allows pipelining, but a lock keeps the
        # read loop trivially correct and no Dobby caller needs the throughput.
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        resolved = shutil.which(self.command)
        if not resolved:
            raise MCPError(
                f"`{self.command}` is not installed or not on PATH. "
                "Most MCP servers run through `npx`, which needs Node.js."
            )
        env = {**os.environ, **self.env}
        try:
            self.proc = await asyncio.create_subprocess_exec(
                resolved, *self.args,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=env, start_new_session=True,
            )
        except OSError as e:
            raise MCPError(f"Could not start `{self.command}`: {e}")

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    async def _send(self, payload: Dict[str, Any]) -> None:
        if not self.proc or not self.proc.stdin:
            raise MCPError("The MCP server is not running.")
        line = json.dumps(payload).encode() + b"\n"
        self.proc.stdin.write(line)
        await self.proc.stdin.drain()

    async def _read_response(self, want_id: int, timeout: float) -> Dict[str, Any]:
        """Read until the matching id arrives, skipping notifications."""
        if not self.proc or not self.proc.stdout:
            raise MCPError("The MCP server is not running.")

        async def pump() -> Dict[str, Any]:
            while True:
                raw = await self.proc.stdout.readline()
                if not raw:
                    stderr = b""
                    if self.proc.stderr:
                        try:
                            stderr = await asyncio.wait_for(self.proc.stderr.read(2000), 1)
                        except asyncio.TimeoutError:
                            pass
                    detail = stderr.decode(errors="replace").strip()
                    raise MCPError(
                        f"The MCP server exited unexpectedly."
                        + (f" It said: {detail[:300]}" if detail else "")
                    )
                if len(raw) > MAX_FRAME:
                    raise MCPError("The MCP server sent an oversized frame.")
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    # Servers commonly log to stdout by mistake; skip noise
                    # rather than dying on it.
                    continue
                if msg.get("id") == want_id:
                    return msg

        try:
            return await asyncio.wait_for(pump(), timeout=timeout)
        except asyncio.TimeoutError:
            raise MCPError(f"The MCP server did not answer within {int(timeout)}s.")

    async def request(self, method: str, params: Optional[Dict[str, Any]] = None,
                      timeout: float = CALL_TIMEOUT) -> Dict[str, Any]:
        async with self._lock:
            rid = self._next_id()
            await self._send({"jsonrpc": "2.0", "id": rid, "method": method,
                              "params": params or {}})
            msg = await self._read_response(rid, timeout)
        if "error" in msg:
            err = msg["error"] or {}
            raise MCPError(f"{method} failed: {err.get('message', 'unknown error')}")
        return msg.get("result") or {}

    async def notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        async with self._lock:
            await self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    async def close(self) -> None:
        if not self.proc:
            return
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            await asyncio.wait_for(self.proc.wait(), timeout=5)
        except (asyncio.TimeoutError, ProcessLookupError):
            try:
                self.proc.kill()
            except ProcessLookupError:
                pass
        finally:
            self.proc = None


class HttpTransport(_Transport):
    """JSON-RPC over a single HTTP endpoint."""

    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None):
        self.url = url.rstrip("/")
        # MCP's Streamable HTTP transport requires the client to advertise that
        # it accepts *both* a plain JSON reply and an SSE stream; a server is
        # entitled to answer 406 without it, which is exactly what wigolo does.
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **(headers or {}),
        }
        self._id = 0
        self._session_id: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None

    @staticmethod
    def _decode(response: httpx.Response) -> Any:
        """Read a reply that may be plain JSON or a single SSE frame."""
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" not in content_type:
            return response.json()
        # One JSON-RPC response arrives as `data: {...}` lines; take the first.
        for line in response.text.splitlines():
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload:
                    return json.loads(payload)
        raise MCPError("The MCP server sent an empty event stream.")

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=CALL_TIMEOUT)

    async def request(self, method: str, params: Optional[Dict[str, Any]] = None,
                      timeout: float = CALL_TIMEOUT) -> Dict[str, Any]:
        if not self._client:
            await self.start()
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method,
                   "params": params or {}}
        headers = dict(self.headers)
        # The server assigns a session id on initialize and expects it back on
        # every subsequent request.
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        try:
            r = await self._client.post(self.url, json=payload, headers=headers,
                                        timeout=timeout)
            r.raise_for_status()
            assigned = r.headers.get("mcp-session-id")
            if assigned:
                self._session_id = assigned
            msg = self._decode(r)
        except httpx.ConnectError:
            raise MCPError(f"Could not reach the MCP server at {self.url}.")
        except httpx.HTTPStatusError as e:
            raise MCPError(f"The MCP server returned {e.response.status_code}.")
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            raise MCPError(f"The MCP server sent an unusable response: {e}")

        if isinstance(msg, dict) and "error" in msg:
            err = msg["error"] or {}
            raise MCPError(f"{method} failed: {err.get('message', 'unknown error')}")
        return (msg or {}).get("result") or {}

    async def notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        # Notifications carry no id and expect no reply; failure is not fatal.
        if not self._client:
            await self.start()
        headers = dict(self.headers)
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        try:
            await self._client.post(
                self.url, headers=headers,
                json={"jsonrpc": "2.0", "method": method, "params": params or {}},
                timeout=10,
            )
        except httpx.HTTPError:
            pass

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


class MCPClient:
    """One connection: handshake, discover tools, call them."""

    def __init__(self, name: str, transport: _Transport, kind: str):
        self.name = name
        self.transport = transport
        self.kind = kind
        self.session: Optional[MCPSession] = None

    @classmethod
    def stdio(cls, name: str, command: str, args: Optional[List[str]] = None,
              env: Optional[Dict[str, str]] = None) -> "MCPClient":
        return cls(name, StdioTransport(command, args or [], env), "stdio")

    @classmethod
    def http(cls, name: str, url: str,
             headers: Optional[Dict[str, str]] = None) -> "MCPClient":
        return cls(name, HttpTransport(url, headers), "http")

    async def connect(self) -> MCPSession:
        """Handshake, then discover what the server offers."""
        start = getattr(self.transport, "start", None)
        if start:
            await start()

        result = await self.transport.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"roots": {"listChanged": False}, "sampling": {}},
                "clientInfo": CLIENT_INFO,
            },
            timeout=CONNECT_TIMEOUT,
        )
        # Required by the spec: the server may not serve requests until told
        # the handshake is done.
        await self.transport.notify("notifications/initialized")

        self.session = MCPSession(
            name=self.name, transport=self.kind,
            server_info=result.get("serverInfo") or {},
            capabilities=result.get("capabilities") or {},
        )
        try:
            self.session.tools = await self.list_tools()
        except MCPError as e:
            # A server with no tools capability is still a valid connection.
            logger.info("mcp_no_tools", server=self.name, reason=str(e))
        return self.session

    async def list_tools(self) -> List[MCPTool]:
        result = await self.transport.request("tools/list", {}, timeout=CONNECT_TIMEOUT)
        tools: List[MCPTool] = []
        for t in result.get("tools") or []:
            if not isinstance(t, dict) or not t.get("name"):
                continue
            tools.append(MCPTool(
                name=str(t["name"]),
                description=str(t.get("description") or "")[:1000],
                input_schema=t.get("inputSchema") or t.get("input_schema") or {},
            ))
        return tools

    async def call_tool(self, tool: str, arguments: Optional[Dict[str, Any]] = None,
                        timeout: float = CALL_TIMEOUT) -> Dict[str, Any]:
        """Invoke a tool and normalise the reply into text plus raw content."""
        result = await self.transport.request(
            "tools/call", {"name": tool, "arguments": arguments or {}}, timeout=timeout
        )
        content = result.get("content") or []
        text_parts = [
            c.get("text", "") for c in content
            if isinstance(c, dict) and c.get("type") == "text"
        ]
        return {
            "tool": tool,
            "is_error": bool(result.get("isError")),
            "text": "\n".join(p for p in text_parts if p).strip(),
            "content": content,
        }

    async def close(self) -> None:
        await self.transport.close()

    async def __aenter__(self) -> "MCPClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

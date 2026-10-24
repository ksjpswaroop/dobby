"""
MCP client.

The protocol work is tested against a real JSON-RPC server implemented in the
test itself, rather than a mock of our own client — a mock would happily agree
with a wrong implementation. What matters is that we speak the wire format a
genuine MCP server expects, and that connecting is gated.
"""

import asyncio
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_mcp_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.main import app  # noqa: E402
from src.mcp import registry  # noqa: E402
from src.mcp.client import MCPClient, MCPError, MCPTool  # noqa: E402

PROJECT = "default-project"

# A minimal but genuine MCP server: reads newline-delimited JSON-RPC on stdin,
# answers initialize / tools/list / tools/call.
FAKE_SERVER = r'''
import json, sys
TOOLS = [{"name": "echo", "description": "Echo text back",
          "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}}]
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except Exception:
        continue
    method, rid = msg.get("method"), msg.get("id")
    if rid is None:
        continue                      # a notification; nothing to answer
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05",
                  "serverInfo": {"name": "fake", "version": "1.0"},
                  "capabilities": {"tools": {}}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        args = (msg.get("params") or {}).get("arguments") or {}
        name = (msg.get("params") or {}).get("name")
        if name != "echo":
            print(json.dumps({"jsonrpc": "2.0", "id": rid,
                              "error": {"code": -32602, "message": "no such tool"}}),
                  flush=True)
            continue
        result = {"content": [{"type": "text", "text": args.get("text", "")}]}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": rid,
                          "error": {"code": -32601, "message": "method not found"}}),
              flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}), flush=True)
'''


@pytest.fixture(scope="module")
def server_script(tmp_path_factory):
    p = tmp_path_factory.mktemp("mcp") / "fake_server.py"
    p.write_text(FAKE_SERVER)
    return str(p)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(_TMP_DB + suffix)
        except OSError:
            pass


@pytest.fixture
def db(client):
    return app.state.db


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Never touch the user's real ~/.dobby/mcp_servers.json."""
    monkeypatch.setattr(registry, "CONFIG_PATH", tmp_path / "mcp_servers.json")
    registry._connections.clear()
    yield
    registry._connections.clear()


class TestStdioProtocol:
    @pytest.mark.asyncio
    async def test_handshake_reports_the_server_identity(self, server_script):
        c = MCPClient.stdio("fake", sys.executable, [server_script])
        try:
            session = await c.connect()
            assert session.server_info["name"] == "fake"
            assert session.transport == "stdio"
        finally:
            await c.close()

    @pytest.mark.asyncio
    async def test_tools_are_discovered_with_their_schema(self, server_script):
        async with MCPClient.stdio("fake", sys.executable, [server_script]) as c:
            names = [t.name for t in c.session.tools]
            assert names == ["echo"]
            assert c.session.tools[0].input_schema["type"] == "object"

    @pytest.mark.asyncio
    async def test_calling_a_tool_returns_its_text(self, server_script):
        async with MCPClient.stdio("fake", sys.executable, [server_script]) as c:
            out = await c.call_tool("echo", {"text": "round trip"})
            assert out["text"] == "round trip" and out["is_error"] is False

    @pytest.mark.asyncio
    async def test_a_server_error_becomes_a_readable_exception(self, server_script):
        async with MCPClient.stdio("fake", sys.executable, [server_script]) as c:
            with pytest.raises(MCPError, match="no such tool"):
                await c.call_tool("nope", {})

    @pytest.mark.asyncio
    async def test_a_missing_command_explains_itself(self):
        c = MCPClient.stdio("ghost", "definitely-not-installed-xyz", [])
        with pytest.raises(MCPError, match="not installed"):
            await c.connect()

    @pytest.mark.asyncio
    async def test_concurrent_calls_do_not_cross_responses(self, server_script):
        """The read loop must match replies to requests, not to arrival order."""
        async with MCPClient.stdio("fake", sys.executable, [server_script]) as c:
            results = await asyncio.gather(*(
                c.call_tool("echo", {"text": f"msg-{i}"}) for i in range(5)
            ))
            assert [r["text"] for r in results] == [f"msg-{i}" for i in range(5)]


class TestStreamableHttp:
    """Real servers use the Streamable HTTP transport, which is picky."""

    def test_accept_header_advertises_both_reply_forms(self):
        from src.mcp.client import HttpTransport

        t = HttpTransport("http://x.test/mcp")
        accept = t.headers["Accept"]
        # Omitting either earns a 406 from a spec-compliant server — observed
        # live against wigolo.
        assert "application/json" in accept and "text/event-stream" in accept

    def test_a_plain_json_reply_is_decoded(self):
        from src.mcp.client import HttpTransport
        import httpx

        r = httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"ok": True}},
                           headers={"content-type": "application/json"})
        assert HttpTransport._decode(r)["result"]["ok"] is True

    def test_an_sse_framed_reply_is_decoded(self):
        from src.mcp.client import HttpTransport
        import httpx

        body = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n'
        r = httpx.Response(200, text=body,
                           headers={"content-type": "text/event-stream"})
        assert HttpTransport._decode(r)["result"]["ok"] is True

    def test_an_empty_stream_is_a_clear_error(self):
        from src.mcp.client import HttpTransport, MCPError
        import httpx

        r = httpx.Response(200, text="event: ping\n\n",
                           headers={"content-type": "text/event-stream"})
        with pytest.raises(MCPError, match="empty event stream"):
            HttpTransport._decode(r)


class TestRegistry:
    def test_add_and_list(self):
        entry = registry.add_server("fake", "stdio", command="python3", args=["-c", "pass"])
        assert entry["id"]
        assert any(s["name"] == "fake" for s in registry.list_servers())

    def test_duplicate_names_are_refused(self):
        registry.add_server("dupe", "stdio", command="python3")
        with pytest.raises(registry.RegistryError, match="already registered"):
            registry.add_server("dupe", "stdio", command="python3")

    @pytest.mark.parametrize("kwargs,fragment", [
        ({"name": "", "transport": "stdio", "command": "x"}, "a name"),
        ({"name": "x", "transport": "carrier-pigeon"}, "stdio' or 'http"),
        ({"name": "x", "transport": "stdio", "command": ""}, "needs a command"),
        ({"name": "x", "transport": "http", "url": ""}, "needs a URL"),
    ])
    def test_invalid_definitions_are_refused(self, kwargs, fragment):
        with pytest.raises(registry.RegistryError, match=fragment):
            registry.add_server(**kwargs)

    def test_remove(self):
        entry = registry.add_server("gone", "stdio", command="python3")
        assert registry.remove_server(entry["id"]) is True
        assert registry.remove_server(entry["id"]) is False

    def test_config_survives_a_reload(self, tmp_path, monkeypatch):
        registry.add_server("persisted", "http", url="http://x.test/mcp")
        # Simulate a restart by re-reading from disk.
        assert any(s["name"] == "persisted" for s in registry.list_servers())


class TestApprovalGate:
    @pytest.mark.asyncio
    async def test_connecting_is_refused_without_approval(self, db, server_script, monkeypatch):
        """A config file is not consent."""
        from src.services import inbox_service as inbox

        async def deny(*a, **k):
            return {"allowed": False, "reason": "denied", "ask_id": "x"}

        monkeypatch.setattr(inbox, "require", deny)
        entry = registry.add_server("gated", "stdio", command=sys.executable,
                                    args=[server_script])
        out = await registry.connect(db, PROJECT, entry["id"])
        assert out["connected"] is False and out["reason"] == "denied"

    @pytest.mark.asyncio
    async def test_an_approved_connection_discovers_tools(self, db, server_script, monkeypatch):
        from src.services import inbox_service as inbox

        async def approve(*a, **k):
            return {"allowed": True, "reason": "approved", "ask_id": "x"}

        monkeypatch.setattr(inbox, "require", approve)
        entry = registry.add_server("approved", "stdio", command=sys.executable,
                                    args=[server_script])
        out = await registry.connect(db, PROJECT, entry["id"])
        assert out["connected"] is True
        assert [t["name"] for t in out["session"]["tools"]] == ["echo"]
        await registry.disconnect(entry["id"])

    @pytest.mark.asyncio
    async def test_a_stdio_server_asks_for_shell_not_network(self, db, server_script, monkeypatch):
        """The capability named must match what actually happens."""
        seen = {}
        from src.services import inbox_service as inbox

        async def capture(db_, project, capability, target, **k):
            seen["capability"] = capability
            return {"allowed": False, "reason": "denied"}

        monkeypatch.setattr(inbox, "require", capture)
        entry = registry.add_server("stdio-cap", "stdio", command=sys.executable,
                                    args=[server_script])
        await registry.connect(db, PROJECT, entry["id"])
        assert seen["capability"] == "shell.execute"

    @pytest.mark.asyncio
    async def test_an_http_server_asks_for_network(self, db, monkeypatch):
        seen = {}
        from src.services import inbox_service as inbox

        async def capture(db_, project, capability, target, **k):
            seen["capability"] = capability
            return {"allowed": False, "reason": "denied"}

        monkeypatch.setattr(inbox, "require", capture)
        entry = registry.add_server("http-cap", "http", url="http://x.test/mcp")
        await registry.connect(db, PROJECT, entry["id"])
        assert seen["capability"] == "net.fetch"


class TestToolCalls:
    @pytest.mark.asyncio
    async def test_calling_through_the_registry(self, db, server_script):
        entry = registry.add_server("callable", "stdio", command=sys.executable,
                                    args=[server_script])
        await registry.connect(db, PROJECT, entry["id"], skip_approval=True)
        out = await registry.call_tool(db, PROJECT, entry["id"], "echo", {"text": "hi"})
        assert out["text"] == "hi"
        await registry.disconnect(entry["id"])

    @pytest.mark.asyncio
    async def test_an_unknown_tool_lists_what_is_available(self, db, server_script):
        entry = registry.add_server("known", "stdio", command=sys.executable,
                                    args=[server_script])
        await registry.connect(db, PROJECT, entry["id"], skip_approval=True)
        with pytest.raises(registry.RegistryError, match="Available: echo"):
            await registry.call_tool(db, PROJECT, entry["id"], "nope", {})
        await registry.disconnect(entry["id"])

    @pytest.mark.asyncio
    async def test_calling_a_disconnected_server_is_refused(self, db):
        entry = registry.add_server("offline", "stdio", command=sys.executable)
        with pytest.raises(registry.RegistryError, match="not connected"):
            await registry.call_tool(db, PROJECT, entry["id"], "echo", {})

    @pytest.mark.asyncio
    async def test_all_tools_spans_every_connected_server(self, db, server_script):
        a = registry.add_server("srv-a", "stdio", command=sys.executable, args=[server_script])
        b = registry.add_server("srv-b", "stdio", command=sys.executable, args=[server_script])
        await registry.connect(db, PROJECT, a["id"], skip_approval=True)
        await registry.connect(db, PROJECT, b["id"], skip_approval=True)
        tools = await registry.all_tools()
        assert {t["server_name"] for t in tools} == {"srv-a", "srv-b"}
        await registry.shutdown()


class TestApi:
    def test_servers_endpoint_offers_suggestions(self, client):
        r = client.get("/api/v1/mcp/servers")
        assert r.status_code == 200
        assert any(s["name"] == "wigolo" for s in r.json()["suggested"])

    def test_add_and_remove_over_http(self, client):
        r = client.post("/api/v1/mcp/servers", json={
            "name": "via-api", "transport": "http", "url": "http://x.test/mcp",
        })
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        assert client.delete(f"/api/v1/mcp/servers/{sid}").status_code == 200
        assert client.delete(f"/api/v1/mcp/servers/{sid}").status_code == 404

    def test_an_invalid_definition_is_a_400(self, client):
        r = client.post("/api/v1/mcp/servers",
                        json={"name": "bad", "transport": "stdio", "command": ""})
        assert r.status_code == 400

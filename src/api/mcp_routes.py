"""MCP API — registered servers, connections, and tool calls."""

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.db.schema import DatabaseManager
from src.mcp import registry

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/mcp", tags=["MCP"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class ServerAdd(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    transport: str = "stdio"
    command: str = ""
    args: List[str] = Field(default_factory=list)
    url: str = ""
    env: Dict[str, str] = Field(default_factory=dict)


class ToolCall(BaseModel):
    project_id: str = "default-project"
    tool: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


@router.get("/servers")
async def list_servers():
    return {"servers": registry.list_servers(), "suggested": registry.SUGGESTED}


@router.post("/servers")
async def add_server(req: ServerAdd):
    try:
        return registry.add_server(req.name, req.transport, req.command,
                                   req.args, req.url, req.env)
    except registry.RegistryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/servers/{server_id}")
async def remove_server(server_id: str):
    await registry.disconnect(server_id)
    if not registry.remove_server(server_id):
        raise HTTPException(status_code=404, detail="Server not found")
    return {"success": True}


@router.post("/servers/{server_id}/connect")
async def connect(server_id: str, project_id: str = "default-project",
                  db: DatabaseManager = Depends(get_db)):
    """Connect, asking permission first — a config file is not consent."""
    try:
        return await registry.connect(db, project_id, server_id)
    except registry.RegistryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/servers/{server_id}/disconnect")
async def disconnect(server_id: str):
    return {"success": await registry.disconnect(server_id)}


@router.get("/tools")
async def tools():
    """Every tool across every connected server."""
    return {"tools": await registry.all_tools()}


@router.post("/servers/{server_id}/call")
async def call(server_id: str, req: ToolCall,
               db: DatabaseManager = Depends(get_db)):
    try:
        return await registry.call_tool(db, req.project_id, server_id,
                                        req.tool, req.arguments)
    except registry.RegistryError as e:
        raise HTTPException(status_code=400, detail=str(e))

"""
Mind-map API — Phase 1 (CRUD + canvas).

Structural rules live in the service layer; these handlers translate them into
HTTP. An illegal move (a cycle) returns 400 so the canvas can revert its
optimistic update rather than silently corrupting the tree.
"""

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from src.db.schema import DatabaseManager
from src.services import mindmap_service as svc

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/mindmaps", tags=["Mind Map"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class MapCreate(BaseModel):
    project_id: str
    title: str = "Untitled map"
    session_id: Optional[str] = None


class MapUpdate(BaseModel):
    title: Optional[str] = None
    root_node_id: Optional[str] = None
    viewport_state: Optional[Dict[str, Any]] = None


class NodeCreate(BaseModel):
    title: str
    parent_id: Optional[str] = None
    node_type: str = "Idea"
    description: str = ""
    color: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class NodeUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    node_type: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None


class NodeMove(BaseModel):
    new_parent_id: Optional[str] = None
    sort_order: Optional[int] = None


class EdgeCreate(BaseModel):
    source_node_id: str
    target_node_id: str
    relation_type: str = "related"


class SnapshotSave(BaseModel):
    snapshot: Dict[str, Any]
    label: str = ""


# ---------------------------------------------------------------------------
# Maps
# ---------------------------------------------------------------------------
@router.get("/types")
async def node_types() -> Dict[str, List[str]]:
    return {"node_types": svc.NODE_TYPES}


@router.post("")
async def create_map(req: MapCreate, db: DatabaseManager = Depends(get_db)):
    return svc.create_map(db, req.project_id, req.title, req.session_id)


@router.get("/project/{project_id}")
async def list_maps(project_id: str, db: DatabaseManager = Depends(get_db)):
    return {"maps": svc.list_maps(db, project_id)}


@router.get("/map/{map_id}")
async def get_map(map_id: str, db: DatabaseManager = Depends(get_db)):
    m = svc.get_map(db, map_id)
    if not m:
        raise HTTPException(status_code=404, detail="Mind map not found")
    return m


@router.get("/map/{map_id}/tree")
async def get_tree(map_id: str, db: DatabaseManager = Depends(get_db)):
    tree = svc.get_map_tree(db, map_id)
    if not tree:
        raise HTTPException(status_code=404, detail="Mind map not found")
    return tree


@router.patch("/map/{map_id}")
async def update_map(map_id: str, req: MapUpdate, db: DatabaseManager = Depends(get_db)):
    m = svc.update_map(db, map_id, **req.model_dump(exclude_none=True))
    if not m:
        raise HTTPException(status_code=404, detail="Mind map not found")
    return m


@router.post("/map/{map_id}/duplicate")
async def duplicate_map(map_id: str, db: DatabaseManager = Depends(get_db)):
    m = svc.duplicate_map(db, map_id)
    if not m:
        raise HTTPException(status_code=404, detail="Mind map not found")
    return m


@router.delete("/map/{map_id}")
async def delete_map(map_id: str, db: DatabaseManager = Depends(get_db)):
    if not svc.delete_map(db, map_id):
        raise HTTPException(status_code=404, detail="Mind map not found")
    return {"success": True}


@router.post("/map/{map_id}/validate")
async def validate(map_id: str, db: DatabaseManager = Depends(get_db)):
    return {"problems": svc.validate_tree(db, map_id)}


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
@router.post("/map/{map_id}/nodes")
async def create_node(map_id: str, req: NodeCreate, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.create_node(
            db, map_id, req.title, req.parent_id, req.node_type,
            description=req.description, color=req.color, metadata=req.metadata,
        )
    except svc.MindMapError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/nodes/{node_id}")
async def update_node(node_id: str, req: NodeUpdate, db: DatabaseManager = Depends(get_db)):
    n = svc.update_node(db, node_id, **req.model_dump(exclude_none=True))
    if not n:
        raise HTTPException(status_code=404, detail="Node not found")
    return n


@router.put("/nodes/{node_id}/move")
async def move_node(node_id: str, req: NodeMove, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.move_node(db, node_id, req.new_parent_id, req.sort_order)
    except svc.MindMapError as e:
        # 400 (not 500): the canvas reverts its optimistic move and shows this.
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/nodes/{node_id}")
async def delete_node(node_id: str, db: DatabaseManager = Depends(get_db)):
    removed = svc.delete_node(db, node_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Node not found")
    return {"deleted": removed}


@router.post("/nodes/{node_id}/duplicate")
async def duplicate_node(node_id: str, db: DatabaseManager = Depends(get_db)):
    n = svc.duplicate_node(db, node_id)
    if not n:
        raise HTTPException(status_code=404, detail="Node not found")
    return n


# ---------------------------------------------------------------------------
# Edges & snapshots
# ---------------------------------------------------------------------------
@router.post("/map/{map_id}/edges")
async def create_edge(map_id: str, req: EdgeCreate, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.create_edge(db, map_id, req.source_node_id, req.target_node_id,
                               req.relation_type)
    except svc.MindMapError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/edges/{edge_id}")
async def delete_edge(edge_id: str, db: DatabaseManager = Depends(get_db)):
    if not svc.delete_edge(db, edge_id):
        raise HTTPException(status_code=404, detail="Edge not found")
    return {"success": True}


@router.post("/map/{map_id}/snapshots")
async def save_snapshot(map_id: str, req: SnapshotSave, db: DatabaseManager = Depends(get_db)):
    return {"id": svc.save_snapshot(db, map_id, req.snapshot, req.label)}


@router.get("/map/{map_id}/snapshots")
async def list_snapshots(map_id: str, db: DatabaseManager = Depends(get_db)):
    return {"snapshots": svc.list_snapshots(db, map_id)}


@router.post("/map/{map_id}/restore/{snapshot_id}")
async def restore_snapshot(map_id: str, snapshot_id: str, db: DatabaseManager = Depends(get_db)):
    """Rebuild a map from a snapshot — this is what makes undo able to bring
    deleted nodes back, which a field-by-field replay cannot do."""
    try:
        return svc.restore_snapshot(db, map_id, snapshot_id)
    except svc.MindMapError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------------------------
# Export / import (Phase 3)
# ---------------------------------------------------------------------------
class ImportRequest(BaseModel):
    data: Dict[str, Any]


@router.get("/map/{map_id}/export/json")
async def export_json(map_id: str, db: DatabaseManager = Depends(get_db)):
    from src.services import mindmap_export as ex

    try:
        return ex.export_json(db, map_id)
    except ex.ImportError_ as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/map/{map_id}/export/markdown", response_class=PlainTextResponse)
async def export_markdown(map_id: str, db: DatabaseManager = Depends(get_db)):
    from src.services import mindmap_export as ex

    try:
        return PlainTextResponse(ex.export_markdown(db, map_id), media_type="text/markdown")
    except ex.ImportError_ as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/map/{map_id}/export/mermaid", response_class=PlainTextResponse)
async def export_mermaid(map_id: str, db: DatabaseManager = Depends(get_db)):
    from src.services import mindmap_export as ex

    try:
        return PlainTextResponse(ex.export_mermaid(db, map_id), media_type="text/plain")
    except ex.ImportError_ as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/map/{map_id}/export/outline", response_class=PlainTextResponse)
async def export_outline(map_id: str, db: DatabaseManager = Depends(get_db)):
    """Heading markdown — the interchange format other mind-map tools read."""
    from src.services import mindmap_outline as ol

    tree = svc.get_map_tree(db, map_id)
    if not tree:
        raise HTTPException(status_code=404, detail="Mind map not found")
    return PlainTextResponse(ol.to_outline(tree), media_type="text/markdown")


@router.post("/import/{project_id}")
async def import_map(project_id: str, req: ImportRequest,
                     db: DatabaseManager = Depends(get_db)):
    from src.services import mindmap_export as ex

    try:
        return ex.import_json(db, project_id, req.data)
    except ex.ImportError_ as e:
        # 400 with a field-level message so the UI can show what's wrong.
        raise HTTPException(status_code=400, detail=str(e))


class OutlineImport(BaseModel):
    outline: str = Field(..., description="Heading or bullet markdown")
    title: Optional[str] = None


@router.post("/import/{project_id}/outline")
async def import_outline(project_id: str, req: OutlineImport,
                         db: DatabaseManager = Depends(get_db)):
    """Build a map from markdown pasted out of any other tool."""
    from src.services import mindmap_outline as ol

    try:
        return ol.import_outline(db, project_id, req.outline, req.title)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class OutlineReplace(BaseModel):
    outline: str


@router.put("/map/{map_id}/outline")
async def replace_outline(map_id: str, req: OutlineReplace,
                          db: DatabaseManager = Depends(get_db)):
    """Rewrite a map from edited outline text. Snapshots first, so undo works."""
    from src.services import mindmap_outline as ol

    try:
        result = ol.replace_from_outline(db, map_id, req.outline)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "Replace failed"))
    return result


# ---------------------------------------------------------------------------
# AI (Phase 2)
# ---------------------------------------------------------------------------
class GenerateRequest(BaseModel):
    project_id: str
    topic: Optional[str] = None


class ApplyRegroup(BaseModel):
    proposed: Dict[str, Any]


@router.post("/ai/generate")
async def ai_generate(req: GenerateRequest, db: DatabaseManager = Depends(get_db)):
    from src.services import mindmap_ai

    try:
        result = await mindmap_ai.generate_map(db, req.project_id, req.topic)
    except mindmap_ai.AIUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    if not result.get("success"):
        raise HTTPException(status_code=422, detail=result.get("error", "Generation failed"))
    return result


@router.post("/ai/expand/{node_id}")
async def ai_expand(node_id: str, db: DatabaseManager = Depends(get_db)):
    from src.services import mindmap_ai

    try:
        result = await mindmap_ai.expand_node(db, node_id)
    except mindmap_ai.AIUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    if not result.get("success"):
        raise HTTPException(status_code=422, detail=result.get("error", "Expansion failed"))
    return result


@router.post("/ai/regroup/{map_id}")
async def ai_regroup(map_id: str, db: DatabaseManager = Depends(get_db)):
    """Propose a reorganization. Persists nothing."""
    from src.services import mindmap_ai

    try:
        result = await mindmap_ai.regroup_map(db, map_id)
    except mindmap_ai.AIUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    if not result.get("success"):
        raise HTTPException(status_code=422, detail=result.get("error", "Regroup failed"))
    return result


class ChatEdit(BaseModel):
    instruction: str = Field(..., min_length=1, max_length=1000)


@router.post("/ai/chat/{map_id}")
async def ai_chat_edit(map_id: str, req: ChatEdit, db: DatabaseManager = Depends(get_db)):
    """Edit a map in natural language. Applies immediately; snapshotted for undo."""
    from src.services import mindmap_ai

    try:
        result = await mindmap_ai.chat_edit(db, map_id, req.instruction)
    except mindmap_ai.AIUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    if not result.get("success"):
        raise HTTPException(status_code=422, detail=result.get("error", "Edit failed"))
    return result


@router.post("/ai/regroup/{map_id}/apply")
async def ai_regroup_apply(map_id: str, req: ApplyRegroup,
                           db: DatabaseManager = Depends(get_db)):
    from src.services import mindmap_ai

    result = mindmap_ai.apply_regroup(db, map_id, req.proposed)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "Apply failed"))
    return result

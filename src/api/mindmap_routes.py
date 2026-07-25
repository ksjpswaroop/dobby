"""
Mind-map API — Phase 1 (CRUD + canvas).

Structural rules live in the service layer; these handlers translate them into
HTTP. An illegal move (a cycle) returns 400 so the canvas can revert its
optimistic update rather than silently corrupting the tree.
"""

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
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

"""Work Graph API — how goals, projects, decisions and skills connect."""

from fastapi import APIRouter, Depends, HTTPException

from src.db.schema import DatabaseManager
from src.services import workgraph_service as svc

router = APIRouter(prefix="/api/v1/workgraph", tags=["Work Graph"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


@router.get("/meta")
async def meta():
    return {"node_types": list(svc.NODE_TYPES), "edge_types": list(svc.EDGE_TYPES)}


@router.get("/{project_id}")
async def graph(project_id: str, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.build(db, project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{project_id}/node/{node_id}")
async def node_detail(project_id: str, node_id: str,
                      db: DatabaseManager = Depends(get_db)):
    try:
        return svc.node_detail(db, project_id, node_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

"""Living-documents API (100-Day Roadmap, Phase 2: Days 11-20)."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.db.document_models import DOC_STATUSES
from src.db.schema import DatabaseManager
from src.services import document_ai as ai
from src.services import document_service as svc

router = APIRouter(prefix="/api/v1/documents", tags=["Documents"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class SaveContent(BaseModel):
    content: str
    title: Optional[str] = None


class StatusChange(BaseModel):
    status: str


class TagAdd(BaseModel):
    project_id: str
    name: str = Field(..., min_length=1, max_length=60)
    color: str = "neutral"


class CommentCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)
    start_offset: Optional[int] = None
    end_offset: Optional[int] = None
    parent_id: Optional[str] = None


class SectionRegen(BaseModel):
    section_index: int
    instruction: str = ""
    model: str = ""


class RefinePreview(BaseModel):
    content: str
    selection: str
    action: str
    tone: str = "plain"
    model: str = ""


class RefineApply(BaseModel):
    start_offset: int
    end_offset: int
    replacement: str


class DocTypeCreate(BaseModel):
    project_id: str
    name: str = Field(..., min_length=1, max_length=120)
    description: str = ""
    sections: List[str] = Field(default_factory=list)
    prompt: str = ""
    verification_rules: Dict[str, Any] = Field(default_factory=dict)


@router.get("/meta")
async def meta():
    return {
        "statuses": list(DOC_STATUSES),
        "refine_actions": list(ai.REFINE_ACTIONS),
        "tones": list(ai.TONES),
    }


# --- Document + versions -----------------------------------------------------
@router.get("/{node_id}")
async def get_document(node_id: str, db: DatabaseManager = Depends(get_db)):
    doc = svc.get_document(db, node_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.put("/{node_id}")
async def save_document(node_id: str, req: SaveContent,
                        db: DatabaseManager = Depends(get_db)):
    try:
        return svc.save_content(db, node_id, req.content, req.title)
    except svc.DocumentError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{node_id}/versions")
async def list_versions(node_id: str, db: DatabaseManager = Depends(get_db)):
    return {"versions": svc.list_versions(db, node_id)}


@router.get("/versions/{version_id}")
async def get_version(version_id: str, db: DatabaseManager = Depends(get_db)):
    v = svc.get_version(db, version_id)
    if not v:
        raise HTTPException(status_code=404, detail="Version not found")
    return v


@router.get("/{node_id}/versions/{version_id}/diff")
async def diff_version(node_id: str, version_id: str,
                       db: DatabaseManager = Depends(get_db)):
    try:
        return svc.diff_version(db, node_id, version_id)
    except svc.DocumentError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{node_id}/versions/{version_id}/restore")
async def restore_version(node_id: str, version_id: str,
                          db: DatabaseManager = Depends(get_db)):
    try:
        return svc.restore_version(db, node_id, version_id)
    except svc.DocumentError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Status ------------------------------------------------------------------
@router.post("/{node_id}/status")
async def set_status(node_id: str, req: StatusChange,
                     db: DatabaseManager = Depends(get_db)):
    try:
        return svc.set_status(db, node_id, req.status)
    except svc.DocumentError as e:
        code = 404 if "not found" in str(e).lower() else 409
        raise HTTPException(status_code=code, detail=str(e))


# --- Links -------------------------------------------------------------------
@router.get("/{node_id}/links")
async def links(node_id: str, project_id: str,
                db: DatabaseManager = Depends(get_db)):
    try:
        return svc.resolve_links(db, project_id, node_id)
    except svc.DocumentError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Tags --------------------------------------------------------------------
@router.get("/tags/{project_id}")
async def list_tags(project_id: str, db: DatabaseManager = Depends(get_db)):
    return {"tags": svc.list_tags(db, project_id)}


@router.get("/tags/{project_id}/{tag_name}")
async def find_by_tag(project_id: str, tag_name: str,
                      db: DatabaseManager = Depends(get_db)):
    return {"documents": svc.find_by_tag(db, project_id, tag_name)}


@router.post("/{node_id}/tags")
async def add_tag(node_id: str, req: TagAdd, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.add_tag(db, req.project_id, node_id, req.name, req.color)
    except svc.DocumentError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{node_id}/tags/{tag_id}")
async def remove_tag(node_id: str, tag_id: str, db: DatabaseManager = Depends(get_db)):
    return svc.remove_tag(db, node_id, tag_id)


# --- Comments ----------------------------------------------------------------
@router.get("/{node_id}/comments")
async def list_comments(node_id: str, include_resolved: bool = True,
                        db: DatabaseManager = Depends(get_db)):
    return {"comments": svc.list_comments(db, node_id, include_resolved)}


@router.post("/{node_id}/comments")
async def add_comment(node_id: str, req: CommentCreate,
                      db: DatabaseManager = Depends(get_db)):
    try:
        return svc.add_comment(db, node_id, req.body, req.start_offset,
                               req.end_offset, req.parent_id)
    except svc.DocumentError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/comments/{comment_id}/resolve")
async def resolve_comment(comment_id: str, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.set_comment_resolved(db, comment_id, True)
    except svc.DocumentError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/comments/{comment_id}/reopen")
async def reopen_comment(comment_id: str, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.set_comment_resolved(db, comment_id, False)
    except svc.DocumentError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/comments/{comment_id}")
async def delete_comment(comment_id: str, db: DatabaseManager = Depends(get_db)):
    if not svc.delete_comment(db, comment_id):
        raise HTTPException(status_code=404, detail="Comment not found")
    return {"success": True}


# --- AI ----------------------------------------------------------------------
@router.post("/{node_id}/regenerate-section")
async def regenerate_section(node_id: str, req: SectionRegen,
                             db: DatabaseManager = Depends(get_db)):
    try:
        return await ai.regenerate_section(db, node_id, req.section_index,
                                           req.instruction, req.model)
    except ai.DocumentAIError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/refine/preview")
async def refine_preview(req: RefinePreview):
    try:
        return await ai.preview_refine(req.content, req.selection, req.action,
                                       req.tone, req.model)
    except ai.DocumentAIError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{node_id}/refine/apply")
async def refine_apply(node_id: str, req: RefineApply,
                       db: DatabaseManager = Depends(get_db)):
    try:
        return ai.apply_refine(db, node_id, req.start_offset, req.end_offset,
                               req.replacement)
    except ai.DocumentAIError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{node_id}/summarize")
async def summarize(node_id: str, model: str = "",
                    db: DatabaseManager = Depends(get_db)):
    try:
        return await ai.summarize(db, node_id, model)
    except ai.DocumentAIError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Custom document types ---------------------------------------------------
@router.get("/types/{project_id}")
async def list_types(project_id: str, db: DatabaseManager = Depends(get_db)):
    return {"types": svc.list_document_types(db, project_id)}


@router.post("/types")
async def create_type(req: DocTypeCreate, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.create_document_type(db, req.project_id, req.name, req.sections,
                                        req.prompt, req.description,
                                        req.verification_rules)
    except svc.DocumentError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/types/{type_id}")
async def delete_type(type_id: str, db: DatabaseManager = Depends(get_db)):
    if not svc.delete_document_type(db, type_id):
        raise HTTPException(status_code=404, detail="Document type not found")
    return {"success": True}


@router.post("/{node_id}/verify-type/{type_id}")
async def verify_type(node_id: str, type_id: str,
                      db: DatabaseManager = Depends(get_db)):
    try:
        return svc.verify_against_type(db, node_id, type_id)
    except svc.DocumentError as e:
        raise HTTPException(status_code=404, detail=str(e))

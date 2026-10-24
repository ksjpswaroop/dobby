"""Attachments API — local file storage and text extraction."""

from typing import List

import structlog
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from src.services import attachment_service as svc

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/attachments", tags=["Attachments"])


@router.get("/project/{project_id}")
async def list_attachments(project_id: str):
    return {"attachments": svc.list_attachments(project_id)}


@router.post("/project/{project_id}")
async def upload(project_id: str, file: UploadFile = File(...)):
    """Store a file locally and extract its text."""
    data = await file.read()
    try:
        return svc.save(project_id, file.filename or "file", data)
    except svc.AttachmentError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/project/{project_id}/{attachment_id}/text")
async def get_text(project_id: str, attachment_id: str):
    try:
        return {"text": svc.text_of(project_id, attachment_id)}
    except svc.AttachmentError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/project/{project_id}/{attachment_id}")
async def delete(project_id: str, attachment_id: str):
    if not svc.delete(project_id, attachment_id):
        raise HTTPException(status_code=404, detail="Attachment not found")
    return {"success": True}

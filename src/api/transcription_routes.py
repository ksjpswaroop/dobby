"""Transcription API — local speech-to-text."""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from src.db.schema import DatabaseManager
from src.services import attachment_service as attachments
from src.services import transcription_service as svc

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/transcription", tags=["Transcription"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class ModelRequest(BaseModel):
    project_id: str = "default-project"
    model_id: str


class TranscribeRequest(BaseModel):
    project_id: str = "default-project"
    attachment_id: str
    model_id: str = ""
    language: str = ""


@router.get("/capabilities")
async def capabilities():
    """What is installed, so the UI can say so before the user tries."""
    return svc.capabilities()


@router.post("/models/download")
async def download_model(req: ModelRequest, db: DatabaseManager = Depends(get_db)):
    try:
        return await svc.download_model(db, req.project_id, req.model_id)
    except svc.TranscriptionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/models/{model_id}")
async def delete_model(model_id: str):
    if not svc.delete_model(model_id):
        raise HTTPException(status_code=404, detail="That model is not installed")
    return {"success": True}


@router.post("/transcribe")
async def transcribe(req: TranscribeRequest):
    """Transcribe a previously uploaded audio attachment."""
    row = attachments.get(req.project_id, req.attachment_id)
    if not row:
        raise HTTPException(status_code=404, detail="Attachment not found")
    try:
        return await svc.transcribe(row["path"], req.model_id, req.language)
    except svc.TranscriptionError as e:
        raise HTTPException(status_code=400, detail=str(e))

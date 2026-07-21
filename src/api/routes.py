"""
API Routes for document generation
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import structlog

logger = structlog.get_logger()


router = APIRouter()


class GenerateRequest(BaseModel):
    """Request model for document generation"""
    idea: str = Field(..., min_length=10, max_length=5000, description="Product idea description")
    output_path: Optional[str] = Field(default=None, description="Output directory path")
    template_override: Optional[Dict[str, str]] = Field(default=None, description="Custom template overrides")
    ollama_model: Optional[str] = Field(default="llama3.2", description="Ollama model to use")
    parallel: Optional[bool] = Field(default=True, description="Enable parallel agent execution")


class GenerateResponse(BaseModel):
    """Response model for document generation"""
    job_id: str
    status: str
    message: str
    estimated_time_seconds: int = 300


class JobStatus(BaseModel):
    """Job status response"""
    job_id: str
    status: str
    current_agent: Optional[str] = None
    progress_percent: float = 0.0
    completed_documents: List[str] = []
    failed_documents: List[str] = []
    verification_score: Optional[float] = None


@router.post("/generate", response_model=GenerateResponse, summary="Generate all 29 documents")
async def generate_documents(
    request: GenerateRequest,
    background_tasks: BackgroundTasks,
):
    """
    Generate all 29 comprehensive documents from a single idea.
    
    This endpoint:
    1. Validates the idea
    2. Creates a job in the state machine
    3. Spawns parallel agents for document generation
    4. Runs verification on all outputs
    5. Saves documents to file system
    
    Returns immediately with job_id for status tracking.
    """
    try:
        orchestrator = background_tasks.state.get("orchestrator")
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Orchestrator not initialized")
        
        # Create job
        job_id = await orchestrator.create_job(
            idea=request.idea,
            output_path=request.output_path,
            template_override=request.template_override,
            ollama_model=request.ollama_model,
            parallel=request.parallel,
        )
        
        logger.info("job_created", job_id=job_id, idea_length=len(request.idea))
        
        return GenerateResponse(
            job_id=job_id,
            status="queued",
            message="Job queued for processing",
            estimated_time_seconds=300,
        )
    
    except Exception as e:
        logger.error("generation_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")


@router.get("/jobs/{job_id}", response_model=JobStatus, summary="Get job status")
async def get_job_status(job_id: str):
    """
    Get the current status of a document generation job.
    
    Returns:
    - job_id: Unique job identifier
    - status: Current status (queued, running, done, failed)
    - current_agent: Currently executing agent (if running)
    - progress_percent: Completion percentage (0-100)
    - completed_documents: List of successfully generated documents
    - failed_documents: List of failed documents
    - verification_score: Overall verification score (0-100)
    """
    orchestrator = APIRouter().state.get("orchestrator")
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    job = await orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    return JobStatus(
        job_id=job.job_id,
        status=job.current_state.value,
        current_agent=job.current_agent,
        progress_percent=job.progress_percent,
        completed_documents=job.completed_documents,
        failed_documents=job.failed_documents,
        verification_score=job.verification_score,
    )


@router.post("/verify", summary="Verify generated documents")
async def verify_documents(job_id: str):
    """
    Run verification on all generated documents.
    
    Checks:
    - PRD tech → Architecture tech consistency
    - Architecture components → Backlog coverage
    - Design system → Wireframes alignment
    - Cross-reference completeness
    
    Returns verification score (0-100%) and detailed report.
    """
    orchestrator = APIRouter().state.get("orchestrator")
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    verification_result = await orchestrator.verify_job(job_id)
    
    return {
        "job_id": job_id,
        "verification_score": verification_result.score,
        "checks": verification_result.checks,
        "recommendations": verification_result.recommendations,
    }

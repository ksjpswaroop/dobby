"""
FastAPI Application for Dobby

Provides REST API for document generation, job status, and verification.
"""

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import structlog

from src.api.routes import router as generation_router
from src.orchestrator import DocumentOrchestrator
from src.utils.logging import setup_logging

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info("dobby_startup", version="0.1.0")
    app.state.orchestrator = DocumentOrchestrator()
    yield
    # Shutdown
    logger.info("dobby_shutdown")


app = FastAPI(
    title="Dobby",
    description="Autonomous Multi-Agent Document Generation Platform",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure per environment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(generation_router, prefix="/api/v1", tags=["generation"])


@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "version": "0.1.0"}


@app.get("/metrics", tags=["monitoring"])
async def metrics():
    """Prometheus metrics endpoint"""
    from prometheus_client import generate_latest
    return generate_latest()


@app.get("/", tags=["root"])
async def root():
    """Root endpoint"""
    return {
        "name": "Dobby",
        "version": "0.1.0",
        "description": "Autonomous Multi-Agent Document Generation Platform",
        "docs": "/docs",
        "health": "/health",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )

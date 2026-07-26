"""
FastAPI Application for Dobby v2.0

Main entry point with:
- CORS configuration
- API routes
- Database initialization
- Error handling
"""

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import structlog
from pathlib import Path

from src.db.schema import init_database, DatabaseManager
from src.api.routes import router as api_router

logger = structlog.get_logger()

DEFAULT_PROJECT_ID = "default-project"


def _ensure_default_project(db) -> None:
    """Create the default project the desktop UI targets, if it's missing."""
    from src.db.schema import Project

    with db.get_session() as session:
        if session.get(Project, DEFAULT_PROJECT_ID) is None:
            session.add(
                Project(
                    id=DEFAULT_PROJECT_ID,
                    name="My Workspace",
                    idea="Default workspace",
                    description="Auto-created default project.",
                )
            )
            session.commit()
            logger.info("default_project_created", project_id=DEFAULT_PROJECT_ID)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI
    
    Initializes:
    - Database
    - Global state
    
    Cleans up:
    - Database connections
    """
    # Startup
    logger.info("dobby_startup", message="Starting Dobby v2.0...")
    
    # Initialize database. DOBBY_DB_PATH overrides the default location, which
    # keeps tests (and alternate workspaces) off the user's real database.
    import os

    db_path = Path(os.environ.get("DOBBY_DB_PATH", Path.home() / ".dobby" / "dobby.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    app.state.db = init_database(str(db_path))
    app.state.db_path = str(db_path)

    # Ensure the app works out-of-the-box: seed the default project the UI uses
    # so a fresh install is immediately usable with zero manual setup.
    _ensure_default_project(app.state.db)

    logger.info("database_initialized", path=str(db_path))

    yield
    
    # Shutdown
    logger.info("dobby_shutdown", message="Shutting down Dobby v2.0...")


# Create FastAPI app
app = FastAPI(
    title="Dobby v2.0",
    description="Autonomous Multi-Agent Document Generation Platform - Interactive, Stateful, Graph-Based",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS middleware (for Tauri frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1420",  # Tauri Vite dev
        "http://localhost:3000",  # Tauri dev
        "http://localhost:5173",  # Vite dev
        "tauri://localhost",  # Tauri production
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle all uncaught exceptions"""
    logger.error(
        "uncaught_exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        exc_info=True,
    )
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": str(exc),
            "path": request.url.path,
        },
    )


# Include API routes
app.include_router(api_router, prefix="/api/v1")

# Include dashboard routes
from src.api.dashboard_routes import router as dashboard_router
app.include_router(dashboard_router)

# Include settings & model-management routes
from src.api.settings_routes import router as settings_router
app.include_router(settings_router)

# Include generation routes (wizard + yolo pipelines)
from src.api.generation_routes import router as generation_router
app.include_router(generation_router)

# Include runs routes (Logs & Traces + live progress stream)
from src.api.runs_routes import router as runs_router
app.include_router(runs_router)

# Include search routes (global search across projects/documents/backlog/runs)
from src.api.search_routes import router as search_router
app.include_router(search_router)

# Include mind-map routes (visual concept mapping)
from src.api.mindmap_routes import router as mindmap_router
app.include_router(mindmap_router)

# Include research routes (the stage before Create)
from src.api.research_routes import router as research_router
app.include_router(research_router)


# Health check endpoint
@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint"""
    db_path = app.state.db_path if hasattr(app.state, "db_path") else "not_initialized"
    
    return {
        "status": "healthy",
        "version": "2.0.0",
        "database": db_path,
    }


# Root endpoint
@app.get("/", tags=["Root"])
async def root():
    """Root endpoint with API information"""
    return {
        "name": "Dobby v2.0",
        "version": "2.0.0",
        "description": "Interactive, Stateful, Graph-Based Document Generation Platform",
        "docs": "/docs",
        "health": "/health",
        "api": "/api/v1",
    }


# CLI entry point
def main():
    """Run the FastAPI server"""
    import uvicorn
    
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()

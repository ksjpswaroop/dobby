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
import os
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

    # Seed the built-in prompt library. Idempotent, so it only ever inserts
    # what a given install is missing.
    from src.services.prompt_library import seed_builtins

    try:
        seeded = seed_builtins(app.state.db)
        if seeded:
            logger.info("prompt_library_seeded", added=seeded)
    except Exception:
        logger.warning("prompt_seed_failed", exc_info=True)

    # Mint this launch's API token before anything can serve a request.
    from src.security.tokens import get_token_manager

    get_token_manager().publish()
    logger.info("launch_token_ready", file=str(get_token_manager().path))

    # A restart leaves sessions marked 'active' with nobody driving them.
    # Suspending is right: the checkpoints are still good, so the work is
    # paused rather than lost.
    from src.services.session_service import reconcile as reconcile_sessions

    try:
        reconcile_sessions(app.state.db, DEFAULT_PROJECT_ID)
    except Exception:
        logger.warning("session_reconcile_failed", exc_info=True)

    # Start the always-on scheduler. It lives inside this process rather than a
    # separate daemon: the app *is* the scheduler, which is the only design that
    # works for a desktop app that is sometimes closed. Startup also catches up
    # anything that came due while it was.
    from src.services.automation_service import SchedulerLoop

    app.state.scheduler = SchedulerLoop(app.state.db)
    if os.environ.get("DOBBY_DISABLE_SCHEDULER") != "1":
        app.state.scheduler.start()

    yield

    # Shutdown
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler:
        await scheduler.stop()
    from src.mcp import registry as mcp_registry

    await mcp_registry.shutdown()
    get_token_manager().revoke()
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


@app.middleware("http")
async def require_launch_token(request: Request, call_next):
    """Gate every API route behind this launch's token.

    "It's only localhost" is not an access boundary — every other process on the
    machine can reach this port, and any page the user visits can issue requests
    to it. Health checks and the handshake stay open; see `src/security/tokens`.

    Set DOBBY_DISABLE_AUTH=1 to turn this off for local debugging.
    """
    from src.security.tokens import bearer_from_header, get_token_manager, is_open_path

    path = request.url.path
    if (
        os.environ.get("DOBBY_DISABLE_AUTH") == "1"
        or request.method == "OPTIONS"          # CORS preflight carries no auth
        or is_open_path(path)
        or not path.startswith("/api/")
    ):
        return await call_next(request)

    manager = get_token_manager()
    presented = bearer_from_header(request.headers.get("authorization"))
    # EventSource cannot set headers, so the SSE stream accepts ?token= instead.
    if presented is None:
        presented = request.query_params.get("token")

    if not manager.verify(presented):
        return JSONResponse(
            status_code=401,
            content={
                "error": "unauthorized",
                "message": ("This request needs the current launch token. "
                            "Fetch it from /api/v1/auth/handshake."),
                "path": path,
            },
        )
    return await call_next(request)


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

# Include the handshake route (must be reachable without a token)
from src.api.auth_routes import router as auth_router
app.include_router(auth_router)

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

# Include inbox routes (approvals + parked asks)
from src.api.inbox_routes import router as inbox_router
app.include_router(inbox_router)

# Include messaging routes (Slack / Telegram connectors)
from src.api.messaging_routes import router as messaging_router
app.include_router(messaging_router)

# Include transcription routes (local speech-to-text)
from src.api.transcription_routes import router as transcription_router
app.include_router(transcription_router)

# Include persona routes (how Dobby behaves)
from src.api.persona_routes import router as persona_router
app.include_router(persona_router)

# Include work-session routes (durable sessions + permission modes)
from src.api.session_routes import router as session_router
app.include_router(session_router)

# Include provider routes (multi-provider model access)
from src.api.provider_routes import router as provider_router
app.include_router(provider_router)

# Include attachment routes (local files as source material)
from src.api.attachment_routes import router as attachment_router
app.include_router(attachment_router)

# Include MCP routes (external tool servers)
from src.api.mcp_routes import router as mcp_router
app.include_router(mcp_router)

# Include licensing routes (verification mechanism; billing deferred)
from src.api.license_routes import router as license_router
app.include_router(license_router)

# Include terminal routes (approval-gated command execution)
from src.api.terminal_routes import router as terminal_router
app.include_router(terminal_router)

# Include automation routes (scheduled work)
from src.api.automation_routes import router as automation_router
app.include_router(automation_router)

# Include idea capture routes (quick-capture + triage)
from src.api.idea_routes import router as idea_router
app.include_router(idea_router)

# Include activity timeline routes (unified feed over ideas/features/runs/research)
from src.api.timeline_routes import router as timeline_router
app.include_router(timeline_router)

# Include pins & favorites routes (generic across ideas/features/documents)
from src.api.pin_routes import router as pin_router
app.include_router(pin_router)

# Include momentum routes (daily streak + 14-day sparkline)
from src.api.momentum_routes import router as momentum_router
app.include_router(momentum_router)

# Include living-document routes (editing, versions, status, tags, comments)
from src.api.document_routes import router as document_router
app.include_router(document_router)

# Include copilot routes (chat, next-best-action, prioritization, prompts,
# per-task model routing, usage telemetry)
from src.api.copilot_routes import router as copilot_router
app.include_router(copilot_router)

# Include planning routes (board, sprints, milestones, blockers, OKRs,
# daily plan, delivery analytics, work breakdown)
from src.api.planning_routes import router as planning_router
app.include_router(planning_router)

# Include trust routes (trash, project backup, consistency, batch operations)
from src.api.trust_routes import router as trust_router
app.include_router(trust_router)

# Include capture routes (URL, email, OCR, bulk import, meeting notes, dedupe)
from src.api.capture_routes import router as capture_router
app.include_router(capture_router)

# Include habit routes (reminders, recap, achievements, focus, share card)
from src.api.habit_routes import router as habit_router
app.include_router(habit_router)

# Include quality routes (verification report, custom rules, citations, auto-fix)
from src.api.quality_routes import router as quality_router
app.include_router(quality_router)

# Include platform routes (i18n, model catalog, in-app help, goals, ritual mode)
from src.api.platform_routes import router as platform_router
app.include_router(platform_router)

# Include integration routes (outbound webhooks, API keys, recipes)
from src.api.integration_routes import router as integration_router
app.include_router(integration_router)


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

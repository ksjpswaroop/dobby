"""
API Routes for Dobby v2.0

Endpoints:
- /api/v1/projects - Project CRUD
- /api/v1/graph - Graph operations
- /api/v1/features - Feature backlog with Pareto scoring
- /api/v1/sessions - Session management
- /api/v1/audit - Audit trail queries
"""

from fastapi import APIRouter, HTTPException, Depends, Body
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid

from src.db.schema import DatabaseManager, Project, Node, Edge, FeatureBacklog, Session, AuditEntry
from src.graph.graph import DocumentGraph, GraphNode, GraphEdge, NodeType, EdgeType, NodeStatus

router = APIRouter()


# ============================================================================
# Dependency Injection
# ============================================================================
def get_db() -> DatabaseManager:
    """Get database instance from app state"""
    from src.main import app
    return app.state.db


# ============================================================================
# Request/Response Models
# ============================================================================
class ProjectCreate(BaseModel):
    name: str
    idea: str
    description: Optional[str] = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    idea: str
    description: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime


class NodeCreate(BaseModel):
    node_type: str
    title: str
    content: Optional[str] = ""
    parent_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class EdgeCreate(BaseModel):
    source_node_id: str
    target_node_id: str
    edge_type: str
    metadata: Optional[Dict[str, Any]] = None


class FeatureBacklogCreate(BaseModel):
    title: str
    description: Optional[str] = None
    category: str
    impact_score: int = Field(ge=1, le=10, default=5)
    effort_score: int = Field(ge=1, le=10, default=5)
    risk_score: int = Field(ge=1, le=10, default=5)


class FeatureBacklogResponse(BaseModel):
    id: str
    title: str
    pareto_score: float
    status: str
    category: str


# ============================================================================
# Project Routes
# ============================================================================
@router.post("/projects", response_model=ProjectResponse, tags=["Projects"])
async def create_project(project: ProjectCreate, db: DatabaseManager = Depends(get_db)):
    """Create a new project"""
    with db.get_session() as session:
        project_id = str(uuid.uuid4())
        
        db_project = Project(
            id=project_id,
            name=project.name,
            idea=project.idea,
            description=project.description,
        )
        
        session.add(db_project)
        session.commit()
        session.refresh(db_project)
        
        return ProjectResponse(
            id=db_project.id,
            name=db_project.name,
            idea=db_project.idea,
            description=db_project.description,
            status=db_project.status,
            created_at=db_project.created_at,
            updated_at=db_project.updated_at,
        )


@router.get("/projects", response_model=List[ProjectResponse], tags=["Projects"])
async def list_projects(db: DatabaseManager = Depends(get_db)):
    """List all projects"""
    with db.get_session() as session:
        projects = session.query(Project).all()
        
        return [
            ProjectResponse(
                id=p.id,
                name=p.name,
                idea=p.idea,
                description=p.description,
                status=p.status,
                created_at=p.created_at,
                updated_at=p.updated_at,
            )
            for p in projects
        ]


@router.get("/projects/{project_id}", response_model=ProjectResponse, tags=["Projects"])
async def get_project(project_id: str, db: DatabaseManager = Depends(get_db)):
    """Get project by ID"""
    with db.get_session() as session:
        project = session.query(Project).filter(Project.id == project_id).first()
        
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        return ProjectResponse(
            id=project.id,
            name=project.name,
            idea=project.idea,
            description=project.description,
            status=project.status,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )


# ============================================================================
# Graph Routes
# ============================================================================
@router.post("/projects/{project_id}/graph/nodes", tags=["Graph"])
async def create_node(
    project_id: str,
    node: NodeCreate,
    db: DatabaseManager = Depends(get_db),
):
    """Create a new graph node"""
    with db.get_session() as session:
        # Verify project exists
        project = session.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        node_id = str(uuid.uuid4())
        
        db_node = Node(
            id=node_id,
            project_id=project_id,
            node_type=node.node_type,
            title=node.title,
            content=node.content,
            parent_id=node.parent_id,
            extra_metadata=node.metadata or {},
        )

        session.add(db_node)
        # The parent/child link is expressed via parent_id; the ORM exposes the
        # reverse side as Node.child_nodes (no separate children column).
        session.commit()
        session.refresh(db_node)
        
        return {
            "node_id": db_node.id,
            "node_type": db_node.node_type,
            "title": db_node.title,
            "status": db_node.status,
        }


@router.post("/projects/{project_id}/graph/edges", tags=["Graph"])
async def create_edge(
    project_id: str,
    edge: EdgeCreate,
    db: DatabaseManager = Depends(get_db),
):
    """Create a new graph edge"""
    with db.get_session() as session:
        edge_id = str(uuid.uuid4())
        
        db_edge = Edge(
            id=edge_id,
            project_id=project_id,
            source_node_id=edge.source_node_id,
            target_node_id=edge.target_node_id,
            edge_type=edge.edge_type,
            extra_metadata=edge.metadata or {},
        )
        
        session.add(db_edge)
        session.commit()
        session.refresh(db_edge)
        
        return {
            "edge_id": db_edge.id,
            "edge_type": db_edge.edge_type,
            "source": db_edge.source_node_id,
            "target": db_edge.target_node_id,
        }


# NOTE: GET /projects/{id}/graph is served by dashboard_routes.py, which returns
# the Mermaid syntax the UI needs. A second definition here previously shadowed
# it (registration order) and broke the graph view, so it was removed.


# ============================================================================
# Feature Backlog Routes (with Pareto Scoring)
# ============================================================================
@router.post("/projects/{project_id}/backlog", response_model=FeatureBacklogResponse, tags=["Backlog"])
async def add_to_backlog(
    project_id: str,
    feature: FeatureBacklogCreate,
    db: DatabaseManager = Depends(get_db),
):
    """Add feature to backlog with Pareto scoring"""
    with db.get_session() as session:
        feature_id = str(uuid.uuid4())
        
        # Calculate Pareto score
        pareto_score = (
            (feature.impact_score * 0.6)
            - (feature.effort_score * 0.3)
            - (feature.risk_score * 0.1)
        )
        
        db_feature = FeatureBacklog(
            id=feature_id,
            project_id=project_id,
            title=feature.title,
            description=feature.description,
            category=feature.category,
            impact_score=feature.impact_score,
            effort_score=feature.effort_score,
            risk_score=feature.risk_score,
            pareto_score=pareto_score,
        )
        
        session.add(db_feature)
        session.commit()
        session.refresh(db_feature)
        
        return FeatureBacklogResponse(
            id=db_feature.id,
            title=db_feature.title,
            pareto_score=db_feature.pareto_score,
            status=db_feature.status,
            category=db_feature.category,
        )


@router.get("/projects/{project_id}/backlog/top", tags=["Backlog"])
async def get_top_features(
    project_id: str,
    limit: int = 10,
    db: DatabaseManager = Depends(get_db),
):
    """Get top features by Pareto score"""
    with db.get_session() as session:
        features = (
            session.query(FeatureBacklog)
            .filter(
                FeatureBacklog.project_id == project_id,
                FeatureBacklog.status == "backlog",
            )
            .order_by(FeatureBacklog.pareto_score.desc())
            .limit(limit)
            .all()
        )
        
        return [
            {
                "id": f.id,
                "title": f.title,
                "pareto_score": f.pareto_score,
                "impact": f.impact_score,
                "effort": f.effort_score,
                "risk": f.risk_score,
            }
            for f in features
        ]


@router.put("/projects/{project_id}/backlog/{feature_id}/start", tags=["Backlog"])
async def start_feature(
    project_id: str,
    feature_id: str,
    db: DatabaseManager = Depends(get_db),
):
    """Mark feature as in-progress and create initial node"""
    with db.get_session() as session:
        feature = session.query(FeatureBacklog).filter(FeatureBacklog.id == feature_id).first()
        if not feature:
            raise HTTPException(status_code=404, detail="Feature not found")
        
        # Update feature status
        feature.status = "in_progress"
        feature.completed_at = None
        
        # Create initial feature node
        node_id = str(uuid.uuid4())
        db_node = Node(
            id=node_id,
            project_id=project_id,
            node_type="feature",
            title=feature.title,
            content=feature.description or "",
            status="in_progress",
        )
        
        session.add(db_node)
        feature.node_id = node_id
        
        session.commit()
        
        return {
            "feature_id": feature_id,
            "node_id": node_id,
            "status": "in_progress",
        }


# ============================================================================
# Session Routes
# ============================================================================
@router.post("/projects/{project_id}/sessions", tags=["Sessions"])
async def create_session(
    project_id: str,
    session_type: str = "wizard",
    db: DatabaseManager = Depends(get_db),
):
    """Create a new session (wizard, editor, yolo)"""
    with db.get_session() as session:
        session_id = str(uuid.uuid4())
        
        db_session = Session(
            id=session_id,
            project_id=project_id,
            session_type=session_type,
            state={},
        )
        
        session.add(db_session)
        session.commit()
        session.refresh(db_session)
        
        return {
            "session_id": db_session.id,
            "session_type": db_session.session_type,
            "created_at": db_session.created_at,
        }


@router.get("/projects/{project_id}/sessions/{session_id}", tags=["Sessions"])
async def get_session(
    project_id: str,
    session_id: str,
    db: DatabaseManager = Depends(get_db),
):
    """Get session state (for resuming)"""
    with db.get_session() as session:
        db_session = (
            session.query(Session)
            .filter(Session.id == session_id, Session.project_id == project_id)
            .first()
        )
        
        if not db_session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return {
            "session_id": db_session.id,
            "session_type": db_session.session_type,
            "current_step": db_session.current_step,
            "state": db_session.state,
            "last_active": db_session.last_active,
        }


@router.put("/projects/{project_id}/sessions/{session_id}/state", tags=["Sessions"])
async def update_session_state(
    project_id: str,
    session_id: str,
    state: Dict[str, Any],
    db: DatabaseManager = Depends(get_db),
):
    """Update session state"""
    with db.get_session() as session:
        db_session = (
            session.query(Session)
            .filter(Session.id == session_id, Session.project_id == project_id)
            .first()
        )
        
        if not db_session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        db_session.state = state
        db_session.last_active = datetime.utcnow()
        
        session.commit()
        
        return {
            "session_id": db_session.id,
            "updated_at": db_session.last_active,
        }


# ============================================================================
# Audit Trail Routes
# ============================================================================
@router.get("/projects/{project_id}/audit", tags=["Audit"])
async def get_audit_trail(
    project_id: str,
    limit: int = 50,
    db: DatabaseManager = Depends(get_db),
):
    """Get audit trail for project"""
    with db.get_session() as session:
        entries = (
            session.query(AuditEntry)
            .filter(AuditEntry.project_id == project_id)
            .order_by(AuditEntry.timestamp.desc())
            .limit(limit)
            .all()
        )
        
        return [
            {
                "id": e.id,
                "action": e.action,
                "node_id": e.node_id,
                "timestamp": e.timestamp,
                "user_id": e.user_id,
            }
            for e in entries
        ]

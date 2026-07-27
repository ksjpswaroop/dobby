"""
Dashboard and Graph API Endpoints for Dobby v2.0

Endpoints:
- GET /api/v1/projects/{project_id}/dashboard - Dashboard statistics
- GET /api/v1/projects/{project_id}/backlog - Feature backlog with Pareto scores
- GET /api/v1/projects/{project_id}/graph - Dependency graph data
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Any, Optional
from datetime import datetime
import structlog

from src.db.schema import DatabaseManager, Project, Node, Edge, FeatureBacklog
from src.pipeline.pareto import get_pareto_scorer

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1", tags=["dashboard", "backlog", "graph"])


# ============================================================================
# Helper Functions
# ============================================================================
def get_db() -> DatabaseManager:
    """Reuse the single database manager created at app startup.

    Previously this rebuilt the engine (and re-ran create_all + template
    seeding) on every request, which was both slow and wasteful.
    """
    from src.main import app

    return app.state.db


# ============================================================================
# Dashboard Endpoints
# ============================================================================
@router.get("/projects/{project_id}/dashboard")
async def get_dashboard(
    project_id: str,
    db: DatabaseManager = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get dashboard statistics for a project
    
    Returns:
    {
        "project_count": 1,
        "feature_count": 47,
        "document_count": 12,
        "today_feature": {
            "id": "...",
            "title": "...",
            "pareto_score": 5.2,
            "status": "backlog"
        },
        "recent_features": [...]
    }
    """
    with db.get_session() as session:
        # Get project. A missing project is treated as an empty workspace rather
        # than an error so the dashboard always renders.
        project = session.query(Project).filter(Project.id == project_id).first()
        if not project:
            return {
                "project_count": 0,
                "feature_count": 0,
                "document_count": 0,
                "today_feature": None,
                "recent_features": [],
            }

        # Count features
        feature_count = session.query(Node).filter(
            Node.project_id == project_id,
            Node.node_type == "feature"
        ).count()
        
        # Count documents
        document_count = session.query(Node).filter(
            Node.project_id == project_id,
            Node.node_type.in_(["documentation", "prd", "architecture"])
        ).count()
        
        # Get today's priority feature (highest Pareto score in backlog)
        scorer = get_pareto_scorer(db)
        today_feature_data = scorer.get_daily_priority_feature(project_id)
        
        # Get recent features (last 5 completed)
        recent_features = (
            session.query(FeatureBacklog)
            .filter(
                FeatureBacklog.project_id == project_id,
                FeatureBacklog.status == "completed"
            )
            .order_by(FeatureBacklog.updated_at.desc())
            .limit(5)
            .all()
        )
        
        return {
            "project_count": session.query(Project).count(),
            "feature_count": feature_count,
            "document_count": document_count,
            "today_feature": today_feature_data,
            "recent_features": [
                {
                    "id": f.id,
                    "title": f.title,
                    "pareto_score": f.pareto_score,
                    "status": f.status,
                }
                for f in recent_features
            ],
        }


# ============================================================================
# Feature Backlog Endpoints
# ============================================================================
@router.get("/projects/{project_id}/backlog")
async def get_backlog(
    project_id: str,
    status: Optional[str] = None,
    limit: int = 100,
    db: DatabaseManager = Depends(get_db),
) -> List[Dict[str, Any]]:
    """
    Get feature backlog sorted by Pareto score
    
    Query params:
    - status: Filter by status (backlog, in_progress, completed)
    - limit: Maximum number of features (default: 100)
    
    Returns:
    [
        {
            "id": "...",
            "title": "...",
            "description": "...",
            "pareto_score": 5.2,
            "impact_score": 8,
            "effort_score": 3,
            "risk_score": 2,
            "category": "core",
            "status": "backlog",
            "created_at": "2026-07-21T10:00:00Z",
            "updated_at": "2026-07-21T10:00:00Z"
        }
    ]
    """
    with db.get_session() as session:
        query = session.query(FeatureBacklog).filter(
            FeatureBacklog.project_id == project_id
        )
        
        if status:
            query = query.filter(FeatureBacklog.status == status)
        
        features = (
            query.order_by(FeatureBacklog.pareto_score.desc())
            .limit(limit)
            .all()
        )
        
        return [
            {
                "id": f.id,
                "title": f.title,
                "description": f.description,
                "pareto_score": f.pareto_score,
                "impact_score": f.impact_score,
                "effort_score": f.effort_score,
                "risk_score": f.risk_score,
                "category": f.category,
                "status": f.status,
                "created_at": f.created_at.isoformat() if f.created_at else None,
                "updated_at": f.updated_at.isoformat() if f.updated_at else None,
            }
            for f in features
        ]


# ============================================================================
# Graph Endpoints
# ============================================================================
@router.get("/projects/{project_id}/graph")
async def get_graph(
    project_id: str,
    max_nodes: int = 100,
    db: DatabaseManager = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get dependency graph data for Mermaid.js visualization
    
    Query params:
    - max_nodes: Maximum number of nodes to return (default: 100)
    
    Returns:
    {
        "nodes": [
            {
                "id": "...",
                "type": "feature",
                "title": "Smart Action Items",
                "status": "completed"
            }
        ],
        "edges": [
            {
                "source": "feature_123",
                "target": "story_456",
                "type": "generates"
            }
        ],
        "mermaid_syntax": "graph TD\n  A[Feature] --> B[Story]\n..."
    }
    """
    with db.get_session() as session:
        # Get nodes (limit to max_nodes)
        nodes = (
            session.query(Node)
            .filter(Node.project_id == project_id)
            .limit(max_nodes)
            .all()
        )
        
        # Get edges for these nodes
        node_ids = [n.id for n in nodes]
        edges = (
            session.query(Edge)
            .filter(
                Edge.project_id == project_id,
                Edge.source_node_id.in_(node_ids),
                Edge.target_node_id.in_(node_ids)
            )
            .all()
        )
        
        # Build Mermaid syntax
        mermaid_lines = ["graph TD"]
        
        # Add nodes with styling
        for node in nodes:
            node_type = node.node_type or "unknown"
            title = (node.title or "Untitled").replace("[", "(").replace("]", ")")
            
            # Color by node type
            colors = {
                "feature": "#3B82F6",  # blue
                "user_story": "#10B981",  # green
                "functional_analysis": "#F59E0B",  # amber
                "flowchart": "#8B5CF6",  # purple
                "pseudocode": "#EC4899",  # pink
                "tdd_tests": "#EF4444",  # red
                "documentation": "#6B7280",  # gray
            }
            
            color = colors.get(node_type, "#6B7280")
            mermaid_lines.append(f"  {node.id}[\"{title}\"]")
            mermaid_lines.append(f"  style {node.id} fill:{color},color:white")
        
        # Add edges
        edge_types = {
            "generates": "-- generates -->",
            "refines": "-- refines -->",
            "implements": "-- implements -->",
            "tests": "-- tests -->",
            "documents": "-- documents -->",
            "depends_on": "-- depends on -->",
        }
        
        for edge in edges:
            edge_type = edge.edge_type or "generates"
            arrow = edge_types.get(edge_type, "--> ")
            mermaid_lines.append(f"  {edge.source_node_id} {arrow} {edge.target_node_id}")
        
        mermaid_syntax = "\n".join(mermaid_lines)
        
        return {
            "nodes": [
                {
                    "id": n.id,
                    "type": n.node_type,
                    "title": n.title,
                    "status": n.status,
                }
                for n in nodes
            ],
            "edges": [
                {
                    "source": e.source_node_id,
                    "target": e.target_node_id,
                    "type": e.edge_type,
                }
                for e in edges
            ],
            "mermaid_syntax": mermaid_syntax,
        }


# ============================================================================
# Health Check
# ============================================================================
@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/projects/{project_id}/home")
async def get_home(project_id: str, db: DatabaseManager = Depends(get_db)) -> Dict[str, Any]:
    """Today's actionable slice — one round-trip for the landing screen."""
    from src.services.home_service import build_home

    return build_home(db, project_id)

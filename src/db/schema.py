"""
Dobby v2.0 Database Schema

SQLite database with tables for:
- Projects
- Graph Nodes (Idea, Feature, Story, etc.)
- Graph Edges (dependencies, relationships)
- Feature Backlog (with Pareto scoring)
- Verification Results
- Audit Trail
- Templates
- Sessions
"""

from sqlalchemy import (
    create_engine,
    Column,
    String,
    Text,
    Integer,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
    Index,
    event,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
from pathlib import Path
import json

Base = declarative_base()


# ============================================================================
# Project Model
# ============================================================================
class Project(Base):
    """Project represents a single product/application being documented"""
    
    __tablename__ = "projects"
    
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    idea = Column(Text)
    description = Column(Text)
    status = Column(String, default="active")  # active, archived, completed
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    nodes = relationship("Node", back_populates="project", cascade="all, delete-orphan")
    edges = relationship("Edge", back_populates="project", cascade="all, delete-orphan")
    backlog_features = relationship("FeatureBacklog", back_populates="project", cascade="all, delete-orphan")
    sessions = relationship("Session", back_populates="project", cascade="all, delete-orphan")
    audit_entries = relationship("AuditEntry", back_populates="project", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Project(id='{self.id}', name='{self.name}', status='{self.status}')>"


# ============================================================================
# Graph Node Model
# ============================================================================
class Node(Base):
    """
    Graph Node represents any entity in the document graph:
    - Idea (root)
    - Feature
    - UserStory
    - FunctionalAnalysis
    - Flowchart
    - Pseudocode
    - TDDTests
    - Documentation
    """
    
    __tablename__ = "nodes"
    
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    node_type = Column(String, nullable=False, index=True)  # idea, feature, user_story, etc.
    title = Column(String, nullable=False)
    content = Column(Text)
    status = Column(String, default="draft")  # draft, in_progress, verified, finalized
    parent_id = Column(String, ForeignKey("nodes.id"), index=True)
    extra_metadata = Column("metadata", JSON, default=dict)
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    project = relationship("Project", back_populates="nodes")
    parent = relationship("Node", remote_side=[id], back_populates="child_nodes")
    child_nodes = relationship("Node", foreign_keys=[parent_id], back_populates="parent")
    verification_results = relationship("VerificationResult", back_populates="node", cascade="all, delete-orphan")
    audit_entries = relationship("AuditEntry", back_populates="node")
    
    __table_args__ = (
        Index("idx_node_type_status", "node_type", "status"),
        Index("idx_project_node_type", "project_id", "node_type"),
    )
    
    def __repr__(self):
        return f"<Node(id='{self.id}', type='{self.node_type}', title='{self.title}')>"


# ============================================================================
# Graph Edge Model
# ============================================================================
class Edge(Base):
    """
    Graph Edge represents relationships between nodes:
    - generates: Feature generates UserStory
    - refines: UserStory refines FunctionalAnalysis
    - implements: Pseudocode implements Flowchart
    - tests: TDDTests tests Pseudocode
    - documents: Documentation documents TDDTests
    """
    
    __tablename__ = "edges"
    
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    source_node_id = Column(String, ForeignKey("nodes.id"), nullable=False, index=True)
    target_node_id = Column(String, ForeignKey("nodes.id"), nullable=False, index=True)
    edge_type = Column(String, nullable=False)  # generates, refines, implements, tests, documents
    extra_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    project = relationship("Project", back_populates="edges")
    source_node = relationship("Node", foreign_keys=[source_node_id])
    target_node = relationship("Node", foreign_keys=[target_node_id])
    
    __table_args__ = (
        Index("idx_edge_type", "edge_type"),
        Index("idx_source_target", "source_node_id", "target_node_id", unique=True),
    )
    
    def __repr__(self):
        return f"<Edge(id='{self.id}', type='{self.edge_type}', from='{self.source_node_id}' to='{self.target_node_id}')>"


# ============================================================================
# Feature Backlog Model (with Pareto scoring)
# ============================================================================
class FeatureBacklog(Base):
    """
    Feature backlog with Pareto scoring for prioritization
    
    Pareto Score = (Impact * 0.6) - (Effort * 0.3) - (Risk * 0.1)
    """
    
    __tablename__ = "feature_backlog"
    
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    category = Column(String, index=True)  # core, user_management, integration, ai, etc.
    impact_score = Column(Integer, default=5)  # 1-10
    effort_score = Column(Integer, default=5)  # 1-10
    risk_score = Column(Integer, default=5)  # 1-10
    pareto_score = Column(Float, default=0.0)  # Calculated
    status = Column(String, default="backlog", index=True)  # backlog, in_progress, completed, skipped
    dependencies = Column(JSON, default=list)  # List of feature IDs this depends on
    extra_metadata = Column("metadata", JSON, default=dict)
    node_id = Column(String, ForeignKey("nodes.id"), nullable=True)  # Linked node if feature is started
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    project = relationship("Project", back_populates="backlog_features")
    node = relationship("Node", backref="backlog_feature")
    
    __table_args__ = (
        Index("idx_pareto_score", "pareto_score", mysql_length=8),
        Index("idx_status_pareto", "status", "pareto_score"),
    )
    
    def calculate_pareto_score(self) -> float:
        """Calculate Pareto score: (Impact * 0.6) - (Effort * 0.3) - (Risk * 0.1)"""
        return float((self.impact_score * 0.6) - (self.effort_score * 0.3) - (self.risk_score * 0.1))
    
    def __repr__(self):
        return f"<FeatureBacklog(id='{self.id}', title='{self.title}', pareto={self.pareto_score:.2f})>"


# ============================================================================
# Verification Result Model
# ============================================================================
class VerificationResult(Base):
    """
    Deterministic verification result for a node
    
    Stores:
    - Overall score (0-100)
    - Pass/fail status
    - Issues found (JSON)
    - Checks performed (JSON)
    - Metrics (JSON)
    """
    
    __tablename__ = "verification_results"
    
    id = Column(String, primary_key=True)
    node_id = Column(String, ForeignKey("nodes.id"), nullable=False, index=True)
    overall_score = Column(Float, nullable=False)
    passed = Column(Boolean, nullable=False)
    issues = Column(JSON, default=list)  # List of VerificationIssue dicts
    checks_performed = Column(JSON, default=list)  # List of check names
    metrics = Column(JSON, default=dict)  # Metrics from each check
    verified_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    node = relationship("Node", back_populates="verification_results")
    
    __table_args__ = (
        Index("idx_node_score", "node_id", "overall_score"),
        Index("idx_passed", "passed"),
    )
    
    def __repr__(self):
        return f"<VerificationResult(node='{self.node_id}', score={self.overall_score}, passed={self.passed})>"


# ============================================================================
# Audit Trail Model
# ============================================================================
class AuditEntry(Base):
    """
    Audit trail entry for every change in the system
    
    Tracks:
    - Who made the change (user_id)
    - What changed (action, old_content, new_content)
    - When (timestamp)
    - Which node/project was affected
    """
    
    __tablename__ = "audit_trail"
    
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    node_id = Column(String, ForeignKey("nodes.id"), nullable=True, index=True)
    action = Column(String, nullable=False)  # create, update, delete, verify, finalize
    old_content = Column(Text, nullable=True)  # JSON string of old state
    new_content = Column(Text, nullable=True)  # JSON string of new state
    user_id = Column(String, nullable=True)  # User who made the change
    extra_metadata = Column("metadata", JSON, default=dict)  # Additional context
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    project = relationship("Project", back_populates="audit_entries")
    node = relationship("Node", back_populates="audit_entries")
    
    __table_args__ = (
        Index("idx_action_timestamp", "action", "timestamp"),
        Index("idx_project_timestamp", "project_id", "timestamp"),
    )
    
    def __repr__(self):
        return f"<AuditEntry(id='{self.id}', action='{self.action}', timestamp='{self.timestamp}')>"


# ============================================================================
# Template Model
# ============================================================================
class Template(Base):
    """
    Document template (e.g., PRD template, Architecture template)
    
    Supports versioning and customization
    """
    
    __tablename__ = "templates"
    
    id = Column(String, primary_key=True)
    name = Column(String, unique=True, nullable=False)  # e.g., "PRD.md.template"
    content = Column(Text, nullable=False)
    version = Column(Integer, default=1)
    extra_metadata = Column("metadata", JSON, default=dict)  # Variables, sections, etc.
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<Template(name='{self.name}', version={self.version})>"


# ============================================================================
# Session Model
# ============================================================================
class Session(Base):
    """
    User session for wizard or editing
    
    Persists state so user can resume anytime
    """
    
    __tablename__ = "sessions"
    
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    session_type = Column(String, nullable=False)  # wizard, editor, yolo
    current_node_id = Column(String, ForeignKey("nodes.id"), nullable=True)
    current_step = Column(Integer, default=0)  # For wizard: 1-7
    state = Column(JSON, default=dict)  # Wizard state, UI state, accumulated data
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    project = relationship("Project", back_populates="sessions")
    current_node = relationship("Node")
    
    __table_args__ = (
        Index("idx_project_session_type", "project_id", "session_type"),
        Index("idx_last_active", "last_active"),
    )
    
    def __repr__(self):
        return f"<Session(id='{self.id}', type='{self.session_type}', last_active='{self.last_active}')>"


# ============================================================================
# Database Manager
# ============================================================================
class DatabaseManager:
    """
    Database manager for Dobby v2.0
    
    Handles:
    - Database creation and initialization
    - Session management
    - Migrations
    - Backup/restore
    """
    
    def __init__(self, db_path: str = "~/.dobby/dobby.db"):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create SQLite engine
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            echo=False,  # Set to True for SQL debugging
            connect_args={"check_same_thread": False},  # Needed for SQLite
        )

        # Tune SQLite on every new connection: WAL for concurrent reads while
        # writing, enforced foreign keys, and a balanced sync mode.
        @event.listens_for(self.engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            # Wait up to 10s for a lock instead of failing immediately — matters
            # when bulk generation commits from several concurrent tasks.
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.close()

        # Create session factory. expire_on_commit=False keeps attributes
        # readable after commit (and after the session closes), which avoids
        # DetachedInstanceError when returning ORM objects from a `with` block.
        SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.SessionLocal = SessionLocal
        
        # Register models defined in sibling modules so create_all sees their
        # tables. Imported here (not at module top) to avoid a circular import,
        # since those modules import Base from this one.
        from src.db import (  # noqa: F401
            automation_models, copilot_models, document_models, idea_models, inbox_models,
            license_models, mindmap_models, pin_models, planning_models, research_models,
            run_models, session_models, trust_models,
        )

        # Create all tables
        Base.metadata.create_all(bind=self.engine)
        
        # Initialize default templates
        self._initialize_templates()
    
    def get_session(self):
        """Get a new database session"""
        return self.SessionLocal()
    
    def _initialize_templates(self):
        """Initialize default templates if they don't exist"""
        with self.get_session() as session:
            # Check if templates exist
            count = session.query(Template).count()
            
            if count == 0:
                # Add default templates (simplified versions)
                default_templates = [
                    Template(
                        id="tpl_prd",
                        name="PRD.md.template",
                        content="# PRD: {{product_name}}\n\n## 1. Executive Summary\n{{executive_summary}}\n\n...",
                        version=1,
                    ),
                    Template(
                        id="tpl_architecture",
                        name="ARCHITECTURE.md.template",
                        content="# Architecture: {{product_name}}\n\n## 1. System Overview\n{{overview}}\n\n...",
                        version=1,
                    ),
                ]
                
                session.add_all(default_templates)
                session.commit()
    
    def backup(self, backup_path: str) -> str:
        """Create a backup of the database"""
        import shutil
        
        backup_path_obj = Path(backup_path).expanduser()
        backup_path_obj.parent.mkdir(parents=True, exist_ok=True)
        
        shutil.copy2(self.db_path, backup_path_obj)
        return str(backup_path_obj)
    
    def restore(self, backup_path: str):
        """Restore database from backup"""
        import shutil
        
        backup_path_obj = Path(backup_path).expanduser()
        
        if not backup_path_obj.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")
        
        shutil.copy2(backup_path_obj, self.db_path)


# ============================================================================
# Database Initialization
# ============================================================================
def init_database(db_path: str = "~/.dobby/dobby.db") -> DatabaseManager:
    """Initialize the Dobby database"""
    return DatabaseManager(db_path=db_path)


if __name__ == "__main__":
    # Test database creation
    print("Initializing Dobby database...")
    db = init_database()
    print(f"Database created at: {db.db_path}")
    
    # Test session
    with db.get_session() as session:
        projects_count = session.query(Project).count()
        print(f"Projects in database: {projects_count}")
        
        templates_count = session.query(Template).count()
        print(f"Templates in database: {templates_count}")
    
    print("Database initialization complete! ✅")

"""
Session Management for Dobby v2.0

Handles:
- Session creation (wizard, editor, yolo)
- Session persistence (save state to database)
- Session resume (load state from database)
- Session cleanup (remove old sessions)
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Literal
from datetime import datetime, timedelta
import json
import uuid

from src.db.schema import DatabaseManager, Session as DBSession


# ============================================================================
# Session Types
# ============================================================================
SessionType = Literal["wizard", "editor", "yolo"]


# ============================================================================
# Wizard Session State
# ============================================================================
@dataclass
class WizardState:
    """State machine for 7-step wizard"""
    
    current_step: int = 0  # 1-7
    feature_id: Optional[str] = None
    project_id: Optional[str] = None
    feature_title: str = ""
    feature_description: str = ""

    # Accumulated data from each step
    feature_spec: str = ""
    user_story: str = ""
    functional_analysis: str = ""
    flowchart: str = ""
    pseudocode: str = ""
    tdd_tests: str = ""
    documentation: str = ""
    
    # User edits at each step
    user_edits: Dict[int, list] = field(default_factory=dict)
    
    # Verification results
    verification_results: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            "current_step": self.current_step,
            "feature_id": self.feature_id,
            "project_id": self.project_id,
            "feature_title": self.feature_title,
            "feature_description": self.feature_description,
            "feature_spec": self.feature_spec,
            "user_story": self.user_story,
            "functional_analysis": self.functional_analysis,
            "flowchart": self.flowchart,
            "pseudocode": self.pseudocode,
            "tdd_tests": self.tdd_tests,
            "documentation": self.documentation,
            "user_edits": self.user_edits,
            "verification_results": self.verification_results,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WizardState":
        """Create from dictionary"""
        return cls(
            current_step=data.get("current_step", 0),
            feature_id=data.get("feature_id"),
            project_id=data.get("project_id"),
            feature_title=data.get("feature_title", ""),
            feature_description=data.get("feature_description", ""),
            feature_spec=data.get("feature_spec", ""),
            user_story=data.get("user_story", ""),
            functional_analysis=data.get("functional_analysis", ""),
            flowchart=data.get("flowchart", ""),
            pseudocode=data.get("pseudocode", ""),
            tdd_tests=data.get("tdd_tests", ""),
            documentation=data.get("documentation", ""),
            user_edits=data.get("user_edits", {}),
            verification_results=data.get("verification_results", {}),
        )


# ============================================================================
# Session Manager
# ============================================================================
class SessionManager:
    """
    Session manager for Dobby v2.0
    
    Provides:
    - Create sessions (wizard, editor, yolo)
    - Save session state
    - Load session state (resume)
    - Cleanup old sessions
    """
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    def create_session(
        self,
        project_id: str,
        session_type: SessionType = "wizard",
    ) -> str:
        """
        Create a new session
        
        Args:
            project_id: Project ID
            session_type: Type of session (wizard, editor, yolo)
        
        Returns:
            Session ID
        """
        with self.db.get_session() as session:
            session_id = str(uuid.uuid4())
            
            db_session = DBSession(
                id=session_id,
                project_id=project_id,
                session_type=session_type,
                current_step=0,
                state={},
            )
            
            session.add(db_session)
            session.commit()
            session.refresh(db_session)
            
            return session_id
    
    def save_wizard_state(
        self,
        session_id: str,
        wizard_state: WizardState,
    ):
        """Save wizard state to database"""
        with self.db.get_session() as session:
            db_session = session.query(DBSession).filter(DBSession.id == session_id).first()
            
            if not db_session:
                raise ValueError(f"Session not found: {session_id}")
            
            db_session.current_step = wizard_state.current_step
            db_session.state = wizard_state.to_dict()
            db_session.last_active = datetime.utcnow()
            
            session.commit()
    
    def load_wizard_state(self, session_id: str) -> Optional[WizardState]:
        """Load wizard state from database"""
        with self.db.get_session() as session:
            db_session = session.query(DBSession).filter(DBSession.id == session_id).first()
            
            if not db_session:
                return None
            
            if db_session.session_type != "wizard":
                raise ValueError(f"Session is not a wizard session: {session_id}")
            
            return WizardState.from_dict(db_session.state)
    
    def save_state(self, session_id: str, state: Dict[str, Any]):
        """Save generic state to database"""
        with self.db.get_session() as session:
            db_session = session.query(DBSession).filter(DBSession.id == session_id).first()
            
            if not db_session:
                raise ValueError(f"Session not found: {session_id}")
            
            db_session.state = state
            db_session.last_active = datetime.utcnow()
            
            session.commit()
    
    def load_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load state from database"""
        with self.db.get_session() as session:
            db_session = session.query(DBSession).filter(DBSession.id == session_id).first()
            
            if not db_session:
                return None
            
            return db_session.state
    
    def cleanup_old_sessions(
        self,
        project_id: str,
        max_age_days: int = 30,
    ) -> int:
        """
        Cleanup old sessions
        
        Args:
            project_id: Project ID
            max_age_days: Maximum age in days
        
        Returns:
            Number of sessions deleted
        """
        cutoff_date = datetime.utcnow() - timedelta(days=max_age_days)
        
        with self.db.get_session() as session:
            old_sessions = (
                session.query(DBSession)
                .filter(
                    DBSession.project_id == project_id,
                    DBSession.last_active < cutoff_date,
                )
                .all()
            )
            
            deleted_count = 0
            for db_session in old_sessions:
                session.delete(db_session)
                deleted_count += 1
            
            session.commit()
            
            return deleted_count
    
    def get_active_sessions(self, project_id: str) -> list:
        """Get all active sessions for a project"""
        with self.db.get_session() as session:
            active_sessions = (
                session.query(DBSession)
                .filter(
                    DBSession.project_id == project_id,
                    DBSession.last_active > datetime.utcnow() - timedelta(hours=24),
                )
                .all()
            )
            
            return [
                {
                    "session_id": s.id,
                    "session_type": s.session_type,
                    "current_step": s.current_step,
                    "last_active": s.last_active,
                }
                for s in active_sessions
            ]


# ============================================================================
# Factory Function
# ============================================================================
def get_session_manager(db: DatabaseManager) -> SessionManager:
    """Get session manager instance"""
    return SessionManager(db)

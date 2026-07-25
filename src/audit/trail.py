"""
Audit Trail System for Dobby v2.0

Tracks every change in the system:
- Who made the change (user_id)
- What changed (action, old_content, new_content)
- When (timestamp)
- Which node/project was affected

Provides:
- Complete audit trail for compliance
- Change history for debugging
- Revert capability (restore previous versions)
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from datetime import datetime
import json
import uuid

from src.db.schema import DatabaseManager, AuditEntry, Project, Node


# ============================================================================
# Audit Actions
# ============================================================================
class AuditAction:
    """Standard audit actions"""
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    VERIFY = "verify"
    FINALIZE = "finalize"
    REVERT = "revert"
    EXPORT = "export"


# ============================================================================
# Audit Entry Dataclass
# ============================================================================
@dataclass
class AuditLogEntry:
    """
    Audit log entry
    
    Attributes:
        entry_id: Unique identifier
        project_id: Project ID
        node_id: Node ID (if applicable)
        action: What happened (create, update, delete, etc.)
        old_content: Previous state (JSON string)
        new_content: New state (JSON string)
        user_id: Who made the change
        metadata: Additional context
        timestamp: When it happened
    """
    
    entry_id: str
    project_id: str
    node_id: Optional[str]
    action: str
    old_content: Optional[Dict[str, Any]]
    new_content: Optional[Dict[str, Any]]
    user_id: Optional[str]
    metadata: Dict[str, Any]
    timestamp: datetime
    
    def __post_init__(self):
        if not self.entry_id:
            self.entry_id = str(uuid.uuid4())
        if not self.timestamp:
            self.timestamp = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "entry_id": self.entry_id,
            "project_id": self.project_id,
            "node_id": self.node_id,
            "action": self.action,
            "old_content": self.old_content,
            "new_content": self.new_content,
            "user_id": self.user_id,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuditLogEntry":
        """Create from dictionary"""
        return cls(
            entry_id=data.get("entry_id", str(uuid.uuid4())),
            project_id=data["project_id"],
            node_id=data.get("node_id"),
            action=data["action"],
            old_content=data.get("old_content"),
            new_content=data.get("new_content"),
            user_id=data.get("user_id"),
            metadata=data.get("metadata", {}),
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.utcnow(),
        )


# ============================================================================
# Audit Trail Manager
# ============================================================================
class AuditTrailManager:
    """
    Audit trail manager for Dobby v2.0
    
    Provides:
    - Log changes (create, update, delete, verify, etc.)
    - Query audit trail (by project, node, action, date range)
    - Get change history for a node
    - Revert to previous version
    """
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    def log(
        self,
        project_id: str,
        action: str,
        old_content: Optional[Dict[str, Any]] = None,
        new_content: Optional[Dict[str, Any]] = None,
        node_id: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Log an audit entry
        
        Args:
            project_id: Project ID
            action: What happened (create, update, delete, etc.)
            old_content: Previous state
            new_content: New state
            node_id: Node ID (if applicable)
            user_id: User who made the change
            metadata: Additional context
        
        Returns:
            Audit entry ID
        """
        with self.db.get_session() as session:
            entry_id = str(uuid.uuid4())
            
            db_entry = AuditEntry(
                id=entry_id,
                project_id=project_id,
                node_id=node_id,
                action=action,
                old_content=json.dumps(old_content) if old_content else None,
                new_content=json.dumps(new_content) if new_content else None,
                user_id=user_id,
                extra_metadata=metadata or {},
            )
            
            session.add(db_entry)
            session.commit()
            session.refresh(db_entry)
            
            return entry_id
    
    def log_create(
        self,
        project_id: str,
        new_content: Dict[str, Any],
        node_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """Log a create action"""
        return self.log(
            project_id=project_id,
            action=AuditAction.CREATE,
            old_content=None,
            new_content=new_content,
            node_id=node_id,
            user_id=user_id,
        )
    
    def log_update(
        self,
        project_id: str,
        old_content: Dict[str, Any],
        new_content: Dict[str, Any],
        node_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """Log an update action"""
        return self.log(
            project_id=project_id,
            action=AuditAction.UPDATE,
            old_content=old_content,
            new_content=new_content,
            node_id=node_id,
            user_id=user_id,
        )
    
    def log_delete(
        self,
        project_id: str,
        old_content: Dict[str, Any],
        node_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """Log a delete action"""
        return self.log(
            project_id=project_id,
            action=AuditAction.DELETE,
            old_content=old_content,
            new_content=None,
            node_id=node_id,
            user_id=user_id,
        )
    
    def log_verify(
        self,
        project_id: str,
        node_id: str,
        verification_result: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> str:
        """Log a verification action"""
        return self.log(
            project_id=project_id,
            action=AuditAction.VERIFY,
            old_content=None,
            new_content=verification_result,
            node_id=node_id,
            user_id=user_id,
            metadata={"type": "verification"},
        )
    
    def log_finalize(
        self,
        project_id: str,
        node_id: str,
        user_id: Optional[str] = None,
    ) -> str:
        """Log a finalize action"""
        return self.log(
            project_id=project_id,
            action=AuditAction.FINALIZE,
            old_content=None,
            new_content={"status": "finalized"},
            node_id=node_id,
            user_id=user_id,
        )
    
    def get_audit_trail(
        self,
        project_id: str,
        node_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AuditLogEntry]:
        """
        Get audit trail for a project
        
        Args:
            project_id: Project ID
            node_id: Filter by node ID (optional)
            action: Filter by action (optional)
            limit: Maximum number of entries
            offset: Offset for pagination
        
        Returns:
            List of audit entries (newest first)
        """
        with self.db.get_session() as session:
            query = session.query(AuditEntry).filter(AuditEntry.project_id == project_id)
            
            if node_id:
                query = query.filter(AuditEntry.node_id == node_id)
            
            if action:
                query = query.filter(AuditEntry.action == action)
            
            entries = (
                query.order_by(AuditEntry.timestamp.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            
            return [
                AuditLogEntry(
                    entry_id=e.id,
                    project_id=e.project_id,
                    node_id=e.node_id,
                    action=e.action,
                    old_content=json.loads(e.old_content) if e.old_content else None,
                    new_content=json.loads(e.new_content) if e.new_content else None,
                    user_id=e.user_id,
                    metadata=e.extra_metadata or {},
                    timestamp=e.timestamp,
                )
                for e in entries
            ]
    
    def get_change_history(
        self,
        node_id: str,
        limit: int = 50,
    ) -> List[AuditLogEntry]:
        """
        Get change history for a specific node
        
        Args:
            node_id: Node ID
            limit: Maximum number of entries
        
        Returns:
            List of audit entries (newest first)
        """
        with self.db.get_session() as session:
            entries = (
                session.query(AuditEntry)
                .filter(AuditEntry.node_id == node_id)
                .order_by(AuditEntry.timestamp.desc())
                .limit(limit)
                .all()
            )
            
            return [
                AuditLogEntry(
                    entry_id=e.id,
                    project_id=e.project_id,
                    node_id=e.node_id,
                    action=e.action,
                    old_content=json.loads(e.old_content) if e.old_content else None,
                    new_content=json.loads(e.new_content) if e.new_content else None,
                    user_id=e.user_id,
                    metadata=e.extra_metadata or {},
                    timestamp=e.timestamp,
                )
                for e in entries
            ]
    
    def get_previous_version(
        self,
        node_id: str,
        version_index: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """
        Get previous version of a node
        
        Args:
            node_id: Node ID
            version_index: Which version to get (0 = most recent, 1 = previous, etc.)
        
        Returns:
            Previous version content (or None if not found)
        """
        history = self.get_change_history(node_id, limit=version_index + 2)
        
        if len(history) <= version_index:
            return None
        
        entry = history[version_index]
        
        # For update actions, return old_content
        if entry.action == AuditAction.UPDATE and entry.old_content:
            return entry.old_content
        
        # For create actions, return new_content
        if entry.action == AuditAction.CREATE and entry.new_content:
            return entry.new_content
        
        return None
    
    def revert_to_version(
        self,
        project_id: str,
        node_id: str,
        version_index: int,
        user_id: Optional[str] = None,
    ) -> bool:
        """
        Revert node to a previous version
        
        Args:
            project_id: Project ID
            node_id: Node ID
            version_index: Which version to revert to
            user_id: User performing the revert
        
        Returns:
            True if successful
        """
        from src.db.schema import Node as DBNode
        
        previous_version = self.get_previous_version(node_id, version_index)
        
        if not previous_version:
            raise ValueError(f"Version {version_index} not found for node {node_id}")
        
        with self.db.get_session() as session:
            # Get current node
            db_node = session.query(DBNode).filter(DBNode.id == node_id).first()
            
            if not db_node:
                raise ValueError(f"Node not found: {node_id}")
            
            # Store current state for audit
            current_state = {
                "title": db_node.title,
                "content": db_node.content,
                "status": db_node.status,
                "metadata": db_node.extra_metadata,
            }

            # Update node with previous version
            db_node.title = previous_version.get("title", db_node.title)
            db_node.content = previous_version.get("content", db_node.content)
            db_node.status = previous_version.get("status", db_node.status)
            db_node.extra_metadata = previous_version.get("metadata", db_node.extra_metadata)
            db_node.version += 1
            db_node.updated_at = datetime.utcnow()
            
            # Log the revert
            self.log(
                project_id=project_id,
                action=AuditAction.REVERT,
                old_content=current_state,
                new_content=previous_version,
                node_id=node_id,
                user_id=user_id,
                metadata={
                    "reverted_to_version": version_index,
                },
            )
            
            session.commit()
            
            return True
    
    def export_audit_trail(
        self,
        project_id: str,
        output_path: str,
    ) -> str:
        """
        Export audit trail to JSON file
        
        Args:
            project_id: Project ID
            output_path: Output file path
        
        Returns:
            Output file path
        """
        from pathlib import Path
        
        entries = self.get_audit_trail(project_id, limit=10000)
        
        output_path = Path(output_path).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "w") as f:
            json.dump(
                {
                    "project_id": project_id,
                    "exported_at": datetime.utcnow().isoformat(),
                    "total_entries": len(entries),
                    "entries": [entry.to_dict() for entry in entries],
                },
                f,
                indent=2,
            )
        
        return str(output_path)


# ============================================================================
# Factory Function
# ============================================================================
def get_audit_trail_manager(db: DatabaseManager) -> AuditTrailManager:
    """Get audit trail manager instance"""
    return AuditTrailManager(db)

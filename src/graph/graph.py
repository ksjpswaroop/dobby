"""
Graph Data Structures for Dobby v2.0

Implements:
- Node: Graph node (Idea, Feature, Story, etc.)
- Edge: Relationship between nodes
- Graph: Full document graph with traversal, queries, visualization
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Any, Literal
from enum import Enum
from pathlib import Path
import json
import hashlib
from datetime import datetime


# ============================================================================
# Node Types
# ============================================================================
class NodeType(str, Enum):
    """Types of nodes in the document graph"""
    IDEA = "idea"
    FEATURE = "feature"
    USER_STORY = "user_story"
    FUNCTIONAL_ANALYSIS = "functional_analysis"
    FLOWCHART = "flowchart"
    PSEUDOCODE = "pseudocode"
    TDD_TESTS = "tdd_tests"
    DOCUMENTATION = "documentation"
    PRD = "prd"
    ARCHITECTURE = "architecture"
    BACKLOG = "backlog"
    OTHER = "other"


# ============================================================================
# Edge Types
# ============================================================================
class EdgeType(str, Enum):
    """Types of edges (relationships) between nodes"""
    GENERATES = "generates"  # Feature generates UserStory
    REFINES = "refines"  # UserStory refines FunctionalAnalysis
    IMPLEMENTS = "implements"  # Pseudocode implements Flowchart
    TESTS = "tests"  # TDDTests tests Pseudocode
    DOCUMENTS = "documents"  # Documentation documents TDDTests
    DEPENDS_ON = "depends_on"  # Feature depends on another Feature
    AGGREGATES = "aggregates"  # PRD aggregates Features
    RELATED_TO = "related_to"  # General relationship


# ============================================================================
# Node Status
# ============================================================================
class NodeStatus(str, Enum):
    """Status of a node"""
    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    VERIFIED = "verified"
    FINALIZED = "finalized"


# ============================================================================
# Graph Node
# ============================================================================
@dataclass
class GraphNode:
    """
    Graph node representing any entity in the document graph
    
    Attributes:
        node_id: Unique identifier (UUID)
        node_type: Type of node (Feature, UserStory, etc.)
        title: Human-readable title
        content: Main content (Markdown)
        status: Current status (draft, verified, finalized)
        parent_id: ID of parent node (if any)
        children: List of child node IDs
        metadata: Additional metadata (JSON)
        version: Version number (increments on each edit)
        created_at: Creation timestamp
        updated_at: Last update timestamp
        content_hash: SHA256 hash of content (for change detection)
    """
    
    node_id: str
    node_type: NodeType
    title: str
    content: str = ""
    status: NodeStatus = NodeStatus.DRAFT
    parent_id: Optional[str] = None
    children: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    version: int = 1
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    content_hash: str = ""
    
    def __post_init__(self):
        """Calculate content hash after initialization"""
        if not self.content_hash:
            self.content_hash = self._calculate_hash()
    
    def _calculate_hash(self) -> str:
        """Calculate SHA256 hash of content"""
        return hashlib.sha256(self.content.encode()).hexdigest()
    
    def update_content(self, new_content: str):
        """Update content and recalculate hash"""
        self.content = new_content
        self.content_hash = self._calculate_hash()
        self.version += 1
        self.updated_at = datetime.utcnow()
    
    def add_child(self, child_id: str):
        """Add child node ID"""
        if child_id not in self.children:
            self.children.append(child_id)
            self.updated_at = datetime.utcnow()
    
    def remove_child(self, child_id: str):
        """Remove child node ID"""
        if child_id in self.children:
            self.children.remove(child_id)
            self.updated_at = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "title": self.title,
            "content": self.content,
            "status": self.status.value,
            "parent_id": self.parent_id,
            "children": self.children,
            "metadata": self.metadata,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "content_hash": self.content_hash,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphNode":
        """Create from dictionary"""
        return cls(
            node_id=data["node_id"],
            node_type=NodeType(data["node_type"]),
            title=data["title"],
            content=data.get("content", ""),
            status=NodeStatus(data.get("status", "draft")),
            parent_id=data.get("parent_id"),
            children=data.get("children", []),
            metadata=data.get("metadata", {}),
            version=data.get("version", 1),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            content_hash=data.get("content_hash", ""),
        )
    
    def __repr__(self):
        return f"<GraphNode(id='{self.node_id}', type='{self.node_type.value}', title='{self.title}')>"


# ============================================================================
# Graph Edge
# ============================================================================
@dataclass
class GraphEdge:
    """
    Graph edge representing relationship between two nodes
    
    Attributes:
        edge_id: Unique identifier (UUID)
        source_node_id: ID of source node
        target_node_id: ID of target node
        edge_type: Type of relationship
        metadata: Additional metadata (JSON)
        created_at: Creation timestamp
    """
    
    edge_id: str
    source_node_id: str
    target_node_id: str
    edge_type: EdgeType
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "edge_id": self.edge_id,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "edge_type": self.edge_type.value,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphEdge":
        """Create from dictionary"""
        return cls(
            edge_id=data["edge_id"],
            source_node_id=data["source_node_id"],
            target_node_id=data["target_node_id"],
            edge_type=EdgeType(data["edge_type"]),
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(data["created_at"]),
        )
    
    def __repr__(self):
        return f"<GraphEdge(type='{self.edge_type.value}', from='{self.source_node_id}' to='{self.target_node_id}')>"


# ============================================================================
# Document Graph
# ============================================================================
class DocumentGraph:
    """
    Document graph for managing nodes and edges
    
    Provides:
    - Add/remove nodes and edges
    - Traverse graph (BFS, DFS)
    - Query nodes by type, status, etc.
    - Get dependencies and dependents
    - Export to various formats (JSON, Mermaid, DOT)
    """
    
    def __init__(self):
        self.nodes: Dict[str, GraphNode] = {}
        self.edges: Dict[str, GraphEdge] = {}
        self.adjacency_list: Dict[str, List[str]] = {}  # node_id -> list of edge_ids
    
    def add_node(self, node: GraphNode):
        """Add node to graph"""
        self.nodes[node.node_id] = node
        self.adjacency_list[node.node_id] = []
    
    def remove_node(self, node_id: str):
        """Remove node from graph"""
        if node_id not in self.nodes:
            return
        
        # Remove all edges connected to this node
        edges_to_remove = [
            edge_id for edge_id, edge in self.edges.items()
            if edge.source_node_id == node_id or edge.target_node_id == node_id
        ]
        
        for edge_id in edges_to_remove:
            self.remove_edge(edge_id)
        
        # Remove node
        del self.nodes[node_id]
        del self.adjacency_list[node_id]
    
    def add_edge(self, edge: GraphEdge):
        """Add edge to graph"""
        self.edges[edge.edge_id] = edge
        
        # Update adjacency list
        if edge.source_node_id in self.adjacency_list:
            self.adjacency_list[edge.source_node_id].append(edge.edge_id)
    
    def remove_edge(self, edge_id: str):
        """Remove edge from graph"""
        if edge_id not in self.edges:
            return
        
        edge = self.edges[edge_id]
        
        # Remove from adjacency list
        if edge.source_node_id in self.adjacency_list:
            if edge_id in self.adjacency_list[edge.source_node_id]:
                self.adjacency_list[edge.source_node_id].remove(edge_id)
        
        # Remove edge
        del self.edges[edge_id]
    
    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Get node by ID"""
        return self.nodes.get(node_id)
    
    def get_nodes_by_type(self, node_type: NodeType) -> List[GraphNode]:
        """Get all nodes of a specific type"""
        return [
            node for node in self.nodes.values()
            if node.node_type == node_type
        ]
    
    def get_nodes_by_status(self, status: NodeStatus) -> List[GraphNode]:
        """Get all nodes with a specific status"""
        return [
            node for node in self.nodes.values()
            if node.status == status
        ]
    
    def get_edges_for_node(self, node_id: str) -> List[GraphEdge]:
        """Get all edges connected to a node"""
        edge_ids = self.adjacency_list.get(node_id, [])
        return [self.edges[edge_id] for edge_id in edge_ids if edge_id in self.edges]
    
    def get_dependencies(self, node_id: str) -> List[str]:
        """Get all nodes that this node depends on"""
        dependencies = []
        
        for edge in self.edges.values():
            if edge.target_node_id == node_id and edge.edge_type == EdgeType.DEPENDS_ON:
                dependencies.append(edge.source_node_id)
        
        return dependencies
    
    def get_dependents(self, node_id: str) -> List[str]:
        """Get all nodes that depend on this node"""
        dependents = []
        
        for edge in self.edges.values():
            if edge.source_node_id == node_id and edge.edge_type == EdgeType.DEPENDS_ON:
                dependents.append(edge.target_node_id)
        
        return dependents
    
    def traverse_bfs(self, start_node_id: str) -> List[str]:
        """Breadth-first traversal from start node"""
        if start_node_id not in self.nodes:
            return []
        
        visited = set()
        queue = [start_node_id]
        result = []
        
        while queue:
            node_id = queue.pop(0)
            
            if node_id in visited:
                continue
            
            visited.add(node_id)
            result.append(node_id)
            
            # Add children
            if node_id in self.adjacency_list:
                for edge_id in self.adjacency_list[node_id]:
                    edge = self.edges.get(edge_id)
                    if edge and edge.target_node_id not in visited:
                        queue.append(edge.target_node_id)
        
        return result
    
    def traverse_dfs(self, start_node_id: str) -> List[str]:
        """Depth-first traversal from start node"""
        if start_node_id not in self.nodes:
            return []
        
        visited = set()
        result = []
        
        def dfs(node_id: str):
            if node_id in visited:
                return
            
            visited.add(node_id)
            result.append(node_id)
            
            # Visit children
            if node_id in self.adjacency_list:
                for edge_id in self.adjacency_list[node_id]:
                    edge = self.edges.get(edge_id)
                    if edge:
                        dfs(edge.target_node_id)
        
        dfs(start_node_id)
        return result
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert graph to dictionary"""
        return {
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "edges": [edge.to_dict() for edge in self.edges.values()],
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert graph to JSON string"""
        return json.dumps(self.to_dict(), indent=indent)
    
    def to_mermaid(self) -> str:
        """
        Convert graph to Mermaid diagram syntax
        
        Returns Mermaid flowchart that can be rendered in UI
        """
        lines = ["graph TD"]
        
        # Add nodes
        for node in self.nodes.values():
            node_id = node.node_id.replace("-", "_")
            label = f"{node.title} ({node.node_type.value})"
            lines.append(f"    {node_id}[\"{label}\"]")
        
        # Add edges
        for edge in self.edges.values():
            source = edge.source_node_id.replace("-", "_")
            target = edge.target_node_id.replace("-", "_")
            lines.append(f"    {source} -->|{edge.edge_type.value}| {target}")
        
        return "\n".join(lines)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get graph statistics"""
        node_types = {}
        node_statuses = {}
        
        for node in self.nodes.values():
            # Count by type
            node_type = node.node_type.value
            node_types[node_type] = node_types.get(node_type, 0) + 1
            
            # Count by status
            node_status = node.status.value
            node_statuses[node_status] = node_statuses.get(node_status, 0) + 1
        
        return {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "nodes_by_type": node_types,
            "nodes_by_status": node_statuses,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DocumentGraph":
        """Create graph from dictionary"""
        graph = cls()
        
        # Add nodes
        for node_data in data.get("nodes", []):
            node = GraphNode.from_dict(node_data)
            graph.add_node(node)
        
        # Add edges
        for edge_data in data.get("edges", []):
            edge = GraphEdge.from_dict(edge_data)
            graph.add_edge(edge)
        
        return graph

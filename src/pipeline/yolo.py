"""
YOLO Mode Pipeline for Dobby v2.0

Instant generation mode that bypasses the wizard:
- Generates all 7 steps in one go (no user intervention)
- Verifies final output deterministically
- Presents result for user review
- User can accept, edit, or reject

Much faster than wizard mode (~2-5 minutes vs ~30 minutes)
but with less user control during generation.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from datetime import datetime
import structlog
import uuid

from src.db.schema import DatabaseManager, Project, Node, Edge
from src.graph.graph import DocumentGraph, GraphNode, GraphEdge, NodeType, EdgeType, NodeStatus
from src.llm.ollama_client import OllamaClient, get_ollama_client
from src.verifiers.deterministic_verifier import DeterministicVerifier, get_verifier, VerificationResult
from src.sessions.manager import SessionManager, get_session_manager

logger = structlog.get_logger()


# ============================================================================
# YOLO Result Types
# ============================================================================
@dataclass
class YOLOGenerationResult:
    """Result of YOLO generation"""
    success: bool
    feature_node_id: str
    all_node_ids: List[str]
    all_content: Dict[str, str]  # step_name -> content
    verification: Optional[VerificationResult]
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "feature_node_id": self.feature_node_id,
            "all_node_ids": self.all_node_ids,
            "all_content": self.all_content,
            "verification": self.verification.to_dict() if self.verification else None,
            "error": self.error,
        }


@dataclass
class YOLOAcceptanceResult:
    """Result of accepting YOLO generation"""
    success: bool
    feature_node_id: str
    all_node_ids: List[str]
    message: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "feature_node_id": self.feature_node_id,
            "all_node_ids": self.all_node_ids,
            "message": self.message,
        }


# ============================================================================
# YOLO Pipeline
# ============================================================================
class YOLOPipeline:
    """
    YOLO Mode Pipeline
    
    Instant generation with:
    - All 7 steps generated at once
    - Single verification at the end
    - User review and accept/reject
    - Fast (~2-5 minutes)
    """
    
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.session_manager = get_session_manager(db)
        self.verifier = get_verifier()
        self.ollama: Optional[OllamaClient] = None
    
    async def initialize(self):
        """Initialize Ollama client using the user-configured host/model."""
        from src.settings import get_settings

        s = get_settings()
        self.ollama = await get_ollama_client(base_url=s.ollama_host, model=s.model)
    
    async def close(self):
        """Close Ollama client"""
        if self.ollama:
            await self.ollama.close()
    
    async def generate_instant(
        self,
        project_id: str,
        feature_title: str,
        feature_description: str,
        user_id: Optional[str] = None,
    ) -> YOLOGenerationResult:
        """
        Generate complete feature documentation instantly
        
        Args:
            project_id: Project ID
            feature_title: Title of the feature
            feature_description: Description of the feature
            user_id: User ID (optional)
        
        Returns:
            YOLOGenerationResult with all generated content
        """
        if not self.ollama:
            raise RuntimeError("Ollama client not initialized. Call initialize() first.")
        
        logger.info(
            "yolo_generation_started",
            project_id=project_id,
            feature_title=feature_title,
        )
        
        try:
            # Create session for tracking
            session_id = self.session_manager.create_session(
                project_id=project_id,
                session_type="yolo",
            )
            
            # Create feature node
            with self.db.get_session() as session:
                feature_node_id = str(uuid.uuid4())
                
                feature_node = Node(
                    id=feature_node_id,
                    project_id=project_id,
                    node_type="feature",
                    title=feature_title,
                    content=feature_description,
                    status="in_progress",
                )
                
                session.add(feature_node)
                session.commit()
            
            # Generate all 7 steps sequentially
            all_content: Dict[str, str] = {}
            
            # Step 1: Feature Specification
            logger.info("yolo_step_1_generating", step="feature_spec")
            feature_spec = await self.ollama.generate_feature_spec(
                product_name="Product",
                idea=feature_description,
                feature_title=feature_title,
            )
            all_content["feature_spec"] = feature_spec
            
            # Step 2: User Story
            logger.info("yolo_step_2_generating", step="user_story")
            user_story = await self.ollama.generate_user_story(
                feature_spec=feature_spec,
            )
            all_content["user_story"] = user_story
            
            # Step 3: Functional Analysis
            logger.info("yolo_step_3_generating", step="functional_analysis")
            functional_analysis = await self.ollama.generate_functional_analysis(
                user_story=user_story,
            )
            all_content["functional_analysis"] = functional_analysis
            
            # Step 4: Flowchart
            logger.info("yolo_step_4_generating", step="flowchart")
            flowchart = await self.ollama.generate_flowchart(
                functional_analysis=functional_analysis,
            )
            all_content["flowchart"] = flowchart
            
            # Step 5: Pseudocode
            logger.info("yolo_step_5_generating", step="pseudocode")
            pseudocode = await self.ollama.generate_pseudocode(
                flowchart=flowchart,
            )
            all_content["pseudocode"] = pseudocode
            
            # Step 6: TDD Tests
            logger.info("yolo_step_6_generating", step="tdd_tests")
            tdd_tests = await self.ollama.generate_tdd_tests(
                pseudocode=pseudocode,
            )
            all_content["tdd_tests"] = tdd_tests
            
            # Step 7: Documentation
            logger.info("yolo_step_7_generating", step="documentation")
            documentation = await self.ollama.generate_documentation(
                tdd_tests=tdd_tests,
            )
            all_content["documentation"] = documentation
            
            # Combine all content for verification
            combined_content = f"""
# {feature_title}

## Feature Specification
{feature_spec}

## User Story
{user_story}

## Functional Analysis
{functional_analysis}

## Flowchart
{flowchart}

## Pseudocode
{pseudocode}

## TDD Tests
{tdd_tests}

## Documentation
{documentation}
""".strip()
            
            # Verify combined content
            logger.info("yolo_verifying_final_output")
            verification = await self.verifier.verify_section(
                section_id=feature_node_id,
                content=combined_content,
                node_type="feature",
                context={
                    "terminology": {},
                    "all_sections": [],
                },
            )
            
            # Create nodes for all steps
            all_node_ids = [feature_node_id]
            
            with self.db.get_session() as session:
                step_nodes = [
                    ("feature_spec", "feature", feature_spec),
                    ("user_story", "user_story", user_story),
                    ("functional_analysis", "functional_analysis", functional_analysis),
                    ("flowchart", "flowchart", flowchart),
                    ("pseudocode", "pseudocode", pseudocode),
                    ("tdd_tests", "tdd_tests", tdd_tests),
                    ("documentation", "documentation", documentation),
                ]
                
                for step_name, node_type, content in step_nodes:
                    node_id = str(uuid.uuid4())
                    
                    node = Node(
                        id=node_id,
                        project_id=project_id,
                        node_type=node_type,
                        title=step_name.replace("_", " ").title(),
                        content=content,
                        status="draft",  # Draft until accepted
                        parent_id=feature_node_id,
                    )
                    
                    session.add(node)
                    all_node_ids.append(node_id)
                    
                    # Create edge
                    edge_id = str(uuid.uuid4())
                    edge = Edge(
                        id=edge_id,
                        project_id=project_id,
                        source_node_id=feature_node_id,
                        target_node_id=node_id,
                        edge_type="generates",
                    )
                    
                    session.add(edge)
                
                # Update feature node status
                feature_node = session.query(Node).filter(Node.id == feature_node_id).first()
                if feature_node:
                    feature_node.status = "pending_review"
                
                session.commit()
            
            logger.info(
                "yolo_generation_completed",
                feature_node_id=feature_node_id,
                total_nodes=len(all_node_ids),
                verification_score=verification.overall_score,
                passed=verification.passed,
            )
            
            return YOLOGenerationResult(
                success=True,
                feature_node_id=feature_node_id,
                all_node_ids=all_node_ids,
                all_content=all_content,
                verification=verification,
            )
        
        except Exception as e:
            logger.error(
                "yolo_generation_failed",
                feature_title=feature_title,
                error=str(e),
            )
            
            return YOLOGenerationResult(
                success=False,
                feature_node_id="",
                all_node_ids=[],
                all_content={},
                verification=None,
                error=str(e),
            )
    
    async def accept_generation(
        self,
        project_id: str,
        feature_node_id: str,
        user_id: Optional[str] = None,
    ) -> YOLOAcceptanceResult:
        """
        Accept YOLO generation and finalize all nodes
        
        Args:
            project_id: Project ID
            feature_node_id: Feature node ID
            user_id: User ID (optional)
        
        Returns:
            YOLOAcceptanceResult
        """
        with self.db.get_session() as session:
            # Update feature node status
            feature_node = session.query(Node).filter(Node.id == feature_node_id).first()
            
            if not feature_node:
                return YOLOAcceptanceResult(
                    success=False,
                    feature_node_id=feature_node_id,
                    all_node_ids=[],
                    message="Feature node not found",
                )
            
            # Update all child nodes to verified
            child_nodes = (
                session.query(Node)
                .filter(Node.parent_id == feature_node_id)
                .all()
            )
            
            for node in child_nodes:
                node.status = "verified"
            
            # Update feature node to finalized
            feature_node.status = "finalized"
            feature_node.updated_at = datetime.utcnow()
            
            session.commit()
            
            logger.info(
                "yolo_generation_accepted",
                feature_node_id=feature_node_id,
                total_nodes=len(child_nodes) + 1,
            )
            
            return YOLOAcceptanceResult(
                success=True,
                feature_node_id=feature_node_id,
                all_node_ids=[feature_node_id] + [n.id for n in child_nodes],
                message="Generation accepted and finalized",
            )
    
    async def reject_generation(
        self,
        project_id: str,
        feature_node_id: str,
        reason: Optional[str] = None,
    ) -> bool:
        """
        Reject YOLO generation and delete all nodes
        
        Args:
            project_id: Project ID
            feature_node_id: Feature node ID
            reason: Reason for rejection (optional)
        
        Returns:
            True if successful
        """
        with self.db.get_session() as session:
            # Delete all child nodes
            child_nodes = (
                session.query(Node)
                .filter(Node.parent_id == feature_node_id)
                .all()
            )
            
            for node in child_nodes:
                session.delete(node)
            
            # Delete feature node
            feature_node = session.query(Node).filter(Node.id == feature_node_id).first()
            if feature_node:
                session.delete(feature_node)
            
            session.commit()
            
            logger.info(
                "yolo_generation_rejected",
                feature_node_id=feature_node_id,
                reason=reason,
            )
            
            return True
    
    async def edit_and_accept(
        self,
        project_id: str,
        feature_node_id: str,
        edited_content: Dict[str, str],
        user_id: Optional[str] = None,
    ) -> YOLOAcceptanceResult:
        """
        Edit generated content and accept
        
        Args:
            project_id: Project ID
            feature_node_id: Feature node ID
            edited_content: Dict of step_name -> edited_content
            user_id: User ID (optional)
        
        Returns:
            YOLOAcceptanceResult
        """
        with self.db.get_session() as session:
            # Update nodes with edited content
            for step_name, content in edited_content.items():
                node = (
                    session.query(Node)
                    .filter(
                        Node.parent_id == feature_node_id,
                        Node.node_type == step_name,
                    )
                    .first()
                )
                
                if node:
                    node.content = content
                    node.status = "verified"
                    node.updated_at = datetime.utcnow()
            
            # Update feature node to finalized
            feature_node = session.query(Node).filter(Node.id == feature_node_id).first()
            if feature_node:
                feature_node.status = "finalized"
                feature_node.updated_at = datetime.utcnow()
            
            session.commit()
            
            logger.info(
                "yolo_generation_edited_and_accepted",
                feature_node_id=feature_node_id,
                edited_steps=list(edited_content.keys()),
            )
            
            return YOLOAcceptanceResult(
                success=True,
                feature_node_id=feature_node_id,
                all_node_ids=[feature_node_id],
                message="Generation edited and accepted",
            )


# ============================================================================
# Factory Function
# ============================================================================
async def get_yolo_pipeline(db: DatabaseManager) -> YOLOPipeline:
    """Get YOLO pipeline instance"""
    pipeline = YOLOPipeline(db)
    await pipeline.initialize()
    return pipeline

"""
7-Step Wizard Pipeline for Dobby v2.0

Orchestrates feature documentation generation through 7 steps:
1. Feature Specification
2. User Story
3. Functional Analysis
4. Flowchart
5. Pseudocode
6. TDD Tests
7. Documentation

Each step:
- Generates content via Ollama
- Verifies with Deterministic Verifier
- Allows user edits
- Persists state to database
- Proceeds only if verification passes (≥85%)

State machine ensures users can resume anytime.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum
import structlog
import uuid

from src.db.schema import DatabaseManager, Project, Node, Edge, Session
from src.llm.ollama_client import OllamaClient, get_ollama_client
from src.verifiers.deterministic_verifier import DeterministicVerifier, get_verifier, VerificationResult
from src.sessions.manager import SessionManager, WizardState, get_session_manager

logger = structlog.get_logger()


# ============================================================================
# Wizard Steps
# ============================================================================
class WizardStep(int, Enum):
    """7 wizard steps"""
    FEATURE_SPEC = 1
    USER_STORY = 2
    FUNCTIONAL_ANALYSIS = 3
    FLOWCHART = 4
    PSEUDOCODE = 5
    TDD_TESTS = 6
    DOCUMENTATION = 7


# ============================================================================
# Step Configuration
# ============================================================================
@dataclass
class StepConfig:
    """Configuration for a wizard step"""
    step: WizardStep
    name: str
    node_type: str
    min_word_count: int
    required_headers: List[str]


STEP_CONFIGS = {
    WizardStep.FEATURE_SPEC: StepConfig(
        step=WizardStep.FEATURE_SPEC,
        name="Feature Specification",
        node_type="feature",
        min_word_count=200,
        required_headers=["## Overview", "## Problem", "## Solution"],
    ),
    WizardStep.USER_STORY: StepConfig(
        step=WizardStep.USER_STORY,
        name="User Story",
        node_type="user_story",
        min_word_count=100,
        required_headers=["## User Story", "## Acceptance Criteria"],
    ),
    WizardStep.FUNCTIONAL_ANALYSIS: StepConfig(
        step=WizardStep.FUNCTIONAL_ANALYSIS,
        name="Functional Analysis",
        node_type="functional_analysis",
        min_word_count=200,
        required_headers=["## Functional Requirements", "## Non-Functional Requirements"],
    ),
    WizardStep.FLOWCHART: StepConfig(
        step=WizardStep.FLOWCHART,
        name="Flowchart",
        node_type="flowchart",
        min_word_count=100,
        required_headers=["## Flow Description"],
    ),
    WizardStep.PSEUDOCODE: StepConfig(
        step=WizardStep.PSEUDOCODE,
        name="Pseudocode",
        node_type="pseudocode",
        min_word_count=150,
        required_headers=["## Algorithm"],
    ),
    WizardStep.TDD_TESTS: StepConfig(
        step=WizardStep.TDD_TESTS,
        name="TDD Tests",
        node_type="tdd_tests",
        min_word_count=200,
        required_headers=["## Test Cases", "## Test Strategy"],
    ),
    WizardStep.DOCUMENTATION: StepConfig(
        step=WizardStep.DOCUMENTATION,
        name="Documentation",
        node_type="documentation",
        min_word_count=300,
        required_headers=["## Overview", "## Usage"],
    ),
}


# ============================================================================
# Wizard Result Types
# ============================================================================
@dataclass
class StepResult:
    """Result of a wizard step"""
    step: WizardStep
    success: bool
    content: str
    verification: Optional[VerificationResult]
    node_id: Optional[str]
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step.value,
            "success": self.success,
            "content": self.content,
            "verification": self.verification.to_dict() if self.verification else None,
            "node_id": self.node_id,
            "error": self.error,
        }


@dataclass
class WizardCompletionResult:
    """Result of completing the entire wizard"""
    success: bool
    feature_node_id: str
    all_node_ids: List[str]
    verification_results: List[Dict[str, Any]]
    total_steps: int
    completed_steps: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "feature_node_id": self.feature_node_id,
            "all_node_ids": self.all_node_ids,
            "verification_results": self.verification_results,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
        }


# ============================================================================
# Wizard Pipeline
# ============================================================================
class WizardPipeline:
    """
    7-Step Wizard Pipeline
    
    Orchestrates feature documentation generation with:
    - Step-by-step generation via Ollama
    - Deterministic verification at each step
    - User edit capability
    - State persistence for resume
    - Graph construction
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
    
    async def start_wizard(
        self,
        project_id: str,
        feature_title: str,
        feature_description: str,
        user_id: Optional[str] = None,
    ) -> str:
        """
        Start a new wizard session
        
        Args:
            project_id: Project ID
            feature_title: Title of the feature
            feature_description: Description of the feature
            user_id: User ID (optional)
        
        Returns:
            Session ID
        """
        # Create session
        session_id = self.session_manager.create_session(
            project_id=project_id,
            session_type="wizard",
        )
        
        # Create initial feature node
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
        
        # Initialize wizard state
        wizard_state = WizardState(
            current_step=0,
            feature_id=feature_node_id,
            project_id=project_id,
            feature_title=feature_title,
            feature_description=feature_description,
        )
        
        # Save state
        self.session_manager.save_wizard_state(session_id, wizard_state)
        
        logger.info(
            "wizard_started",
            session_id=session_id,
            feature_id=feature_node_id,
            feature_title=feature_title,
        )
        
        return session_id
    
    async def execute_step(
        self,
        session_id: str,
        user_edit: Optional[str] = None,
        force: bool = False,
    ) -> StepResult:
        """
        Execute next wizard step

        Args:
            session_id: Session ID
            user_edit: Optional user edit for current step
            force: Accept and advance even if verification is below threshold.
                This ensures the wizard can never dead-end on a weak model.

        Returns:
            StepResult with content and verification
        """
        # Load wizard state
        wizard_state = self.session_manager.load_wizard_state(session_id)
        
        if not wizard_state:
            raise ValueError(f"Session not found: {session_id}")
        
        # Determine next step
        current_step = wizard_state.current_step
        next_step = WizardStep(current_step + 1)
        
        if next_step > WizardStep.DOCUMENTATION:
            raise ValueError("Wizard already completed")
        
        # Get step configuration
        config = STEP_CONFIGS[next_step]
        
        # Generate content for this step
        try:
            content = await self._generate_step_content(
                step=next_step,
                wizard_state=wizard_state,
            )
            
            # Apply user edit if provided
            if user_edit:
                content = user_edit
            
            # Verify content
            verification = await self.verifier.verify_section(
                section_id=f"{session_id}_step_{next_step.value}",
                content=content,
                node_type=config.node_type,
                context={
                    "terminology": {},
                    "all_sections": [],
                },
            )
            
            # Check if verification passed. If it failed and the caller didn't
            # force acceptance, return a failed result for the user to edit or
            # regenerate. With force=True we accept the draft and advance.
            if not verification.passed and not force:
                return StepResult(
                    step=next_step,
                    success=False,
                    content=content,
                    verification=verification,
                    node_id=None,
                    error=f"Verification failed: {verification.overall_score:.0f}/100 (need ≥85)",
                )

            node_status = "verified" if verification.passed else "draft"

            # Create node for this step
            with self.db.get_session() as session:
                node_id = str(uuid.uuid4())
                
                node = Node(
                    id=node_id,
                    project_id=wizard_state.project_id,
                    node_type=config.node_type,
                    title=f"{config.name} - Step {next_step.value}",
                    content=content,
                    status=node_status,
                    parent_id=wizard_state.feature_id,
                )

                session.add(node)

                # Create edge from feature to this node
                edge_id = str(uuid.uuid4())
                edge = Edge(
                    id=edge_id,
                    project_id=wizard_state.project_id,
                    source_node_id=wizard_state.feature_id,
                    target_node_id=node_id,
                    edge_type="generates",
                )
                
                session.add(edge)
                session.commit()
            
            # Update wizard state
            wizard_state.current_step = next_step.value
            self._store_step_content(wizard_state, next_step, content)
            wizard_state.verification_results[next_step.value] = verification.to_dict()
            self.session_manager.save_wizard_state(session_id, wizard_state)
            
            logger.info(
                "wizard_step_completed",
                session_id=session_id,
                step=next_step.value,
                node_id=node_id,
                verification_score=verification.overall_score,
            )
            
            return StepResult(
                step=next_step,
                success=True,
                content=content,
                verification=verification,
                node_id=node_id,
            )
        
        except Exception as e:
            logger.error(
                "wizard_step_failed",
                session_id=session_id,
                step=next_step.value,
                error=str(e),
            )
            
            return StepResult(
                step=next_step,
                success=False,
                content="",
                verification=None,
                node_id=None,
                error=str(e),
            )
    
    async def _generate_step_content(
        self,
        step: WizardStep,
        wizard_state: WizardState,
    ) -> str:
        """Generate content for a wizard step using Ollama"""
        if not self.ollama:
            raise RuntimeError("Ollama client not initialized. Call initialize() first.")
        
        # Generate based on step
        if step == WizardStep.FEATURE_SPEC:
            return await self.ollama.generate_feature_spec(
                product_name=wizard_state.feature_title or "Product",
                idea=wizard_state.feature_description or wizard_state.feature_title or "New feature",
                feature_title=wizard_state.feature_title or "Feature",
            )
        
        elif step == WizardStep.USER_STORY:
            return await self.ollama.generate_user_story(
                feature_spec=wizard_state.feature_spec,
            )
        
        elif step == WizardStep.FUNCTIONAL_ANALYSIS:
            return await self.ollama.generate_functional_analysis(
                user_story=wizard_state.user_story,
            )
        
        elif step == WizardStep.FLOWCHART:
            return await self.ollama.generate_flowchart(
                functional_analysis=wizard_state.functional_analysis,
            )
        
        elif step == WizardStep.PSEUDOCODE:
            return await self.ollama.generate_pseudocode(
                flowchart=wizard_state.flowchart,
            )
        
        elif step == WizardStep.TDD_TESTS:
            return await self.ollama.generate_tdd_tests(
                pseudocode=wizard_state.pseudocode,
            )
        
        elif step == WizardStep.DOCUMENTATION:
            return await self.ollama.generate_documentation(
                tdd_tests=wizard_state.tdd_tests,
            )
        
        raise ValueError(f"Unknown wizard step: {step}")
    
    def _store_step_content(
        self,
        wizard_state: WizardState,
        step: WizardStep,
        content: str,
    ):
        """Store generated content in wizard state"""
        if step == WizardStep.FEATURE_SPEC:
            wizard_state.feature_spec = content
        elif step == WizardStep.USER_STORY:
            wizard_state.user_story = content
        elif step == WizardStep.FUNCTIONAL_ANALYSIS:
            wizard_state.functional_analysis = content
        elif step == WizardStep.FLOWCHART:
            wizard_state.flowchart = content
        elif step == WizardStep.PSEUDOCODE:
            wizard_state.pseudocode = content
        elif step == WizardStep.TDD_TESTS:
            wizard_state.tdd_tests = content
        elif step == WizardStep.DOCUMENTATION:
            wizard_state.documentation = content
    
    async def complete_wizard(self, session_id: str) -> WizardCompletionResult:
        """
        Complete the wizard and return all generated nodes
        
        Args:
            session_id: Session ID
        
        Returns:
            WizardCompletionResult with all node IDs
        """
        # Load wizard state
        wizard_state = self.session_manager.load_wizard_state(session_id)
        
        if not wizard_state:
            raise ValueError(f"Session not found: {session_id}")
        
        if wizard_state.current_step < WizardStep.DOCUMENTATION.value:
            raise ValueError("Wizard not completed. Execute remaining steps first.")
        
        # Collect all node IDs
        all_node_ids = [wizard_state.feature_id]
        
        # Get all nodes created during wizard
        with self.db.get_session() as session:
            nodes = (
                session.query(Node)
                .filter(Node.parent_id == wizard_state.feature_id)
                .all()
            )
            
            all_node_ids.extend([n.id for n in nodes])
        
        # Collect verification results (from session state)
        verification_results = list(wizard_state.verification_results.values())
        
        logger.info(
            "wizard_completed",
            session_id=session_id,
            total_nodes=len(all_node_ids),
        )
        
        return WizardCompletionResult(
            success=True,
            feature_node_id=wizard_state.feature_id,
            all_node_ids=all_node_ids,
            verification_results=verification_results,
            total_steps=7,
            completed_steps=7,
        )
    
    async def resume_wizard(self, session_id: str) -> WizardState:
        """
        Resume a wizard session
        
        Args:
            session_id: Session ID
        
        Returns:
            WizardState with current progress
        """
        wizard_state = self.session_manager.load_wizard_state(session_id)
        
        if not wizard_state:
            raise ValueError(f"Session not found: {session_id}")
        
        logger.info(
            "wizard_resumed",
            session_id=session_id,
            current_step=wizard_state.current_step,
        )
        
        return wizard_state


# ============================================================================
# Factory Function
# ============================================================================
async def get_wizard_pipeline(db: DatabaseManager) -> WizardPipeline:
    """Get wizard pipeline instance"""
    pipeline = WizardPipeline(db)
    await pipeline.initialize()
    return pipeline

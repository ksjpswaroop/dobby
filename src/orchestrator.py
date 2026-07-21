"""
Document Orchestrator - Coordinates all agents

Manages parallel execution, state persistence, and verification.
"""

import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import structlog
import uuid

from src.state_machine import Job, StateMachine, State, Trigger
from src.agents.base import BaseAgent
from src.agents.prd_agent import PRDAgent
from src.agents.architecture_agent import ArchitectureAgent
from src.agents.demand_agent import DemandAnalysisAgent
from src.agents.market_agent import MarketResearchAgent
from src.agents.feature_agent import FeatureResearchAgent
from src.agents.pareto_agent import ParetoAnalysisAgent

logger = structlog.get_logger()


class DocumentOrchestrator:
    """Orchestrates multi-agent document generation"""
    
    def __init__(self, state_dir: Optional[Path] = None):
        self.state_dir = state_dir or Path.home() / ".dobby" / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.jobs: Dict[str, StateMachine] = {}
        logger.info("orchestrator_initialized", state_dir=str(self.state_dir))
    
    async def create_job(
        self,
        idea: str,
        output_path: Optional[str] = None,
        template_override: Optional[Dict[str, str]] = None,
        ollama_model: str = "llama3.2",
        parallel: bool = True,
    ) -> str:
        """Create a new document generation job"""
        job_id = str(uuid.uuid4())
        output_dir = Path(output_path) if output_path else Path.home() / "dobby-output" / job_id
        
        job = Job(
            job_id=job_id,
            idea=idea,
            output_path=output_dir,
            max_retries=3,
        )
        
        sm = StateMachine(job)
        sm.trigger(Trigger.JOB_CREATED, idea_length=len(idea))
        self.jobs[job_id] = sm
        
        # Persist state
        sm.persist(self.state_dir / f"{job_id}.json")
        
        # Start background execution
        asyncio.create_task(self._execute_job(job_id, parallel, ollama_model))
        
        logger.info("job_created", job_id=job_id, output_path=str(output_dir))
        return job_id
    
    async def _execute_job(self, job_id: str, parallel: bool, ollama_model: str):
        """Execute document generation job"""
        sm = self.jobs.get(job_id)
        if not sm:
            logger.error("job_not_found", job_id=job_id)
            return
        
        try:
            sm.trigger(Trigger.DEPENDENCIES_MET)
            sm.persist(self.state_dir / f"{job_id}.json")
            
            # Build agent pool
            agents = self._build_agent_pool(sm.job.idea, sm.job.output_path, ollama_model)
            
            if parallel:
                # Execute in parallel groups
                await self._execute_parallel(agents, sm)
            else:
                # Execute sequentially
                await self._execute_sequential(agents, sm)
            
            # Run verification
            await self._run_verification(sm)
            
            sm.trigger(Trigger.VERIFICATION_COMPLETE)
            sm.persist(self.state_dir / f"{job_id}.json")
            
            logger.info("job_completed", job_id=job_id)
        
        except Exception as e:
            logger.error("job_failed", job_id=job_id, error=str(e), exc_info=True)
            try:
                sm.trigger(Trigger.AGENT_FAILED, error=str(e))
            except:
                sm.job.current_state = State.FAILED
            sm.persist(self.state_dir / f"{job_id}.json")
    
    def _build_agent_pool(self, idea: str, output_path: Path, model: str) -> List[BaseAgent]:
        """Build pool of agents for document generation"""
        return [
            DemandAnalysisAgent(idea=idea, output_path=output_path, model=model),
            MarketResearchAgent(idea=idea, output_path=output_path, model=model),
            FeatureResearchAgent(idea=idea, output_path=output_path, model=model),
            ParetoAnalysisAgent(idea=idea, output_path=output_path, model=model),
            PRDAgent(idea=idea, output_path=output_path, model=model),
            ArchitectureAgent(idea=idea, output_path=output_path, model=model),
            # Add remaining agents...
        ]
    
    async def _execute_parallel(self, agents: List[BaseAgent], sm: StateMachine):
        """Execute agents in parallel with semaphore"""
        semaphore = asyncio.Semaphore(5)  # Limit to 5 concurrent agents
        
        async def execute_with_semaphore(agent: BaseAgent):
            async with semaphore:
                sm.job.current_agent = agent.__class__.__name__
                sm.persist(self.state_dir / f"{sm.job.job_id}.json")
                
                try:
                    result = await agent.execute()
                    sm.job.completed_documents.append(result.output_file.name)
                    sm.job.progress_percent = (
                        len(sm.job.completed_documents) / len(agents) * 100
                    )
                    logger.info(
                        "agent_complete",
                        job_id=sm.job.job_id,
                        agent=agent.__class__.__name__,
                        output=str(result.output_file),
                    )
                except Exception as e:
                    sm.job.failed_documents.append(agent.__class__.__name__)
                    logger.error(
                        "agent_failed",
                        job_id=sm.job.job_id,
                        agent=agent.__class__.__name__,
                        error=str(e),
                    )
                    raise
        
        # Execute all agents in parallel
        tasks = [execute_with_semaphore(agent) for agent in agents]
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _execute_sequential(self, agents: List[BaseAgent], sm: StateMachine):
        """Execute agents sequentially"""
        for agent in agents:
            sm.job.current_agent = agent.__class__.__name__
            sm.persist(self.state_dir / f"{sm.job.job_id}.json")
            
            result = await agent.execute()
            sm.job.completed_documents.append(result.output_file.name)
            sm.job.progress_percent = (
                len(sm.job.completed_documents) / len(agents) * 100
            )
    
    async def _run_verification(self, sm: StateMachine):
        """Run verification on all generated documents"""
        logger.info("verification_started", job_id=sm.job.job_id)
        # TODO: Implement verification logic
        sm.job.verification_score = 95.0  # Placeholder
    
    async def get_job(self, job_id: str) -> Optional[Job]:
        """Get job by ID"""
        sm = self.jobs.get(job_id)
        if not sm:
            # Try to load from disk
            state_file = self.state_dir / f"{job_id}.json"
            if state_file.exists():
                sm = StateMachine.load(state_file)
                self.jobs[job_id] = sm
        return sm.job if sm else None
    
    async def verify_job(self, job_id: str) -> Any:
        """Run verification on a completed job"""
        sm = self.jobs.get(job_id)
        if not sm:
            raise ValueError(f"Job {job_id} not found")
        
        await self._run_verification(sm)
        return type("VerificationResult", (), {
            "score": sm.job.verification_score,
            "checks": [],
            "recommendations": [],
        })()

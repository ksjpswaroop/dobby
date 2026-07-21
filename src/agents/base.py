"""
Base Agent - Abstract base class for all document generation agents
"""

from abc import ABC, abstractmethod
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from datetime import datetime
import structlog

logger = structlog.get_logger()


@dataclass
class AgentOutput:
    """Output from agent execution"""
    success: bool
    output_file: Path
    content: str
    metadata: Dict[str, Any]
    error: Optional[str] = None


@dataclass
class AgentContext:
    """Context passed to agents"""
    idea: str
    job_id: str
    output_path: Path
    model: str = "llama3.2"
    template_override: Optional[Dict[str, str]] = None
    previous_outputs: Optional[Dict[str, AgentOutput]] = None


class BaseAgent(ABC):
    """Abstract base class for document generation agents"""
    
    def __init__(
        self,
        idea: str,
        output_path: Path,
        model: str = "llama3.2",
        template_override: Optional[Dict[str, str]] = None,
    ):
        self.idea = idea
        self.output_path = output_path
        self.model = model
        self.template_override = template_override
        self.logger = structlog.get_logger(agent_type=self.__class__.__name__)
    
    @property
    @abstractmethod
    def document_name(self) -> str:
        """Name of the document this agent generates"""
        pass
    
    @property
    @abstractmethod
    def template_file(self) -> str:
        """Template file name for this document"""
        pass
    
    @abstractmethod
    async def execute(self, context: AgentContext) -> AgentOutput:
        """
        Execute agent logic and generate document
        
        Args:
            context: AgentContext with idea, job_id, and previous outputs
        
        Returns:
            AgentOutput with generated content
        
        Raises:
            AgentExecutionError: If agent fails during execution
        """
        pass
    
    async def _load_template(self) -> str:
        """Load template file"""
        template_path = Path(__file__).parent.parent.parent / "templates" / self.template_file
        if not template_path.exists():
            raise FileNotFoundError(f"Template not found: {template_path}")
        
        with open(template_path, "r") as f:
            return f.read()
    
    async def _save_document(self, content: str) -> Path:
        """Save generated document to file system"""
        self.output_path.mkdir(parents=True, exist_ok=True)
        output_file = self.output_path / self.document_name
        
        with open(output_file, "w") as f:
            f.write(content)
        
        self.logger.info("document_saved", path=str(output_file))
        return output_file
    
    async def _call_llm(self, prompt: str) -> str:
        """Call LLM (Ollama) for generation"""
        try:
            from ollama import chat
            
            response = await asyncio.to_thread(
                chat,
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
            )
            
            return response["message"]["content"]
        
        except Exception as e:
            self.logger.error("llm_call_failed", error=str(e))
            raise AgentExecutionError(f"LLM call failed: {e}")


class AgentExecutionError(Exception):
    """Raised when agent execution fails"""
    pass

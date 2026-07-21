"""
State Machine for document generation jobs

Manages job lifecycle: idle → queued → running → done/failed
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from datetime import datetime
import json
import uuid
from pathlib import Path
import structlog

logger = structlog.get_logger()


class State(str, Enum):
    """Job states"""
    IDLE = "idle"
    QUEUED = "queued"
    RUNNING = "running"
    RETRIED = "retried"
    DONE = "done"
    FAILED = "failed"


class Trigger(str, Enum):
    """State machine triggers"""
    JOB_CREATED = "job_created"
    DEPENDENCIES_MET = "dependencies_met"
    AGENT_COMPLETE = "agent_complete"
    AGENT_FAILED = "agent_failed"
    BACKOFF_COMPLETE = "backoff_complete"
    VERIFICATION_COMPLETE = "verification_complete"


@dataclass
class Transition:
    """State transition record"""
    from_state: State
    to_state: State
    trigger: Trigger
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Job:
    """Document generation job"""
    job_id: str
    idea: str
    output_path: Path
    current_state: State = State.IDLE
    retry_count: int = 0
    max_retries: int = 3
    current_agent: Optional[str] = None
    progress_percent: float = 0.0
    completed_documents: List[str] = field(default_factory=list)
    failed_documents: List[str] = field(default_factory=list)
    transition_history: List[Transition] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    verification_score: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize job to dictionary"""
        return {
            "job_id": self.job_id,
            "idea": self.idea,
            "output_path": str(self.output_path),
            "current_state": self.current_state.value,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "current_agent": self.current_agent,
            "progress_percent": self.progress_percent,
            "completed_documents": self.completed_documents,
            "failed_documents": self.failed_documents,
            "transition_history": [
                {
                    "from_state": t.from_state.value,
                    "to_state": t.to_state.value,
                    "trigger": t.trigger.value,
                    "timestamp": t.timestamp.isoformat(),
                    "metadata": t.metadata,
                }
                for t in self.transition_history
            ],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "verification_score": self.verification_score,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Job":
        """Deserialize job from dictionary"""
        return cls(
            job_id=data["job_id"],
            idea=data["idea"],
            output_path=Path(data["output_path"]),
            current_state=State(data["current_state"]),
            retry_count=data["retry_count"],
            max_retries=data["max_retries"],
            current_agent=data.get("current_agent"),
            progress_percent=data.get("progress_percent", 0.0),
            completed_documents=data.get("completed_documents", []),
            failed_documents=data.get("failed_documents", []),
            transition_history=[
                Transition(
                    from_state=State(t["from_state"]),
                    to_state=State(t["to_state"]),
                    trigger=Trigger(t["trigger"]),
                    timestamp=datetime.fromisoformat(t["timestamp"]),
                    metadata=t["metadata"],
                )
                for t in data["transition_history"]
            ],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            verification_score=data.get("verification_score"),
        )


class StateMachine:
    """State machine for job lifecycle management"""
    
    # State transition table
    TRANSITIONS = {
        (State.IDLE, Trigger.JOB_CREATED): State.QUEUED,
        (State.QUEUED, Trigger.DEPENDENCIES_MET): State.RUNNING,
        (State.RUNNING, Trigger.AGENT_COMPLETE): State.DONE,
        (State.RUNNING, Trigger.AGENT_FAILED): State.RETRIED,
        (State.RETRIED, Trigger.BACKOFF_COMPLETE): State.RUNNING,
        (State.RETRIED, Trigger.AGENT_FAILED): State.FAILED,
        (State.DONE, Trigger.VERIFICATION_COMPLETE): State.DONE,
    }
    
    def __init__(self, job: Job):
        self.job = job
        logger.debug("state_machine_initialized", job_id=job.job_id)
    
    def trigger(self, trigger_event: Trigger, **metadata: Any) -> bool:
        """
        Trigger a state transition
        
        Args:
            trigger_event: The trigger to apply
            **metadata: Additional metadata for the transition
        
        Returns:
            True if transition succeeded, False otherwise
        
        Raises:
            InvalidTransitionError: If transition is not allowed
        """
        current = self.job.current_state
        key = (current, trigger_event)
        
        if key not in self.TRANSITIONS:
            error_msg = f"Invalid transition: {current.value} + {trigger_event.value}"
            logger.warning("invalid_transition", current_state=current.value, trigger=trigger_event.value)
            raise InvalidTransitionError(error_msg)
        
        next_state = self.TRANSITIONS[key]
        
        # Record transition
        transition = Transition(
            from_state=current,
            to_state=next_state,
            trigger=trigger_event,
            metadata=metadata,
        )
        self.job.transition_history.append(transition)
        
        # Update state
        self.job.current_state = next_state
        self.job.updated_at = datetime.utcnow()
        
        # Update retry count if failed
        if trigger_event == Trigger.AGENT_FAILED:
            self.job.retry_count += 1
            
            if self.job.retry_count >= self.job.max_retries:
                self.job.current_state = State.FAILED
                logger.warning(
                    "max_retries_exceeded",
                    job_id=self.job.job_id,
                    retry_count=self.job.retry_count,
                )
        
        logger.info(
            "state_transition",
            job_id=self.job.job_id,
            from_state=current.value,
            to_state=next_state.value,
            trigger=trigger_event.value,
            retry_count=self.job.retry_count,
        )
        
        return True
    
    def can_trigger(self, trigger_event: Trigger) -> bool:
        """Check if a trigger can be applied"""
        key = (self.job.current_state, trigger_event)
        return key in self.TRANSITIONS
    
    def persist(self, path: Path):
        """Persist job state to disk"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.job.to_dict(), f, indent=2)
        logger.debug("state_persisted", job_id=self.job.job_id, path=str(path))
    
    @classmethod
    def load(cls, path: Path) -> "StateMachine":
        """Load job state from disk"""
        with open(path, "r") as f:
            data = json.load(f)
        job = Job.from_dict(data)
        return cls(job)


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted"""
    pass

"""
Ollama Client for Dobby v2.0

Async HTTP client for local Ollama LLM integration.

Features:
- Connect to local Ollama instance (localhost:11434)
- Generate content for all 7 wizard steps
- Timeout and retry handling
- Connection health checks
- Streaming support (optional)
"""

import httpx
import asyncio
import structlog
from typing import Dict, Any, Optional, AsyncGenerator, List
from datetime import datetime
from pathlib import Path
import json

logger = structlog.get_logger()


# ============================================================================
# Ollama Configuration
# ============================================================================
class OllamaConfig:
    """Ollama configuration"""
    
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2",
        timeout: int = 120,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ):
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay


# ============================================================================
# Generation Prompts
# ============================================================================
class GenerationPrompts:
    """
    Prompts for each of the 7 wizard steps
    
    Each prompt is a template that gets filled with context.
    """
    
    FEATURE_SPEC = """
You are a product expert. Generate a comprehensive feature specification.

Context:
- Product: {product_name}
- Idea: {idea}
- Feature Title: {feature_title}

Generate a feature specification with:
## Overview
Describe the feature and its purpose.

## Problem
What problem does this feature solve?

## Solution
How does this feature solve the problem?

## User Impact
Who benefits from this feature and how?

## Technical Considerations
Any technical constraints or considerations.

Keep it concise but comprehensive (200-400 words).
"""
    
    USER_STORY = """
You are an Agile coach. Generate a user story from the feature specification.

Feature Specification:
{feature_spec}

Generate a user story with:
## User Story
As a [type of user], I want [goal] so that [benefit].

## Acceptance Criteria
- Given [context], When [action], Then [outcome]
- (Provide 3-5 acceptance criteria)

## Definition of Done
- [ ] Code complete
- [ ] Tests written
- [ ] Documentation updated

Keep it focused and testable.
"""
    
    FUNCTIONAL_ANALYSIS = """
You are a systems analyst. Generate functional analysis from the user story.

User Story:
{user_story}

Generate functional analysis with:
## Functional Requirements
- FR1: [Requirement]
- FR2: [Requirement]
- (Provide 5-10 functional requirements)

## Non-Functional Requirements
- Performance: [Requirements]
- Security: [Requirements]
- Scalability: [Requirements]

## Data Requirements
- Input: [Data inputs]
- Output: [Data outputs]
- Storage: [Data storage needs]

Be specific and measurable.
"""
    
    FLOWCHART = """
You are a technical writer. Generate a flowchart description from the functional analysis.

Functional Analysis:
{functional_analysis}

Generate a flowchart description with:
## Flow Description
Describe the step-by-step flow of the feature.

## Mermaid Diagram
```mermaid
graph TD
    A[Start] --> B[Step 1]
    B --> C[Step 2]
    C --> D[End]
```

## Decision Points
- Decision 1: [Condition] → [Yes/No paths]
- Decision 2: [Condition] → [Yes/No paths]

Make the flow clear and easy to follow.
"""
    
    PSEUDOCODE = """
You are a senior software engineer. Generate pseudocode from the flowchart.

Flowchart:
{flowchart}

Generate pseudocode with:
## Algorithm
```
FUNCTION feature_name(input)
    // Step 1: Validate input
    IF input is invalid THEN
        RETURN error
    END IF
    
    // Step 2: Process
    FOR each item IN input DO
        // Process item
    END FOR
    
    // Step 3: Return result
    RETURN result
END FUNCTION
```

## Complexity Analysis
- Time Complexity: O(n)
- Space Complexity: O(1)

## Edge Cases
- Handle null/empty input
- Handle large datasets
- Handle concurrent access

Write clear, readable pseudocode.
IMPORTANT: Your response MUST include the "## Algorithm" section header exactly as written above.
"""

    TDD_TESTS = """
You are a QA engineer. Generate TDD test cases from the pseudocode.

Pseudocode:
{pseudocode}

Generate TDD tests with:
## Test Strategy
- Unit tests: [What to test]
- Integration tests: [What to test]
- Edge cases: [What to test]

## Test Cases
### Test Case 1: [Name]
- Given: [Context]
- When: [Action]
- Then: [Expected outcome]

### Test Case 2: [Name]
- Given: [Context]
- When: [Action]
- Then: [Expected outcome]

(Provide 5-10 test cases)

## Mock Data
- Input: [Sample input]
- Expected Output: [Sample output]

Make tests comprehensive and independent.
IMPORTANT: Your response MUST include both the "## Test Strategy" and "## Test Cases" section headers exactly as written above.
"""
    
    DOCUMENTATION = """
You are a technical writer. Generate documentation from the TDD tests.

TDD Tests:
{tdd_tests}

Generate documentation with:
## Overview
What does this feature do? (2-3 sentences)

## Usage
How do users interact with this feature?

## API Reference
- Endpoint: [URL]
- Method: [GET/POST/etc.]
- Request: [Request format]
- Response: [Response format]

## Examples
```python
# Example usage
result = feature.function(input)
```

## Troubleshooting
- Issue: [Common issue]
  - Solution: [How to fix]

Write clear, user-friendly documentation.
IMPORTANT: Your response MUST begin with the "## Overview" and "## Usage" section headers exactly as written above, before any other sections.
"""


# ============================================================================
# Ollama Client
# ============================================================================
class OllamaClient:
    """
    Async HTTP client for Ollama
    
    Provides:
    - Generate text (sync and streaming)
    - Health checks
    - Model listing
    - Retry logic with exponential backoff
    """
    
    def __init__(self, config: Optional[OllamaConfig] = None):
        self.config = config or OllamaConfig()
        self.client = httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=self.config.timeout,
        )
        self.prompts = GenerationPrompts()
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()
    
    async def health_check(self) -> bool:
        """
        Check if Ollama is running and healthy
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            response = await self.client.get("/api/tags")
            return response.status_code == 200
        except Exception as e:
            logger.warning("ollama_health_check_failed", error=str(e))
            return False
    
    async def list_models(self) -> List[str]:
        """
        List available models
        
        Returns:
            List of model names
        """
        try:
            response = await self.client.get("/api/tags")
            response.raise_for_status()
            data = response.json()
            return [model["name"] for model in data.get("models", [])]
        except Exception as e:
            logger.error("ollama_list_models_failed", error=str(e))
            return []
    
    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 2000,
        temperature: float = 0.7,
        **kwargs,
    ) -> str:
        """
        Generate text from a prompt
        
        Args:
            prompt: The prompt to send
            model: Model to use (default: config.model)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0.0-1.0)
            **kwargs: Additional parameters
        
        Returns:
            Generated text
        
        Raises:
            OllamaError: If generation fails
        """
        model = model or self.config.model
        
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }

        # Ollama's structured-output mode: format="json" constrains decoding to
        # valid JSON, which materially improves schema compliance on small
        # local models. Opt-in so plain prose generation is unaffected.
        if kwargs.get("format"):
            payload["format"] = kwargs["format"]
        
        # Retry logic with exponential backoff
        last_error = None
        for attempt in range(self.config.max_retries):
            try:
                response = await self.client.post(
                    "/api/generate",
                    json=payload,
                )
                response.raise_for_status()
                
                data = response.json()
                generated_text = data.get("response", "")
                
                logger.info(
                    "ollama_generation_success",
                    model=model,
                    tokens=data.get("eval_count", 0),
                    attempt=attempt + 1,
                )
                
                return generated_text
            
            except httpx.HTTPError as e:
                last_error = e
                logger.warning(
                    "ollama_generation_failed",
                    attempt=attempt + 1,
                    error=str(e),
                )
                
                if attempt < self.config.max_retries - 1:
                    delay = self.config.retry_delay * (2 ** attempt)
                    await asyncio.sleep(delay)
        
        # All retries failed
        raise OllamaError(
            f"Generation failed after {self.config.max_retries} attempts: {last_error}"
        )
    
    async def generate_stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 2000,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """
        Generate text with streaming
        
        Args:
            prompt: The prompt to send
            model: Model to use
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
        
        Yields:
            Chunks of generated text
        """
        model = model or self.config.model
        
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        
        async with self.client.stream(
            "POST",
            "/api/generate",
            json=payload,
        ) as response:
            response.raise_for_status()
            
            async for line in response.aiter_lines():
                if not line:
                    continue
                
                try:
                    data = json.loads(line)
                    chunk = data.get("response", "")
                    
                    if chunk:
                        yield chunk
                    
                    if data.get("done", False):
                        break
                
                except json.JSONDecodeError:
                    continue
    
    # ========================================================================
    # Wizard Step Generation Methods
    # ========================================================================
    
    async def generate_feature_spec(
        self,
        product_name: str,
        idea: str,
        feature_title: str,
    ) -> str:
        """Generate feature specification"""
        prompt = self.prompts.FEATURE_SPEC.format(
            product_name=product_name,
            idea=idea,
            feature_title=feature_title,
        )
        return await self.generate(prompt)
    
    async def generate_user_story(self, feature_spec: str) -> str:
        """Generate user story from feature spec"""
        prompt = self.prompts.USER_STORY.format(feature_spec=feature_spec)
        return await self.generate(prompt)
    
    async def generate_functional_analysis(self, user_story: str) -> str:
        """Generate functional analysis from user story"""
        prompt = self.prompts.FUNCTIONAL_ANALYSIS.format(user_story=user_story)
        return await self.generate(prompt)
    
    async def generate_flowchart(self, functional_analysis: str) -> str:
        """Generate flowchart from functional analysis"""
        prompt = self.prompts.FLOWCHART.format(functional_analysis=functional_analysis)
        return await self.generate(prompt)
    
    async def generate_pseudocode(self, flowchart: str) -> str:
        """Generate pseudocode from flowchart"""
        prompt = self.prompts.PSEUDOCODE.format(flowchart=flowchart)
        return await self.generate(prompt)
    
    async def generate_tdd_tests(self, pseudocode: str) -> str:
        """Generate TDD tests from pseudocode"""
        prompt = self.prompts.TDD_TESTS.format(pseudocode=pseudocode)
        return await self.generate(prompt)
    
    async def generate_documentation(self, tdd_tests: str) -> str:
        """Generate documentation from TDD tests"""
        prompt = self.prompts.DOCUMENTATION.format(tdd_tests=tdd_tests)
        return await self.generate(prompt)


# ============================================================================
# Custom Exceptions
# ============================================================================
class OllamaError(Exception):
    """Base exception for Ollama errors"""
    pass


class OllamaConnectionError(OllamaError):
    """Ollama is not running or unreachable"""
    pass


class OllamaGenerationError(OllamaError):
    """Generation failed"""
    pass


# ============================================================================
# Factory Function
# ============================================================================
async def get_ollama_client(
    base_url: str = "http://localhost:11434",
    model: str = "llama3.2",
) -> OllamaClient:
    """
    Get Ollama client instance
    
    Args:
        base_url: Ollama base URL
        model: Default model to use
    
    Returns:
        OllamaClient instance
    
    Raises:
        OllamaConnectionError: If Ollama is not running
    """
    config = OllamaConfig(base_url=base_url, model=model)
    client = OllamaClient(config)
    
    # Check health
    is_healthy = await client.health_check()
    
    if not is_healthy:
        await client.close()
        raise OllamaConnectionError(
            f"Ollama is not running at {base_url}. "
            "Start it with: ollama serve"
        )
    
    return client

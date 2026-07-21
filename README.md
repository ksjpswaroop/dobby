# Dobby 🧝

**Autonomous Multi-Agent Document Generation Platform**

Generate 29 comprehensive product documents from a single idea in under 5 minutes.

```bash
dobby generate --idea "AI-powered meeting notes app"
```

## Quickstart

```bash
# Install
pip install -e .

# Generate all 29 documents
dobby generate --idea "Your product idea here"

# Check status
dobby status <job_id>

# View generated docs
ls ~/dobby-output/<job_id>/
```

## Features

- **29 Documents:** PRD, Architecture, Security, Backlog, Jira export, and 24 more
- **13 Specialized Agents:** Each agent is an expert in one document type
- **Parallel Execution:** 5 concurrent agents with semaphore limiting
- **State Machine:** Full state persistence with retry logic
- **Local LLM:** Runs on Ollama (zero API costs, privacy-preserving)
- **Verification:** Automated cross-reference scoring (95%+ target)
- **FastAPI Backend:** REST API + CLI + future Tauri desktop app

## Documentation Generated

| Phase | Documents |
|-------|-----------|
| **Market & Demand** | DEMAND_ANALYSIS, MARKET_RESEARCH, FEATURE_RESEARCH, PARETO_ANALYSIS |
| **Requirements** | PRD (39 sections), MERMAID_DIAGRAMS, ARCHITECTURE_DIAGRAMS, FLOW_CHARTS |
| **Architecture** | ARCHITECTURE, SECURITY_ANALYSIS, DATA_MODEL |
| **Planning** | IMPLEMENTATION_PLAN, MULTI_PARALLEL_EXECUTION, BACKLOG, JIRA_BACKLOG, WBS, ROADMAP |
| **Design** | DESIGN_SYSTEM, WIREFRAMES, CODE_STANDARDS |
| **Testing** | TDD_SPEC, TEST_PLAN, VERIFICATION_PLAN |
| **Deployment** | DEPLOYMENT, RUNBOOK |
| **Scaffold** | README, pyproject.toml, LICENSE, src/, tests/ |

## Architecture

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│   CLI / API  │─────▶│  Orchestrator │─────▶│ State Machine │
└──────────────┘      └──────────────┘      └──────┬───────┘
                                                   │
                    ┌──────────────────────────────┼────────┐
                    │         Agent Pool           │        │
                    │  ┌──────┐ ┌──────┐ ┌──────┐  │        │
                    │  │ PRD  │ │Arch  │ │Back-│  │        │
                    │  │Agent │ │Agent │ │ log  │  │        │
                    │  └──────┘ └──────┘ └──────┘  │        │
                    └──────────────────────────────┼────────┘
                                                   │
                                                   ▼
                                          ┌──────────────┐
                                          │   File       │
                                          │   System     │
                                          └──────────────┘
```

## Installation

```bash
# Clone repo
git clone https://github.com/ksjpswaroop/dobby.git
cd dobby

# Create venv
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install
pip install -e ".[dev]"

# Install Ollama (macOS)
brew install ollama
ollama serve

# Pull model
ollama pull llama3.2
```

## Usage

### CLI

```bash
# Generate documents
dobby generate --idea "AI-powered meeting notes app"

# With custom output path
dobby generate --idea "..." --output-path ./my-docs

# With custom model
dobby generate --idea "..." --ollama-model mistral

# Check job status
dobby status <job_id>

# Verify documents
dobby verify <job_id>
```

### REST API

```bash
# Start server
uvicorn src.main:app --reload

# Generate documents
curl -X POST http://localhost:8000/api/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"idea": "AI-powered meeting notes app"}'

# Check status
curl http://localhost:8000/api/v1/jobs/<job_id>
```

### Python SDK

```python
from dobby import DocumentOrchestrator

orchestrator = DocumentOrchestrator()
job_id = await orchestrator.create_job(
    idea="AI-powered meeting notes app",
    parallel=True,
)
```

## Configuration

Create `.env` file:

```bash
# Ollama model
OLLAMA_MODEL=llama3.2

# Output directory
OUTPUT_PATH=~/dobby-output

# Concurrency limit
MAX_CONCURRENT_AGENTS=5

# Log level
LOG_LEVEL=INFO
```

## Testing

```bash
# Run tests
pytest

# With coverage
pytest --cov=src --cov-report=html

# Run specific test
pytest tests/test_state_machine.py -v
```

## Development

```bash
# Lint
ruff check src/

# Type check
mypy src/

# Format
black src/
```

## Project Structure

```
dobby/
├── src/
│   ├── __init__.py
│   ├── main.py              # FastAPI app
│   ├── orchestrator.py      # Multi-agent coordinator
│   ├── state_machine.py     # Job lifecycle
│   ├── api/
│   │   └── routes.py        # REST endpoints
│   ├── agents/
│   │   ├── base.py          # Base agent
│   │   ├── prd_agent.py     # PRD generator
│   │   └── ...              # 12 more agents
│   └── utils/
│       └── logging.py       # Structured logging
├── templates/               # 29 document templates
├── prompts/                 # 13 agent prompts
├── tests/                   # Test suite
├── docs/                    # Documentation
├── pyproject.toml
└── README.md
```

## Roadmap

### v1.0 (Current)
- ✅ 29 document templates
- ✅ 13 specialized agents
- ✅ FastAPI backend
- ✅ State machine with retry
- ✅ Parallel execution
- ⏳ Ollama integration
- ⏳ Verification scoring

### v1.1 (Q4 2026)
- [ ] Tauri desktop app
- [ ] Custom template editor
- [ ] Progress UI

### v1.5 (Q1 2027)
- [ ] Cloud deployment
- [ ] Multi-user support
- [ ] Team collaboration

### v2.0 (Q2 2027)
- [ ] Jira/Linear/Notion integration
- [ ] Template marketplace
- [ ] Cloud sync

## Contributing

1. Fork the repo
2. Create feature branch: `git checkout -b feat/my-feature`
3. Commit changes: `git commit -m 'feat: add my feature'`
4. Push: `git push origin feat/my-feature`
5. Open PR

## License

MIT License - see [LICENSE](LICENSE)

## Author

Swaroop <ksjpswaroop@gmail.com>

---

**Dobby is a free elf who serves his master. No API costs, no privacy concerns, just comprehensive documentation.**

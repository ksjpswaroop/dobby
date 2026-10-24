# Dobby v2.0 - Architecture Decisions

## ✅ Approved Architecture Decisions

### 1. Graph-Based, Stateful Design
**Decision:** YES - Full graph-based architecture with stateful sessions

**Rationale:**
- Enables traceability from idea → feature → story → tests → docs
- Supports 1000+ features over 1000 days
- Allows resume anytime (close app, reopen weeks later)
- Full audit trail of every change

**Implementation:**
- Nodes: Idea, Feature, UserStory, FunctionalAnalysis, Flowchart, Pseudocode, TDDTests, Documentation
- Edges: generates, refines, implements, tests, documents
- SQLite database for persistence
- Session state persisted to disk

---

### 2. UI Framework
**Decision:** Python/FastAPI + Ollama + Rust/Tauri

**Stack:**
```
┌─────────────────────────────────────────────────────────────┐
│                    Tauri Desktop App                         │
│                    (Rust + Web Frontend)                     │
│                                                              │
│  Frontend: React/Vue + TypeScript                            │
│  - Dashboard with graph visualization                        │
│  - Feature wizard UI                                         │
│  - Section editor with versioning                            │
│  - Document viewer/export                                    │
│                                                              │
│  Backend: FastAPI (Python)                                   │
│  - REST API for all operations                               │
│  - Graph management (nodes, edges)                           │
│  - Wizard pipeline orchestration                             │
│  - Deterministic verification                                │
│  - Document generation/aggregation                           │
│                                                              │
│  AI: Ollama (Local LLM)                                      │
│  - llama3.2 or mistral for generation                        │
│  - No API costs, privacy-preserving                          │
│  - Runs locally on user's machine                            │
│                                                              │
│  Database: SQLite                                            │
│  - Local-first storage                                       │
│  - No server setup required                                  │
│  - Single file database (~/.dobby/dobby.db)                  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Rationale:**
- **Tauri:** Native desktop app, small bundle size, Rust security
- **FastAPI:** Python ecosystem, async support, easy Ollama integration
- **Ollama:** Local LLM, no API costs, privacy
- **SQLite:** Zero-config, local-first, single file

---

### 3. Feature Prioritization
**Decision:** Pareto analysis at every step, build as we progress

**Approach:**
```
┌─────────────────────────────────────────────────────────────┐
│              PARETO-DRIVEN FEATURE PRIORITIZATION            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Before each feature:                                        │
│  1. List all candidate features (backlog)                   │
│  2. Score each feature:                                     │
│     - Impact (1-10): How much value does this add?          │
│     - Effort (1-10): How hard is this to build?             │
│     - Risk (1-10): How uncertain is this?                   │
│  3. Calculate Pareto Score:                                 │
│     pareto_score = (Impact * 0.6) - (Effort * 0.3) - (Risk * 0.1)  │
│  4. Sort by Pareto Score (descending)                       │
│  5. Pick top feature for today                              │
│  6. After completion, re-score remaining features           │
│                                                              │
│  Benefits:                                                   │
│  - Always working on highest-value feature                  │
│  - Adapts to learning (scores update as we build)           │
│  - 80% value from 20% features                              │
│  - No wasted effort on low-value features                   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Feature Backlog Schema:**
```sql
CREATE TABLE feature_backlog (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    category TEXT,  -- "core", "user_management", "integration", etc.
    impact_score INTEGER DEFAULT 5,  -- 1-10
    effort_score INTEGER DEFAULT 5,  -- 1-10
    risk_score INTEGER DEFAULT 5,  -- 1-10
    pareto_score REAL,  -- Calculated
    status TEXT DEFAULT 'backlog',  -- "backlog", "in_progress", "completed", "skipped"
    dependencies JSON,  -- List of feature IDs this depends on
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- Index for fast Pareto sorting
CREATE INDEX idx_pareto_score ON feature_backlog(pareto_score DESC);
CREATE INDEX idx_status ON feature_backlog(status);
```

**Daily Workflow:**
```python
# Each morning (or when starting work)
async def select_todays_feature(project_id: str) -> Feature:
    """
    Select highest Pareto-score feature from backlog
    Re-score based on learning from yesterday's features
    """
    # Get all backlog features
    backlog = await db.get_backlog_features(project_id)
    
    # Re-score based on learning (optional ML model)
    for feature in backlog:
        feature.pareto_score = calculate_pareto_score(
            impact=feature.impact_score,
            effort=feature.effort_score,
            risk=feature.risk_score,
        )
        await db.update_feature(feature)
    
    # Pick top feature
    top_feature = await db.get_top_pareto_feature(project_id)
    
    logger.info(
        "todays_feature_selected",
        feature_id=top_feature.id,
        feature_title=top_feature.title,
        pareto_score=top_feature.pareto_score,
    )
    
    return top_feature
```

---

### 4. Database Choice
**Decision:** SQLite (local-first)

**Rationale:**
- Zero configuration (no server setup)
- Single file database (`~/.dobby/dobby.db`)
- Perfect for solo founders/individual developers
- Built-in full-text search
- ACID compliant
- Backup = copy single file
- No network latency (all local)

**Schema Location:** `~/.dobby/dobby.db`

**Backup Strategy:**
```bash
# Daily backup (cron job)
cp ~/.dobby/dobby.db ~/.dobby/backups/dobby_$(date +%Y%m%d).db

# Restore
cp ~/.dobby/backups/dobby_20260721.db ~/.dobby/dobby.db
```

---

### 5. YOLO Mode (Bypass Wizard)
**Decision:** YES - Users can bypass wizard for instant generation

**Two Modes:**

#### Mode 1: Wizard-Guided (Default)
```
User → Feature Wizard (7 steps) → Verify each step → Edit → Finalize
Time: ~30 minutes per feature
Control: Maximum (edit at every step)
Quality: Highest (verified at each step)
```

#### Mode 2: YOLO Mode (Instant)
```
User → "Generate feature: X" → Full pipeline in one go → Review final output
Time: ~2-5 minutes per feature
Control: Minimal (review at end only)
Quality: Good (verified at end)
```

**YOLO Mode Implementation:**
```python
async def generate_feature_yolo(
    project_id: str,
    feature_title: str,
    feature_description: str,
) -> FeatureResult:
    """
    YOLO Mode: Generate complete feature in one go (bypass wizard)
    
    Pipeline:
    1. Generate all 7 steps automatically (no user intervention)
    2. Run deterministic verification on final output
    3. Add to graph
    4. Return for review
    
    User can then:
    - Accept (finalize)
    - Edit (manual changes)
    - Reject (delete and retry)
    """
    # Generate all steps automatically
    feature = await generate_feature_spec(feature_title, feature_description)
    story = await generate_user_story(feature)
    analysis = await generate_functional_analysis(story)
    flowchart = await generate_flowchart(analysis)
    pseudocode = await generate_pseudocode(flowchart)
    tests = await generate_tdd_tests(pseudocode)
    docs = await generate_documentation(tests)
    
    # Verify final output
    verification = await deterministic_verifier.verify_feature(docs)
    
    # Add to graph
    feature_node = await graph.add_feature(
        project_id=project_id,
        feature=feature,
        story=story,
        analysis=analysis,
        flowchart=flowchart,
        pseudocode=pseudocode,
        tests=tests,
        docs=docs,
        verification=verification,
    )
    
    return FeatureResult(
        node_id=feature_node.id,
        status="pending_review",  # User must accept/reject
        verification_score=verification.overall_score,
        generated_content=docs,
    )
```

**UI for YOLO Mode:**
```
┌─────────────────────────────────────────────────────────────┐
│  🚀 YOLO Mode - Instant Feature Generation                   │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Feature Title: [Smart action item detection_____________]  │
│                                                              │
│  Description:                                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Automatically detect action items from meeting       │   │
│  │ transcripts and assign them to participants          │   │
│  │                                                       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ⚠️  YOLO Mode bypasses the wizard and generates           │
│     everything in one go. Review carefully before           │
│     accepting.                                              │
│                                                              │
│  Estimated time: 2-5 minutes                                │
│  Verification: Will run after generation                    │
│                                                              │
│  [Cancel]  [🚀 Generate YOLO Mode]                          │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Comparison:**

| Aspect | Wizard Mode | YOLO Mode |
|--------|-------------|-----------|
| **Time per feature** | ~30 min | ~2-5 min |
| **User control** | Maximum (7 edit points) | Minimal (review at end) |
| **Quality** | Highest (verified each step) | Good (verified at end) |
| **Learning** | High (understand each step) | Low (black box) |
| **Best for** | Critical features, learning | Quick iteration, experienced users |
| **Verification** | 7 checkpoints | 1 final checkpoint |

**Recommendation:**
- **Early days (1-100):** Use Wizard Mode to learn the system
- **Middle (100-500):** Mix of both (critical features in wizard, routine in YOLO)
- **Late (500-1000):** Mostly YOLO Mode for speed

---

## 📊 Updated Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    DOBBY v2.0 ARCHITECTURE                   │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Tauri Desktop App (Rust)                 │   │
│  │  ┌────────────────────────────────────────────────┐  │   │
│  │  │  React/Vue Frontend                            │  │   │
│  │  │  - Dashboard (graph visualization)             │  │   │
│  │  │  - Feature Wizard (7-step UI)                  │  │   │
│  │  │  - Section Editor (versioned)                  │  │   │
│  │  │  - YOLO Mode (instant generation)              │  │   │
│  │  │  - Pareto Prioritization (daily feature)       │  │   │
│  │  └────────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
│    │                                                         │
│    │ HTTP/WebSocket                                          │
│    │                                                         │
│    ▼                                                         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │          FastAPI Backend (Python)                     │   │
│  │  ┌────────────────────────────────────────────────┐  │   │
│  │  │  API Routes                                    │  │   │
│  │  │  - /api/v1/projects                            │  │   │
│  │  │  - /api/v1/features                            │  │   │
│  │  │  - /api/v1/wizard                              │  │   │
│  │  │  - /api/v1/yolo                                │  │   │
│  │  │  - /api/v1/verify                              │  │   │
│  │  │  - /api/v1/export                              │  │   │
│  │  └────────────────────────────────────────────────┘  │   │
│  │  ┌────────────────────────────────────────────────┐  │   │
│  │  │  Core Services                                 │  │   │
│  │  │  - GraphManager (nodes, edges)                 │  │   │
│  │  │  - WizardPipeline (7-step orchestration)       │  │   │
│  │  │  - YOLOGenerator (instant generation)          │  │   │
│  │  │  - DeterministicVerifier (7 checks)            │  │   │
│  │  │  - ParetoScorer (feature prioritization)       │  │   │
│  │  │  - DocumentAggregator (29-doc pack export)     │  │   │
│  │  └────────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
│    │                                                         │
│    │ SQLAlchemy                                              │
│    │                                                         │
│    ▼                                                         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │          SQLite Database (~/.dobby/dobby.db)          │   │
│  │  ┌────────────────────────────────────────────────┐  │   │
│  │  │  Tables:                                       │  │   │
│  │  │  - projects                                    │  │   │
│  │  │  - nodes (graph nodes)                         │  │   │
│  │  │  - edges (graph edges)                         │  │   │
│  │  │  - feature_backlog                             │  │   │
│  │  │  - verification_results                        │  │   │
│  │  │  - audit_trail                                 │  │   │
│  │  │  - templates                                   │  │   │
│  │  │  - sessions                                    │  │   │
│  │  └────────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
│    │                                                         │
│    │ HTTP                                                    │
│    │                                                         │
│    ▼                                                         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │          Ollama (Local LLM)                           │   │
│  │  - llama3.2 or mistral                               │   │
│  │  - Runs on user's machine                            │   │
│  │  - No API costs, privacy-preserving                  │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 🎯 Implementation Priorities

### Phase 1: Foundation (Week 1-2) - NOW
- [ ] SQLite database schema and migrations
- [ ] Graph data structures (Node, Edge, Graph classes)
- [ ] Session management (create, resume, persist)
- [ ] Audit trail system
- [ ] FastAPI project scaffold

### Phase 2: Core Pipeline (Week 3-4)
- [ ] 7-step wizard pipeline
- [ ] YOLO mode generator
- [ ] Deterministic verifier (7 checks)
- [ ] Pareto scorer
- [ ] Ollama integration

### Phase 3: Tauri UI (Week 5-8)
- [ ] Tauri app scaffold
- [ ] Dashboard with graph visualization
- [ ] Feature wizard UI
- [ ] YOLO mode UI
- [ ] Section editor with versioning
- [ ] Document export

### Phase 4: Advanced (Week 9-12)
- [ ] Template editor
- [ ] Graph visualization (interactive)
- [ ] Daily Pareto feature selection
- [ ] Backup/restore

---

## ✅ Next Steps

1. **Create database schema** (`src/db/schema.py`)
2. **Implement graph data structures** (`src/graph/`)
3. **Set up FastAPI project** (`src/main.py`, `src/api/`)
4. **Implement wizard pipeline** (`src/pipeline/wizard.py`)
5. **Implement YOLO generator** (`src/pipeline/yolo.py`)
6. **Create Tauri app scaffold** (`tauri-app/`)

**Ready to start Phase 1 implementation?** 🚀

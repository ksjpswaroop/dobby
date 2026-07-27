# Dobby v2.0 Architecture Analysis

## 📊 Current Status (v1.0)

### ✅ What's Built

| Component | Status | Lines | Notes |
|-----------|--------|-------|-------|
| **Iterative Generator** | ✅ Complete | 500 | Generate-Verify-Correct-Finalize-Stitch pipeline |
| **Deterministic Verifier** | ✅ Complete | 700 | 7 check types (NO LLM) |
| **Document Memory** | ✅ Complete | 200 | Terminology, facts, cross-refs tracking |
| **PRD Agent** | ✅ Complete | 220 | 39-section PRD generation |
| **Templates** | ✅ Complete | 29 files | All document types templated |
| **Agent Prompts** | ✅ Complete | 13 files | Specialized prompts per doc type |
| **FastAPI Backend** | ✅ Partial | 300 | Basic API routes, needs state persistence |
| **State Machine** | ✅ Partial | 230 | Job states, needs graph-based dependencies |

### ❌ What's Missing

| Component | Priority | Effort | Notes |
|-----------|----------|--------|-------|
| **Graph-Based Architecture** | P0 | High | Features → Stories → Tests → Docs as graph |
| **Stateful Session Management** | P0 | High | Persist state across days/weeks |
| **Database Layer** | P0 | Medium | SQLite/PostgreSQL for long-term storage |
| **Feature Wizard Pipeline** | P0 | High | Feature→Story→Analysis→Flowchart→Pseudocode→TDD→Docs |
| **UI (Tauri/Web)** | P0 | Very High | User-controlled, section-by-section editing |
| **Template Editor** | P1 | Medium | Customize templates without breaking generation |
| **Section CRUD** | P0 | Medium | Create, Read, Update, Delete, Version sections |
| **Graph Visualization** | P1 | High | Interactive dependency graph |
| **Export System** | P1 | Low | Generate 29-doc pack on-demand |
| **Audit Trail** | P1 | Medium | Full history of changes |

---

## 🏗️ v2.0 Architecture Design

### Core Principles

1. **Graph-Based:** Everything is a node in a dependency graph
2. **Stateful:** Persist every change, resume anytime
3. **Verifiable:** Deterministic checks at every step
4. **User-Controlled:** Wizards guide, user decides
5. **Incremental:** One feature at a time, one section at a time
6. **Traceable:** Full audit trail from idea to implementation

---

## 📐 Graph-Based Architecture

### Node Types

```
┌─────────────────────────────────────────────────────────────┐
│                    DOCUMENT GRAPH                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Idea (root)                                                 │
│    │                                                         │
│    ├─→ Feature_001                                           │
│    │     ├─→ User_Story_001                                  │
│    │     │     ├─→ Functional_Analysis_001                   │
│    │     │     │     ├─→ Flowchart_001                       │
│    │     │     │     │     ├─→ Pseudocode_001                │
│    │     │     │     │     │     ├─→ TDD_Tests_001           │
│    │     │     │     │     │     │     ├─→ Documentation_001 │
│    │     │     │     │     │     │     └─→ Code_001          │
│    │     │     │     │     │     └─→ ...                     │
│    │     │     │     │     └─→ ...                           │
│    │     │     │     └─→ ...                                 │
│    │     │     └─→ User_Story_002                            │
│    │     └─→ Feature_002                                     │
│    └─→ ...                                                   │
│                                                              │
│  Document_Pack (generated on-demand)                         │
│    ├─→ PRD.md (aggregates all features)                      │
│    ├─→ ARCHITECTURE.md                                       │
│    ├─→ BACKLOG.md                                            │
│    └─→ ... (29 docs total)                                   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Node Schema

```python
@dataclass
class GraphNode:
    node_id: str  # UUID
    node_type: str  # "idea", "feature", "user_story", "functional_analysis", etc.
    title: str
    content: str
    status: str  # "draft", "verified", "finalized"
    parent_id: Optional[str]  # Parent node ID
    children: List[str]  # Child node IDs
    metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
    version: int
    verification_result: Optional[VerificationResult]
    audit_trail: List[AuditEntry]
```

### Edge Schema

```python
@dataclass
class GraphEdge:
    edge_id: str
    source_node_id: str
    target_node_id: str
    edge_type: str  # "generates", "refines", "implements", "tests", "documents"
    metadata: Dict[str, Any]
```

---

## 🗄️ Stateful Session Management

### Database Schema (SQLite)

```sql
-- Projects
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    idea TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'active'
);

-- Graph Nodes
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    node_type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    status TEXT DEFAULT 'draft',
    parent_id TEXT REFERENCES nodes(id),
    metadata JSON,
    version INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Graph Edges
CREATE TABLE edges (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    source_node_id TEXT REFERENCES nodes(id),
    target_node_id TEXT REFERENCES nodes(id),
    edge_type TEXT NOT NULL,
    metadata JSON
);

-- Verification Results
CREATE TABLE verification_results (
    id TEXT PRIMARY KEY,
    node_id TEXT REFERENCES nodes(id),
    overall_score REAL,
    passed BOOLEAN,
    issues JSON,
    checks_performed JSON,
    metrics JSON,
    verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Audit Trail
CREATE TABLE audit_trail (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    node_id TEXT REFERENCES nodes(id),
    action TEXT NOT NULL,  -- "create", "update", "delete", "verify", "finalize"
    old_content TEXT,
    new_content TEXT,
    user_id TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Templates
CREATE TABLE templates (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    content TEXT NOT NULL,
    version INTEGER DEFAULT 1,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Sessions
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    current_node_id TEXT REFERENCES nodes(id),
    state JSON,  -- Wizard state, UI state
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 🧙 Feature Wizard Pipeline

### Wizard Steps

```
┌─────────────────────────────────────────────────────────────┐
│              FEATURE WIZARD (7 Steps)                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Step 1: Feature Definition                                  │
│  ┌────────────────────────────────────────────────────┐     │
│  │ Input: Feature name, description, priority         │     │
│  │ Generate: Feature spec (200-500 words)             │     │
│  │ Verify: Completeness, clarity                      │     │
│  │ User: Edit, approve, or reject                     │     │
│  └────────────────────────────────────────────────────┘     │
│    ↓                                                         │
│  Step 2: User Story                                          │
│  ┌────────────────────────────────────────────────────┐     │
│  │ Input: Feature spec                                │     │
│  │ Generate: "As a [user], I want [action]..."        │     │
│  │ Generate: Acceptance criteria (Gherkin)            │     │
│  │ Verify: Story format, criteria completeness        │     │
│  │ User: Edit, approve                                │     │
│  └────────────────────────────────────────────────────┘     │
│    ↓                                                         │
│  Step 3: Functional Analysis                                 │
│  ┌────────────────────────────────────────────────────┐     │
│  │ Input: User story, acceptance criteria             │     │
│  │ Generate: Input/output specs, edge cases           │     │
│  │ Generate: Business logic breakdown                 │     │
│  │ Verify: Coverage, consistency                      │     │
│  │ User: Edit, approve                                │     │
│  └────────────────────────────────────────────────────┘     │
│    ↓                                                         │
│  Step 4: Flowchart                                           │
│  ┌────────────────────────────────────────────────────┐     │
│  │ Input: Functional analysis                         │     │
│  │ Generate: Mermaid flowchart                        │     │
│  │ Generate: Decision tree                            │     │
│  │ Verify: All paths covered                          │     │
│  │ User: Edit, visualize                              │     │
│  └────────────────────────────────────────────────────┘     │
│    ↓                                                         │
│  Step 5: Pseudocode                                          │
│  ┌────────────────────────────────────────────────────┐     │
│  │ Input: Flowchart, functional analysis              │     │
│  │ Generate: Language-agnostic pseudocode             │     │
│  │ Generate: Algorithm steps                          │     │
│  │ Verify: Logic completeness                         │     │
│  │ User: Edit, refine                                 │     │
│  └────────────────────────────────────────────────────┘     │
│    ↓                                                         │
│  Step 6: TDD Test Cases                                      │
│  ┌────────────────────────────────────────────────────┐     │
│  │ Input: Pseudocode, acceptance criteria             │     │
│  │ Generate: pytest test cases                        │     │
│  │ Generate: Edge case tests                          │     │
│  │ Verify: Coverage, assertions                       │     │
│  │ User: Edit, run tests                              │     │
│  └────────────────────────────────────────────────────┘     │
│    ↓                                                         │
│  Step 7: Documentation                                       │
│  ┌────────────────────────────────────────────────────┐     │
│  │ Input: All previous steps                          │     │
│  │ Generate: API docs, user guide                     │     │
│  │ Generate: Integration into PRD                     │     │
│  │ Verify: Completeness, consistency                  │     │
│  │ User: Edit, finalize                               │     │
│  └────────────────────────────────────────────────────┘     │
│                                                              │
│  Output: Feature complete, added to graph, ready for next   │
└─────────────────────────────────────────────────────────────┘
```

### Wizard State Machine

```python
class WizardState(str, Enum):
    NOT_STARTED = "not_started"
    FEATURE_DEFINED = "feature_defined"
    STORY_CREATED = "story_created"
    ANALYSIS_COMPLETE = "analysis_complete"
    FLOWCHART_GENERATED = "flowchart_generated"
    PSEUDOCODE_COMPLETE = "pseudocode_complete"
    TESTS_GENERATED = "tests_generated"
    DOCUMENTATION_COMPLETE = "documentation_complete"
    FINALIZED = "finalized"

@dataclass
class WizardSession:
    session_id: str
    project_id: str
    current_step: int  # 1-7
    state: WizardState
    feature_data: Dict[str, Any]  # Accumulated data from each step
    user_edits: Dict[int, List[str]]  # Step → list of user edits
    verification_results: Dict[int, VerificationResult]
    started_at: datetime
    last_active: datetime
```

---

## 🎨 UI Design (User-Controlled Development)

### Main Dashboard

```
┌─────────────────────────────────────────────────────────────┐
│  Dobby v2.0 - Project: AI Meeting Notes App                  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  📊 Progress: 47/1000 features (4.7%) - Day 47 of 1000      │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  GRAPH VISUALIZATION                                  │   │
│  │                                                       │   │
│  │  [Idea] ──→ [Feature_001] ──→ [Feature_002] ──→ ...  │   │
│  │               │                  │                    │   │
│  │               ├─→ [Story_001]    ├─→ [Story_003]     │   │
│  │               │     └─→ [Tests]  │     └─→ [Tests]   │   │
│  │               └─→ [Story_002]    └─→ [Story_004]     │   │
│  │                                                       │   │
│  │  Legend: 🟢 Finalized 🟡 In Progress ⚪ Not Started   │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────┐  ┌──────────────────┐                │
│  │  📝 FEATURES     │  │  📄 DOCUMENTS    │                │
│  │  ──────────────  │  │  ──────────────  │                │
│  │  ✅ Feature_001  │  │  📄 PRD.md       │                │
│  │  ✅ Feature_002  │  │  📄 ARCH.md      │                │
│  │  🟡 Feature_003  │  │  📄 BACKLOG.md   │                │
│  │  ⚪ Feature_004  │  │  📄 TDD_SPEC.md  │                │
│  │  ⚪ Feature_005  │  │  ... (25 more)  │                │
│  │                  │  │                  │                │
│  │  [+ Add Feature] │  │  [Export All]    │                │
│  └──────────────────┘  └──────────────────┘                │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  RECENT ACTIVITY                                     │   │
│  │  ─────────────────                                   │   │
│  │  • Feature_047: TDD tests generated (2 min ago)      │   │
│  │  • Feature_046: Documentation finalized (1 hour ago) │   │
│  │  • Feature_045: Flowchart created (3 hours ago)      │   │
│  │  • PRD.md updated with Feature_044 (yesterday)       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Feature Wizard UI

```
┌─────────────────────────────────────────────────────────────┐
│  Feature Wizard - Step 3 of 7: Functional Analysis           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Progress: [███░░░░░░] 3/7 steps                            │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  INPUT: User Story                                   │   │
│  │  ─────────────────────────────────────────────────   │   │
│  │  "As a user, I want to record meetings automatically │   │
│  │   so that I can focus on the conversation."          │   │
│  │                                                       │   │
│  │  Acceptance Criteria:                                 │   │
│  │  ✓ Given I'm in a meeting, when I click record,      │   │
│  │    then audio is captured                            │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  GENERATED: Functional Analysis                      │   │
│  │  ─────────────────────────────────────────────────   │   │
│  │  [Editable text area with generated content]         │   │
│  │                                                       │   │
│  │  Inputs:                                              │   │
│  │  - Audio stream from microphone                       │   │
│  │  - User permission to record                          │   │
│  │                                                       │   │
│  │  Outputs:                                             │   │
│  │  - Audio file (WAV/MP3)                               │   │
│  │  - Metadata (timestamp, duration)                     │   │
│  │                                                       │   │
│  │  Edge Cases:                                          │   │
│  │  - No microphone access                               │   │
│  │  - Meeting interrupted                                │   │
│  │  - Low storage space                                  │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  Verification: ✅ Passed (92/100)                           │
│  ─────────────────────────────────────────────────────────  │
│  ✓ Completeness: All inputs/outputs defined                 │
│  ✓ Edge cases: 3 edge cases covered                         │
│  ⚠ Warning: Consider adding error handling scenarios        │
│                                                              │
│  [← Previous]  [Edit]  [Regenerate]  [Next: Flowchart →]   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Section Editor UI

```
┌─────────────────────────────────────────────────────────────┐
│  PRD.md - Section 09: Functional Requirements                │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Version: 3 (edited 2 hours ago)  [History] [Compare]       │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  ## 9. Functional Requirements                       │   │
│  │                                                       │   │
│  │  ### FR-001: Automatic Meeting Recording             │   │
│  │  [User can edit this content directly...]            │   │
│  │                                                       │   │
│  │  **Acceptance Criteria:**                            │   │
│  │  - [x] Given I'm in a meeting...                     │   │
│  │  - [ ] When I click record...                        │   │
│  │                                                       │   │
│  │  ### FR-002: [Add new requirement...]                │   │
│  │                                                       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  Verification: ✅ Passed (88/100)                           │
│  ─────────────────────────────────────────────────────────  │
│  ✓ Structure: All required headers present                  │
│  ✓ Format: Valid markdown                                   │
│  ✓ Completeness: 2/3 acceptance criteria defined            │
│  ⚠ Warning: FR-002 missing acceptance criteria              │
│                                                              │
│  [Save]  [Revert to v2]  [Verify]  [Export Section]        │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 📈 1000 Features in 1000 Days Plan

### Feature Categories (300-1000 features total)

| Category | Count | Examples |
|----------|-------|----------|
| **Core Features** | 100-200 | Recording, transcription, summarization, search |
| **User Management** | 50-100 | Auth, profiles, permissions, teams |
| **Integrations** | 100-200 | Calendar, email, Slack, Zoom, Teams |
| **AI Features** | 100-200 | Summarization, action items, sentiment analysis |
| **Analytics** | 50-100 | Usage stats, meeting insights, trends |
| **Admin** | 50-100 | Billing, settings, audit logs, compliance |
| **Mobile** | 50-100 | iOS app, Android app, offline mode |
| **API** | 50-100 | REST API, webhooks, SDKs |
| **Infrastructure** | 50-100 | Scaling, monitoring, backup, disaster recovery |
| **Security** | 50-100 | Encryption, 2FA, SSO, penetration testing |
| **Total** | **300-1000** | |

### Daily Workflow

```
Day 1:
  → Select feature category
  → Start wizard for Feature_001
  → Complete all 7 steps
  → Verify and finalize
  → Feature added to graph

Day 2:
  → Start wizard for Feature_002
  → ...

Day 47:
  → 47 features complete
  → Export PRD.md (auto-aggregates all 47 features)
  → Review progress on graph

Day 300:
  → 300 features complete
  → Full 29-doc pack export
  → Ready for MVP launch

Day 1000:
  → 1000 features complete
  → Enterprise-grade documentation
  → Full audit trail
```

---

## 🔧 Implementation Plan

### Phase 1: Foundation (Week 1-2)
- [ ] Database layer (SQLite schema, migrations)
- [ ] Graph data structures (nodes, edges)
- [ ] Session management (persist/resume)
- [ ] Audit trail system

### Phase 2: Wizard Pipeline (Week 3-4)
- [ ] 7-step wizard implementation
- [ ] Deterministic verification for each step
- [ ] User edit tracking
- [ ] State machine for wizard flow

### Phase 3: UI (Week 5-8)
- [ ] Tauri desktop app scaffold
- [ ] Dashboard with graph visualization
- [ ] Feature wizard UI
- [ ] Section editor with versioning
- [ ] Document export system

### Phase 4: Advanced Features (Week 9-12)
- [ ] Template editor
- [ ] Graph visualization (interactive)
- [ ] Collaboration features (multi-user)
- [ ] API for programmatic access

### Phase 5: Scale & Polish (Week 13-16)
- [ ] Performance optimization (1000+ features)
- [ ] Backup/restore
- [ ] Import/export formats (Markdown, PDF, DOCX)
- [ ] Documentation and tutorials

---

## ✅ Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Features per day** | 1+ | Count finalized features |
| **Wizard completion time** | <30 min | Time from step 1 to 7 |
| **Verification pass rate** | >90% | % of sections passing verification |
| **User edits per feature** | 2-5 | Count of manual edits |
| **Session resume time** | <5 sec | Time to load previous session |
| **Graph size** | 1000+ nodes | Total nodes in graph |
| **Document export time** | <2 min | Time to generate 29-doc pack |

---

## 🎯 Next Steps

1. **Approve architecture** - Confirm graph-based, stateful design
2. **Prioritize features** - Which 300-1000 features for v1.0?
3. **Choose UI framework** - Tauri (Rust) vs Web (React/Vue)?
4. **Design database schema** - Finalize SQLite vs PostgreSQL
5. **Start Phase 1** - Database layer and graph structures

---

**Ready to proceed with detailed implementation plan?** 🚀

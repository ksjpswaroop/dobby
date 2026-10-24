# Phase 2 Goal Understanding: Core Pipeline Implementation

## Step 1: Surface the Core Intent

**What is being accomplished:**
Build the **core generation pipeline** for Dobby v2.0 that transforms it from a data layer (Phase 1) into a **fully functional document generation platform**.

**Primary goal:**
Enable users to generate comprehensive documentation through two modes:
1. **Wizard-Guided Mode** - 7-step interactive pipeline with verification at each step
2. **YOLO Mode** - Instant generation bypassing the wizard

**Expected outcome:**
- Users can add a feature to backlog → select it → generate complete documentation through wizard or YOLO
- Every generation step is verified deterministically (no LLM verification)
- Features are prioritized daily using Pareto scoring
- Local LLM (Ollama) integration for all generation tasks

**Reason behind it:**
Phase 1 built the foundation (database, graph, API, sessions, audit), but users cannot yet **generate anything**. Phase 2 adds the actual generation capability that makes Dobby useful.

---

## Step 2: Identify Stakeholders and Context

**Who benefits:**
1. **Solo founders** - Generate comprehensive docs without hiring technical writers
2. **Product teams** - Collaborate on feature documentation with full traceability
3. **Developers** - Get TDD tests, pseudocode, flowcharts automatically generated
4. **Investors** - See complete, auditable documentation trail

**Who is affected:**
- Users will interact with wizard/YOLO modes daily
- Ollama must be running locally (dependency)
- Generation quality directly impacts user trust
- Verification system must be fast (<5 seconds per check)

**Business context:**
- Part of 1000-day roadmap (300-1000 features)
- Must scale to handle 1000+ features without performance degradation
- Must maintain hallucination-free generation (deterministic verification only)

---

## Step 3: Capture Constraints

**What must be true:**
- ✅ **Deterministic verification only** - NO LLM-based verification (hallucination risk)
- ✅ **7 check types** - Structure, format, consistency, cross-reference, completeness, statistical, quality
- ✅ **Ollama integration** - Must work with local llama3.2 or mistral
- ✅ **Pareto re-scoring** - Daily re-prioritization based on learning
- ✅ **Wizard state machine** - 7 steps, user can edit at each step, must verify before proceeding
- ✅ **YOLO mode** - Generate all 7 steps in one go, verify at end, user reviews and accepts/rejects
- ✅ **Performance** - Each verification check <5 seconds, full wizard step <30 seconds

**What must be avoided:**
- ❌ LLM-based verification (hallucination risk)
- ❌ Blocking UI during generation (must be async)
- ❌ Lost state between steps (must persist to database)
- ❌ Silent failures (must log and report errors)
- ❌ Ollama API timeouts (must handle gracefully with retries)

**Technical constraints:**
- Ollama runs on user's machine (localhost:11434)
- SQLite database for all persistence
- FastAPI backend with async endpoints
- Tauri frontend (Phase 3) will call these APIs

---

## Step 4: Define Success Criteria

**How we know this succeeded:**

### Functional Criteria
1. ✅ **Wizard Mode Works**
   - User can start wizard for a feature
   - Each of 7 steps generates content via Ollama
   - Each step is verified deterministically (score ≥85%)
   - User can edit content at each step
   - State persists between steps (can close app, resume later)
   - Final output is stitched together and saved to graph

2. ✅ **YOLO Mode Works**
   - User can trigger YOLO generation for a feature
   - All 7 steps generate automatically (no user intervention)
   - Final output is verified deterministically
   - User can review, edit, accept, or reject
   - Accepted content is saved to graph

3. ✅ **Deterministic Verifier Works**
   - 7 check types implemented (no LLM calls)
   - Each check returns score (0-100) and issues list
   - Overall score calculated correctly
   - Verification completes in <5 seconds per check

4. ✅ **Pareto Scorer Works**
   - Features scored by formula: `(Impact * 0.6) - (Effort * 0.3) - (Risk * 0.1)`
   - Daily re-scoring based on learning (optional ML model)
   - Top features returned sorted by Pareto score
   - Features can be re-scored manually by user

5. ✅ **Ollama Integration Works**
   - Connects to local Ollama instance (localhost:11434)
   - Generates content for all 7 steps
   - Handles timeouts and retries
   - Falls back gracefully if Ollama is unavailable

### Performance Criteria
- Wizard step generation: <30 seconds
- YOLO full generation: <5 minutes
- Verification per check: <5 seconds
- Pareto re-scoring (100 features): <1 second
- API response time (p95): <500ms

### Quality Criteria
- Verification score threshold: ≥85% per step
- Document consistency score: ≥90% overall
- Hallucination rate: 0% (deterministic verification)
- Test coverage: ≥80% for pipeline code

---

## Step 5: Output Goal Statement

```
GOAL: Implement Phase 2 Core Pipeline for Dobby v2.0 consisting of:
(1) 7-Step Wizard Pipeline that orchestrates Feature→Story→Analysis→
Flowchart→Pseudocode→TDD Tests→Documentation with deterministic 
verification at each step and state persistence,
(2) YOLO Mode for instant generation bypassing the wizard with final 
verification and user review,
(3) Deterministic Verifier with 7 check types (structure, format, 
consistency, cross-reference, completeness, statistical, quality) using 
only algorithm-driven checks (no LLM verification),
(4) Pareto Scorer for automatic feature prioritization with daily 
re-scoring based on learning,
(5) Ollama Integration for local LLM generation with timeout handling 
and retries,
such that users can generate comprehensive, hallucination-free 
documentation through either guided or instant modes, with all generation 
tracked in the audit trail and persisted to the graph database.
```

---

## Output Flags

**Status:** `READY` — Goal is clear and actionable

**Decomposition:** `DECOMPOSE_ME` — Goal needs breakdown into implementation tasks

---

## Implementation Plan (Phase 2)

### Week 3: Core Pipeline Components

**Day 1-2: Deterministic Verifier** (`src/verifiers/deterministic_verifier.py`)
- 7 check types implementation
- Scoring algorithm
- Issue detection and reporting
- Tests for each check type

**Day 3-4: Ollama Integration** (`src/llm/ollama_client.py`)
- Async HTTP client for Ollama API
- Generation prompts for each of 7 steps
- Timeout and retry handling
- Connection health checks

**Day 5-7: Pareto Scorer** (`src/pipeline/pareto.py`)
- Pareto score calculation
- Daily re-scoring logic
- Learning model (optional)
- API endpoints for scoring

### Week 4: Wizard and YOLO Pipelines

**Day 8-9: Wizard Pipeline** (`src/pipeline/wizard.py`)
- 7-step state machine
- Orchestration logic
- User edit/approval workflow
- State persistence

**Day 10-11: YOLO Pipeline** (`src/pipeline/yolo.py`)
- Instant generation orchestration
- Final verification
- Review and accept/reject workflow

**Day 12-13: Integration Testing**
- End-to-end wizard test
- End-to-end YOLO test
- Performance benchmarks
- Error handling tests

**Day 14: Documentation and Polish**
- API documentation
- Usage examples
- Bug fixes
- Phase 2 summary

---

## Ready to Proceed

All goals are clear, constraints are captured, success criteria are defined.

**Proceeding with Phase 2 implementation now.** 🚀

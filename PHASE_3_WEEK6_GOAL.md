# Phase 3 Week 6: Goal Understanding

## Step 1: Surface the Core Intent

**What is being accomplished:**
Integrate the Tauri desktop app with the FastAPI backend and add interactive graph visualization to enable users to:
- See real-time project statistics from the database
- Start wizard/YOLO generation from the desktop app
- Visualize feature dependencies as interactive graphs
- View feature backlog with Pareto scores
- Complete the full user workflow from desktop UI

**Primary goal:** Connect the frontend (Tauri/React) to the backend (FastAPI/Python) and add visual graph representation of the document generation graph.

**Expected outcome:** A working desktop app that can fetch data from FastAPI, trigger generation pipelines, and display dependency graphs.

---

## Step 2: Identify Stakeholders and Context

**Who benefits:**
1. **Solo developers (primary user: Swaroop)** - Native desktop app for document generation
2. **Product teams** - Visual collaboration on feature dependencies
3. **Investors/Reviewers** - See complete documentation with visual traceability

**Who is affected:**
- Tauri app (Rust backend needs HTTP client integration)
- FastAPI backend (needs to expose endpoints for Tauri)
- React frontend (needs API client integration)
- Graph visualization (Mermaid.js integration)

**Context:**
- Phase 3 Week 5 complete: Tauri scaffold built (18 files, 1,034 lines)
- Phase 2 complete: Core pipelines (Wizard, YOLO, Verifier, Pareto, Ollama)
- FastAPI backend already has routes (`src/api/routes.py`)
- Database schema ready (`src/db/schema.py`)
- Graph structures implemented (`src/graph/graph.py`)

---

## Step 3: Capture Constraints

**What must be true:**
- ✅ Tauri app calls FastAPI via HTTP (localhost:8000)
- ✅ FastAPI must be running before Tauri app starts
- ✅ Graph visualization uses Mermaid.js (lightweight, no server needed)
- ✅ Real-time updates (polling or WebSocket for long-running generation)
- ✅ Error handling for offline backend
- ✅ CORS enabled on FastAPI for localhost:1420

**What must be avoided:**
- ❌ Direct database access from Tauri (keep separation of concerns)
- ❌ Hardcoded backend URLs (use environment variables)
- ❌ Blocking UI during generation (show progress/loading states)
- ❌ Large graph rendering performance issues (limit nodes or use virtualization)

**Technical constraints:**
- Tauri commands must be async (Rust tokio runtime)
- React components must handle async API calls
- Mermaid.js graphs can be large (need zoom/pan)
- FastAPI endpoints need authentication (optional for local dev)

---

## Step 4: Define Success Criteria

**How we know this succeeded:**

### Functional Criteria
- ✅ Dashboard shows real project count, feature count, document count from database
- ✅ "Today's priority feature" displays actual top Pareto-scored feature
- ✅ Clicking "Start Wizard" opens wizard with feature pre-loaded
- ✅ Wizard mode generates content via FastAPI backend (not mock data)
- ✅ YOLO mode generates content via FastAPI backend (not mock data)
- ✅ Graph visualization shows feature → story → tests → docs dependencies
- ✅ Feature backlog list shows all features sorted by Pareto score
- ✅ Clicking a feature starts wizard for that feature

### Performance Criteria
- ✅ Dashboard loads in <2 seconds
- ✅ Graph renders in <5 seconds (up to 100 nodes)
- ✅ Wizard step generation shows progress (no frozen UI)
- ✅ YOLO generation shows estimated time remaining

### Quality Criteria
- ✅ Error messages shown if FastAPI is offline
- ✅ Loading states for all async operations
- ✅ Toast notifications for success/failure
- ✅ Responsive UI (works at 1400x900 and larger)

---

## Step 5: Output Goal Statement

```
GOAL: Integrate Tauri desktop app with FastAPI backend and add Mermaid.js 
graph visualization to enable real-time project statistics, feature backlog 
with Pareto scores, wizard/YOLO generation via API calls, and interactive 
dependency graph rendering, with proper error handling, loading states, and 
performance optimization for graphs up to 100 nodes.
```

---

## Output Flags

**Status:** `DECOMPOSE_ME` — Goal is clear but needs detailed breakdown into implementation tasks.

---

## Decomposition: Week 6 Tasks

### Task 1: FastAPI Backend Preparation (2-3 hours)
- [ ] Add CORS middleware for localhost:1420
- [ ] Create dashboard endpoint (`GET /api/v1/projects/{id}/dashboard`)
- [ ] Create feature backlog endpoint (`GET /api/v1/projects/{id}/backlog`)
- [ ] Create wizard endpoints (already exists, verify)
- [ ] Create YOLO endpoints (already exists, verify)
- [ ] Test all endpoints with curl/Postman

### Task 2: Tauri Rust Backend Integration (3-4 hours)
- [ ] Update `commands.rs` to call FastAPI endpoints
- [ ] Add error handling for offline backend
- [ ] Add timeout handling (30s default)
- [ ] Test Tauri commands with mock data
- [ ] Test Tauri commands with real FastAPI

### Task 3: React Frontend API Client (2-3 hours)
- [ ] Create `src/api/client.ts` (Axios instance)
- [ ] Add API methods (getDashboard, getBacklog, startWizard, etc.)
- [ ] Add error handling (retry logic, offline detection)
- [ ] Update Dashboard.tsx to use real API
- [ ] Update Wizard.tsx to use real API
- [ ] Update Yolo.tsx to use real API

### Task 4: Graph Visualization (4-5 hours)
- [ ] Install Mermaid.js (`npm install mermaid`)
- [ ] Create `src/components/GraphViewer.tsx`
- [ ] Add graph data fetch endpoint (`GET /api/v1/projects/{id}/graph`)
- [ ] Implement zoom/pan controls
- [ ] Add legend and node type colors
- [ ] Test with sample graph data (10-100 nodes)

### Task 5: Feature Backlog List (2-3 hours)
- [ ] Create `src/components/FeatureList.tsx`
- [ ] Display features sorted by Pareto score
- [ ] Add filter by status (backlog, in_progress, completed)
- [ ] Add click-to-start-wizard functionality
- [ ] Show scores, categories, dates

### Task 6: Integration Testing (2-3 hours)
- [ ] Test full workflow: Dashboard → Feature → Wizard → Generation
- [ ] Test full workflow: Dashboard → Feature → YOLO → Generation
- [ ] Test graph visualization with real data
- [ ] Test error scenarios (FastAPI offline, timeout, etc.)
- [ ] Document known issues

**Total estimated time:** 15-21 hours (3-4 days)

---

## Success Metrics for Week 6

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Dashboard API Integration** | 100% | Real data from FastAPI |
| **Wizard API Integration** | 100% | Generation via API |
| **YOLO API Integration** | 100% | Generation via API |
| **Graph Visualization** | 100% | Mermaid.js rendering |
| **Feature Backlog UI** | 100% | Sorted by Pareto score |
| **Error Handling** | 100% | Offline detection, retries |
| **Loading States** | 100% | All async ops show progress |
| **Performance** | <5s | Graph render time |

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| FastAPI endpoint changes | Medium | High | Version API (`/api/v1/`), document contracts |
| Mermaid.js performance | Low | Medium | Limit to 100 nodes, add pagination |
| Tauri CORS issues | Medium | High | Configure CORS in FastAPI, test early |
| Long generation times | High | Medium | Show progress, use WebSocket for real-time |
| Graph complexity | Medium | Low | Simplify graph, group nodes by type |

---

## Next Steps

1. **Start with FastAPI backend** (ensure endpoints exist and work)
2. **Then Tauri Rust integration** (call FastAPI from commands)
3. **Then React API client** (call Tauri commands from frontend)
4. **Then Graph visualization** (Mermaid.js integration)
5. **Then Feature backlog UI** (list with Pareto scores)
6. **Finally integration testing** (end-to-end workflow)

**Ready to proceed with Task 1: FastAPI Backend Preparation.** 🚀

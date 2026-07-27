# Build Tracker: Interactive Mind Mapping

**Goal**: Add interactive mind-map workspace to Dobby's Brainstorming stage. Full CRUD, AI generation, export/import. Three phases, each shippable independently.

**State**: 0/66 steps complete

---

## PHASE 1 — Core CRUD + Canvas (Goal: working editor, no AI)

### 1A — Dependencies & Setup

- [ ] **1.1** `tauri-app/package.json` — add `@xyflow/react`, `zustand` to dependencies; `npm install`
- [ ] **1.2** `pyproject.toml` — add `jsonschema` to dev dependencies; `pip install -e ".[dev]"`

### 1B — Database Layer

- [ ] **1.3** `src/db/mindmap_models.py` [NEW] — `MindMap`, `MindMapNode`, `MindMapEdge`, `MindMapSnapshot` ORM classes. Import `Base` from `src.db.schema`. String UUID PKs, `metadata` JSON columns aliased as `extra_metadata`. FK: `project_id`→`projects.id`(CASCADE), `session_id`→`sessions.id`(SET NULL), `mind_map_id`(CASCADE for nodes/edges/snapshots), `parent_id`→`mind_map_nodes.id`(SET NULL). Indexes on `(mind_map_id)`, `(project_id)`, `(parent_id)`. (covers: AC-8)
- [ ] **1.4** `src/db/schema.py` — import mindmap models after `Base` definition so `create_all` picks them up. (covers: AC-8)

### 1C — Schemas & Service

- [ ] **1.5** `src/schemas/__init__.py` [NEW DIR] + `src/schemas/mindmap_schemas.py` [NEW] — Pydantic request/response: `MindMapCreate/Response/Update/ListResponse`, `NodeCreate/Response/Update/MoveRequest`, `EdgeCreate/Response`, `SnapshotSave/Response`, `TreeValidationError`, `MindMapExportSchema`. (covers: AC-2, AC-3, AC-8)
- [ ] **1.6** `src/services/__init__.py` [NEW DIR] + `src/services/mindmap_service.py` [NEW] — 18 functions: `create_map`, `get_map`, `list_maps`, `update_map`, `duplicate_map`(deep copy), `delete_map`(cascade, preserve brainstorm), `create_node`, `get_node`, `update_node`, `move_node`(cycle detection via `_detect_cycle` helper walking ancestor chain), `delete_node`(recursive descendants), `duplicate_node`(deep copy), `get_map_tree`(nested JSON), `create_edge`, `delete_edge`, `save_snapshot`, `get_snapshots`, `validate_tree`(orphan/cycle/invalid checks), `reorder_siblings`. (covers: AC-2, AC-3, AC-8, AC-9)

### 1D — API Routes

- [ ] **1.7** `src/api/mindmap_routes.py` [NEW] — 18 endpoints under a router:
  - `POST /` create map, `GET /{project_id}` list, `GET /map/{map_id}` get, `PATCH /map/{map_id}` update, `POST /map/{map_id}/duplicate`, `DELETE /map/{map_id}`
  - `POST /map/{map_id}/nodes`, `GET /nodes/{node_id}`, `PATCH /nodes/{node_id}`, `PUT /nodes/{node_id}/move`, `DELETE /nodes/{node_id}`, `POST /nodes/{node_id}/duplicate`
  - `GET /map/{map_id}/tree`, `POST /map/{map_id}/edges`, `DELETE /edges/{edge_id}`
  - `POST /map/{map_id}/snapshots`, `GET /map/{map_id}/snapshots`, `POST /map/{map_id}/validate`
  - Error shape: `{"error":"code","message":"...","detail":{}}`. (covers: AC-2, AC-3, AC-8, AC-9)
- [ ] **1.8** `src/main.py` — import and `include_router(mindmap_router, prefix="/api/v1")`. (covers: AC-2)

### 1E — Frontend Foundation

- [ ] **1.9** `tauri-app/src/features/mindmap/types.ts` [NEW DIR] — TS interfaces: `MindMap`, `MindMapNode`, `NodeType`(union of 9 literals), `MindMapEdge`, `MapTree`(`{map, nodes:TreeNode[]}`), `TreeNode extends MindMapNode {children}`, `ViewportState`, `UndoEntry`, `NodePosition`. (covers: AC-5)
- [ ] **1.10** `tauri-app/src/features/mindmap/api.ts` [NEW] — API client functions (axios to `localhost:8000/api/v1/mindmaps`): `createMap`, `listMaps`, `getMap`, `updateMap`, `duplicateMap`, `deleteMap`, `createNode`, `getNode`, `updateNode`, `moveNode`, `deleteNode`, `duplicateNode`, `getMapTree`, `createEdge`, `deleteEdge`, `saveSnapshot`, `listSnapshots`, `validateTree`. (covers: AC-2, AC-3)
- [ ] **1.11** `tauri-app/src/features/mindmap/store.ts` [NEW] — Zustand store: `maps`, `activeMapId`, `tree`, `selectedNodeId`, `undoStack`/`redoStack`(max 50), `isDirty`/`isSaving`/`lastSaved`, `isLoading`/`error`. Actions: `loadMaps`, `selectMap`, `createMap`, `updateMap`, `deleteMap`, `duplicateMap`, `addNode`, `updateNode`, `moveNode`, `deleteNode`, `duplicateNode`, `addEdge`, `deleteEdge`, `selectNode`, `pushUndo`(called before mutating actions), `undo`, `redo`, `setViewport`, `expandAll`, `collapseAll`. (covers: AC-2, AC-3, AC-9)
- [ ] **1.12** `tauri-app/src/features/mindmap/hooks/useMindMap.ts` [NEW] — wraps store + API. Returns `{maps, activeMap, tree, selectedNode, ...actions}`. Loading/error handling. (covers: AC-2, AC-3)
- [ ] **1.13** `tauri-app/src/features/mindmap/hooks/useUndoRedo.ts` [NEW] — keybindings: Ctrl+Z/Cmd+Z undo, Ctrl+Shift+Z/Cmd+Shift+Z redo. Only active when `activeMapId !== null`. (covers: AC-4, AC-9)
- [ ] **1.14** `tauri-app/src/features/mindmap/hooks/useAutoSave.ts` [NEW] — watches `isDirty`, debounces 2s, calls `updateMap` + `getMapTree`. Shows "Saving..." / "Saved" / "Unsaved" indicator. (covers: AC-9)

### 1F — Frontend Components

- [ ] **1.15** `tauri-app/src/features/mindmap/components/EmptyState.tsx` [NEW] — two variants: "no maps yet" (prompt to create), "empty map" (prompt to add root node). Uses shared `Card`, `Button`. (covers: AC-6)
- [ ] **1.16** `tauri-app/src/features/mindmap/components/MindMapNode.tsx` [NEW] — React Flow custom node. SVG icon + label for each `NodeType`, `border-l-4` colored strip, title (editable on double-click), type badge. `Handle` top(bottom) for parent-child. (covers: AC-3, AC-5, AC-6)
- [ ] **1.17** `tauri-app/src/features/mindmap/components/MindMapEdge.tsx` [NEW] — smooth step edge. Dashed for cross-branch, solid for parent-child. (covers: AC-3)
- [ ] **1.18** `tauri-app/src/features/mindmap/components/MindMapCanvas.tsx` [NEW] — wraps `<ReactFlow>`. dagre auto-layout. `<Controls>`, `<MiniMap>`, `<Background>`. `fitView` on load. `onNodeClick`→select, `onConnect`→addEdge, `onNodeDragStop`→update position. Keyboard: Enter(sibling), Tab(child), Delete(confirm delete), Escape(deselect). Collapse/expand via `hidden` toggle. (covers: AC-3, AC-4, AC-6)
- [ ] **1.19** `tauri-app/src/features/mindmap/components/NodeInspector.tsx` [NEW] — right panel (320px). Fields: title(input auto-focused), description(textarea 3 rows), node type(select), color(swatches), priority(1-5 radio), status(draft/in-progress/done select). Save on blur with debounce. Timestamps display. (covers: AC-3, AC-5, AC-6)
- [ ] **1.20** `tauri-app/src/features/mindmap/components/MapToolbar.tsx` [NEW] — horizontal bar: map selector(dropdown), title(inline edit), Add Node, Auto Layout(dagre rerun), Undo/Redo, Expand/Collapse All, Fit to Screen, Validate Tree, Duplicate, Delete(with Modal confirm), save-state indicator. (covers: AC-2, AC-3, AC-6, AC-9)
- [ ] **1.21** `tauri-app/src/features/mindmap/MindMapWorkspace.tsx` [NEW] — entry point. Props: `projectId`, `sessionId?`. Layout: toolbar top, canvas fill, inspector slide-out(abs right, close btn). On mount: load maps, auto-select first or create new. (covers: AC-1)
- [ ] **1.22** `tauri-app/src/features/mindmap/index.ts` [NEW] — barrel export: only `MindMapWorkspace` + types. (covers: AC-1)

### 1G — Integration

- [ ] **1.23** `tauri-app/src/pages/Wizard.tsx` — add tab bar: "Outline" | "Mind Map". When Mind Map active + `sessionId` exists, render `<MindMapWorkspace projectId="default-project" sessionId={sessionId} />`. (covers: AC-1)
- [ ] **1.24** `tauri-app/src/components/AppShell.tsx` — add "Mind Map" nav entry at `/mindmap` with branching icon. (covers: AC-1)
- [ ] **1.25** `tauri-app/src/App.tsx` — add `<Route path="/mindmap" element={<MindMapPage />} />`. Create `pages/MindMapPage.tsx` wrapping `MindMapWorkspace` with `projectId="default-project"`. (covers: AC-1)

### 1H — Tests

- [ ] **1.26** `tests/test_mindmap_crud.py` [NEW] — `TestMindMapCRUD`: `test_create_map`, `test_list_maps`, `test_delete_map_cascades`, `test_delete_map_preserves_brainstorm`, `test_duplicate_map_deep`, `test_create_node`, `test_move_node`, `test_move_node_cycle_prevention`, `test_delete_node_cascades`, `test_reorder_siblings`, `test_validate_tree_clean`, `test_validate_tree_orphan`, `test_validate_tree_cycle`, `test_snapshot_save_list`, `test_edge_crud`. Use `/tmp/dobby_test_{uuid}.db` fixtures. (covers: AC-11)
- [ ] **1.27** `tests/test_mindmap_api.py` [NEW] — `fastapi.testclient.TestClient`. Each endpoint: 201/200/204 success, 404 not-found, 400 invalid input. Full workflow: create map→add root→add children→move node→get tree→verify hierarchy. (covers: AC-11)

---

## PHASE 2 — AI Integration (Goal: generate, expand, regroup from session data)

### 2A — AI Backend

- [ ] **2.1** `src/schemas/mindmap_schemas.py` — add `MindMapAITree` Pydantic model: `{title, central_node:AINode, children:list[AINode]}`, `AINode{title,description?,node_type,children?:list[AINode]}`. (covers: AC-7)
- [ ] **2.2** `src/services/mindmap_ai.py` [NEW] — depends on `src.llm.ollama_client`:
  - `generate_map_from_session(db, session_id, project_id)→str`: load `Session.state`→extract brainstorm content→build prompt with schema→call Ollama→validate against `MindMapAITree`→retry once on failure→persist as new map→return map_id. On double failure return `{"error":"schema_validation_failed","issues":[...]}`.
  - `expand_node(db, node_id)→list[MindMapNode]`: get node context→prompt "3-8 child ideas"→validate→create rows→return.
  - `regroup_map(db, map_id)→RegroupPreview`: serialize tree→prompt "reorganize"→validate→return `{proposed_tree,changes_summary}`. Does NOT persist.
  - `apply_regroup(db, map_id, proposed_tree)`: delete existing nodes→recreate from proposal→save pre-regroup snapshot. (covers: AC-7)
- [ ] **2.3** `src/api/mindmap_routes.py` — add AI endpoints:
  - `POST /ai/generate-from-session/{session_id}`→`{map_id}`
  - `POST /ai/expand-node/{node_id}`→`[MindMapNode]`
  - `POST /ai/regroup/{map_id}`→`RegroupPreview`(does not modify)
  - `POST /ai/regroup/{map_id}/apply`→updated `MapTree`
  - `GET /ai/schema`→JSON Schema for frontend reference (covers: AC-7)

### 2B — AI Frontend

- [ ] **2.4** `tauri-app/src/features/mindmap/api.ts` — add: `generateMapFromSession`, `expandNode`, `regroupMap`, `applyRegroup`. (covers: AC-7)
- [ ] **2.5** `tauri-app/src/features/mindmap/components/MapToolbar.tsx` — add buttons(visible when `sessionId`): "Generate from Session"(spinner→switch map), "Expand"(visible when node selected, spinner→append children), "Regroup"(opens preview modal). (covers: AC-7)
- [ ] **2.6** `tauri-app/src/features/mindmap/components/RegroupPreview.tsx` [NEW] — modal: summary("moved X, renamed Y, added Z"), Accept(apply+refresh), Reject(close). Guard text: "Manual edits will be replaced. Snapshot saved automatically." (covers: AC-7)
- [ ] **2.7** `tauri-app/src/features/mindmap/store.ts` — add actions: `generateFromSession`, `expandSelectedNode`, `regroupPreview`, `applyRegroup`. (covers: AC-7)

### 2C — Tests

- [ ] **2.8** `tests/test_mindmap_ai.py` [NEW] — mock `OllamaClient.generate` with controlled JSON:
  - `test_ai_schema_validation_valid` — valid `MindMapAITree`→parsed
  - `test_ai_schema_validation_invalid` — missing `title`→`ValidationError`
  - `test_ai_schema_validation_malformed_json` — `{invalid`→graceful error
  - `test_generate_map_from_session` — mock session+LLM→verify map with correct hierarchy
  - `test_expand_node` — mock 5 children→verify created under parent
  - `test_regroup_preview_does_not_persist` — preview returned, map unchanged in DB
  - `test_apply_regroup_replaces_tree` — old nodes deleted, new match proposal
  - `test_regroup_saves_snapshot` — pre-regroup snapshot exists after apply (covers: AC-11)

---

## PHASE 3 — Export/Import + Polish

### 3A — Export/Import Backend

- [ ] **3.1** `src/services/mindmap_export.py` [NEW]:
  - `export_json(db,map_id)→dict` — serialize as `{map,nodes:[...recursive],edges}`(round-trip format)
  - `export_markdown(db,map_id)→str` — recursive indent: `# Central\n## Child\n### Grandchild\n- Edge: related to X`
  - `import_json(db,project_id,data)→MindMap` — validate against `MindMapExportSchema`, create map+nodes+edges, return map_id. Field-level errors on failure. (covers: AC-10)
- [ ] **3.2** `src/api/mindmap_routes.py` — add: `GET /map/{map_id}/export/json`, `GET /map/{map_id}/export/markdown`, `POST /import/{project_id}`. (covers: AC-10)

### 3B — Export/Import Frontend

- [ ] **3.3** `tauri-app/src/features/mindmap/api.ts` — add: `exportJson→Blob`, `exportMarkdown→string`, `exportPng→Blob`(React Flow `toPng()`), `exportSvg→Blob`(React Flow `toSvg()`), `importJson(projectId,file)→MindMap`. (covers: AC-10)
- [ ] **3.4** `tauri-app/src/features/mindmap/components/MapToolbar.tsx` — add Export dropdown(JSON/Markdown/PNG/SVG)→browser download. Import button→file picker(`accept=".json"`)→validate→toast success/error. (covers: AC-10)

### 3C — Polish

- [ ] **3.5** `tauri-app/src/features/mindmap/components/NodeInspector.tsx` — add "Duplicate" button→`store.duplicateNode`. (covers: AC-3)
- [ ] **3.6** `tauri-app/src/features/mindmap/components/MindMapCanvas.tsx` — enable `onConnect` for cross-branch edges(dashed). Right-click context menu: Duplicate, Delete. Edge click+Delete to remove. (covers: AC-3)
- [ ] **3.7** `tauri-app/src/features/mindmap/MindMapWorkspace.tsx` — add `Spinner` while loading tree. Add overlay spinner during AI generation/regroup. (covers: AC-6)
- [ ] **3.8** `tauri-app/src/features/mindmap/components/MindMapErrorBoundary.tsx` [NEW] — React error boundary. On crash: "Something went wrong" + "Reload" button(re-fetch tree). Does not crash host page. (covers: AC-6)
- [ ] **3.9** All mindmap components — a11y pass: `aria-label` on interactive elements, arrow-key canvas nav(React Flow built-in), icon+label for node types(not color alone), `prefers-reduced-motion`→disable animations, focus management(select→inspector, Escape→canvas), `aria-live` for undo/redo announcements. (covers: AC-5, AC-6)
- [ ] **3.10** `mind_map_nodes.metadata` — add optional `source_brainstorm_item_id` field. AI generation populates when source IDs exist. `NodeInspector` shows "Source: brainstorm item X" link. Best-effort, not an error if missing. (covers: AC-1)

### 3D — Tests

- [ ] **3.11** `tests/test_mindmap_export.py` [NEW]:
  - `test_export_json_roundtrip` — create→export→import→assert identical
  - `test_export_markdown_format` — valid Markdown with correct indent
  - `test_import_invalid_json` — `ValidationError` with field message
  - `test_import_missing_required_field` — JSON without `nodes`→explicit error
  - `test_import_cycle_in_json` — self-referencing parent→rejected
  - `test_export_empty_map` — root-only→valid output (covers: AC-11)
- [ ] **3.12** `tests/test_mindmap_ui_states.py` [NEW]:
  - Undo/redo stack: push 3→undo×2→assert tree at snapshot 1→redo×1→assert at snapshot 2
  - Dirty flag: modify→assert dirty=true; save→assert dirty=false (covers: AC-11)

---

## Pre-Mortem

### 🐯 Tigers (act on these)

| # | Risk | Severity | Mitigation | When |
|---|------|----------|------------|------|
| T1 | React Flow lag with 200+ nodes | Launch-Blocking | `React.memo` on custom nodes, benchmark 300 nodes on mid-range laptop, collapse-all default if >500ms | Before Phase 1 ship |
| T2 | Ollama JSON hallucination (10% fail rate) | Launch-Blocking | Two-pass: first `format="json"` + strict schema; second "fix this JSON to match schema"; on double fail show retry button | Before Phase 2 ship |
| T3 | Drag+autosave race condition | Launch-Blocking | Backend is single source of truth for cycle check. On 400 error: revert local state + toast. `isMoving` lock in store | Before Phase 1 ship |

### 📄 Paper Tigers (document, don't worry)

- "SQLite can't handle concurrency" → single-user app, WAL mode active
- "React Flow is overkill for trees" → pan/zoom/drag/minimap/export all needed anyway
- "Zustand adds bloat" → ~1KB gzipped, worth it over useContext prop drilling

### 🐘 Elephants (investigate before committing)

- **Session.state JSON shape varies** (wizard vs YOLO). Before Phase 2: document both shapes, create separate extraction functions if too different.
- **Missing shared UI components** (Select, Textarea, ColorPicker). Check if they exist; if not, add to `ui.tsx` before Phase 1 frontend work.
- **Tauri IPC latency** for frequent small calls. During Phase 1: measure `PATCH /nodes/{id}` RTT; if >100ms, batch inspector updates.

---

## Sequencing (by RICE)

| Order | Step Group | Why First |
|-------|-----------|-----------|
| 1 | 1A Dependencies | Everything depends on `@xyflow/react` + `zustand` |
| 2 | 1B Database | Backend and tests need tables to exist |
| 3 | 1C Schemas + Service | API routes call service functions |
| 4 | 1D API Routes | Frontend API client calls these endpoints |
| 5 | 1E Frontend Foundation | Types→API client→Store→Hooks (strict order) |
| 6 | 1F Components | Canvas first (visual feedback), then inspector+toolbar |
| 7 | 1G Integration | Wire into Wizard + AppShell after components work |
| 8 | 1H Tests | Write alongside, finalize after integration verified |
| 9 | Phase 2 | Depends on Phase 1 CRUD API being stable |
| 10 | Phase 3 | Depends on Phase 1+2, mostly additive |

### Deferred (Won't in MoSCoW)

- Real-time collaboration (single-user app)
- Version history beyond undo/redo stack
- Custom themes per node type beyond color+icon
- Mobile responsive (Tauri desktop app)
- Mind map template library
- Export to OPML/FreeMind (JSON+Markdown covers 90%)
- Node comments/attachments
- Search within mind map
- Print layout

---

## Files inventory

### New files (28)

| File | Phase |
|------|-------|
| `src/db/mindmap_models.py` | P1 |
| `src/schemas/__init__.py` | P1 |
| `src/schemas/mindmap_schemas.py` | P1 |
| `src/services/__init__.py` | P1 |
| `src/services/mindmap_service.py` | P1 |
| `src/api/mindmap_routes.py` | P1 |
| `tauri-app/src/features/mindmap/index.ts` | P1 |
| `tauri-app/src/features/mindmap/MindMapWorkspace.tsx` | P1 |
| `tauri-app/src/features/mindmap/store.ts` | P1 |
| `tauri-app/src/features/mindmap/types.ts` | P1 |
| `tauri-app/src/features/mindmap/api.ts` | P1 |
| `tauri-app/src/features/mindmap/hooks/useMindMap.ts` | P1 |
| `tauri-app/src/features/mindmap/hooks/useUndoRedo.ts` | P1 |
| `tauri-app/src/features/mindmap/hooks/useAutoSave.ts` | P1 |
| `tauri-app/src/features/mindmap/components/EmptyState.tsx` | P1 |
| `tauri-app/src/features/mindmap/components/MindMapNode.tsx` | P1 |
| `tauri-app/src/features/mindmap/components/MindMapEdge.tsx` | P1 |
| `tauri-app/src/features/mindmap/components/MindMapCanvas.tsx` | P1 |
| `tauri-app/src/features/mindmap/components/NodeInspector.tsx` | P1 |
| `tauri-app/src/features/mindmap/components/MapToolbar.tsx` | P1 |
| `tauri-app/src/pages/MindMapPage.tsx` | P1 |
| `src/services/mindmap_ai.py` | P2 |
| `tauri-app/src/features/mindmap/components/RegroupPreview.tsx` | P2 |
| `src/services/mindmap_export.py` | P3 |
| `tauri-app/src/features/mindmap/components/MindMapErrorBoundary.tsx` | P3 |
| `tests/test_mindmap_crud.py` | P1 |
| `tests/test_mindmap_api.py` | P1 |
| `tests/test_mindmap_ai.py` | P2 |
| `tests/test_mindmap_export.py` | P3 |
| `tests/test_mindmap_ui_states.py` | P3 |

### Modified files (6)

| File | Change | Phase |
|------|--------|-------|
| `tauri-app/package.json` | Add `@xyflow/react`, `zustand` | P1 |
| `pyproject.toml` | Add `jsonschema` | P1 |
| `src/db/schema.py` | Import mindmap models | P1 |
| `src/main.py` | Register mindmap router | P1 |
| `tauri-app/src/pages/Wizard.tsx` | Add Mind Map tab | P1 |
| `tauri-app/src/components/AppShell.tsx` | Add nav entry | P1 |
| `tauri-app/src/App.tsx` | Add `/mindmap` route | P1 |

---

## Acceptance criteria map

| AC | Description | Verified by steps |
|----|-------------|-------------------|
| AC-1 | Mind Map tab in Brainstorming stage | 1.21, 1.22, 1.23, 1.24, 1.25, 3.10 |
| AC-2 | Map CRUD + persistence | 1.5, 1.6, 1.7, 1.8, 1.10, 1.11, 1.12, 1.20 |
| AC-3 | Node CRUD + drag/drop/reparent/collapse | 1.5, 1.6, 1.7, 1.10, 1.11, 1.12, 1.16, 1.17, 1.18, 1.19, 1.20, 3.5, 3.6 |
| AC-4 | Keyboard shortcuts | 1.13, 1.18 |
| AC-5 | Node types with icon+label | 1.9, 1.16, 1.19, 3.9 |
| AC-6 | Canvas UX + empty states + toolbar | 1.15, 1.16, 1.18, 1.19, 1.20, 3.7, 3.8, 3.9 |
| AC-7 | AI generation/expand/regroup | 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7 |
| AC-8 | Data integrity (no orphans, cycles, cascade) | 1.3, 1.4, 1.5, 1.6, 1.7 |
| AC-9 | Undo/redo + autosave | 1.5, 1.6, 1.7, 1.11, 1.13, 1.14, 1.20 |
| AC-10 | Export/import | 3.1, 3.2, 3.3, 3.4 |
| AC-11 | Tests | 1.26, 1.27, 2.8, 3.11, 3.12 |

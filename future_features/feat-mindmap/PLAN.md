
# Implementation Plan: Interactive Mind Mapping for Brainstorming

## Summary

Add a self-contained mind-map sub-application to Dobby's Brainstorming stage across three sequenced phases. Phase 1 delivers a working canvas editor with full CRUD and persistence (no AI). Phase 2 adds AI generation/expansion/regrouping from wizard/YOLO session data. Phase 3 adds export/import and production polish.

## Architecture: App-Inside-App

Backend: `src/api/mindmap_routes.py` (router under `/api/v1/mindmaps`), `src/db/mindmap_models.py` (SQLAlchemy ORM), `src/services/mindmap_service.py` (CRUD + validation), `src/services/mindmap_ai.py` (AI pipeline). Frontend: `tauri-app/src/features/mindmap/` with Zustand store, React Flow canvas, isolated from other feature dirs.

## Steps

### Phase 1 — Core CRUD + Canvas

- [ ] **1.1 — Install dependencies** — Add `@xyflow/react` and `zustand` to `tauri-app/package.json`. Run `npm install` in `tauri-app/`. Add `jsonschema` to `pyproject.toml` dev dependencies (used for AI output validation in Phase 2, cheap to add now).

- [ ] **1.2 — Create SQLAlchemy models** — New file `src/db/mindmap_models.py`. Define `MindMap`, `MindMapNode`, `MindMapEdge`, `MindMapSnapshot` ORM classes following existing conventions: `Base = declarative_base()` from `src.db.schema`, String UUID PKs, `metadata` JSON columns with `extra_metadata` attribute aliases, `created_at`/`updated_at` with `datetime.utcnow` defaults. Foreign keys: `project_id` → `projects.id` (CASCADE), `session_id` → `sessions.id` (SET NULL), `mind_map_id` → `mind_maps.id` (CASCADE for nodes/edges/snapshots), `parent_id` → `mind_map_nodes.id` (SET NULL). Indexes on `(mind_map_id)`, `(project_id)`, `(parent_id)`, `(mind_map_id, created_at)`. Use a separate `Base` or import the existing one? Decision: import `Base` from `src.db.schema` so `create_all` picks up new tables. (covers: AC-8)

- [ ] **1.3 — Register models with database init** — In `src/db/schema.py`, import the mindmap models after `Base` definition so `Base.metadata.create_all` creates their tables. Add an `__init__.py` to `src/services/` (new directory). (covers: AC-8)

- [ ] **1.4 — Create Pydantic schemas** — New file `src/schemas/mindmap_schemas.py` (new directory `src/schemas/` with `__init__.py`). Define request/response models: `MindMapCreate`, `MindMapResponse`, `MindMapUpdate`, `MindMapListResponse`, `NodeCreate`, `NodeResponse`, `NodeUpdate`, `NodeMoveRequest` (target parent + sort order), `EdgeCreate`, `EdgeResponse`, `SnapshotSave`, `SnapshotResponse`, `TreeValidationError`. Use existing patterns: `BaseModel`, `Optional` fields, `Field` defaults. Include a `MindMapExportSchema` for the full tree serialization format (map + all nodes + edges). (covers: AC-2, AC-3, AC-8)

- [ ] **1.5 — Implement service layer** — New file `src/services/mindmap_service.py`. Core functions (each takes `db: DatabaseManager`):
  - `create_map(db, project_id, title, session_id=None) → MindMap`
  - `get_map(db, map_id) → MindMap`
  - `list_maps(db, project_id) → list[MindMap]`
  - `update_map(db, map_id, title=None, root_node_id=None, viewport_state=None) → MindMap`
  - `duplicate_map(db, map_id) → MindMap` — deep-copy all nodes/edges, assign new IDs
  - `delete_map(db, map_id)` — cascading, does not touch brainstorm content
  - `create_node(db, map_id, parent_id, title, node_type="Idea", **kwargs) → MindMapNode`
  - `get_node(db, node_id) → MindMapNode`
  - `update_node(db, node_id, **kwargs) → MindMapNode`
  - `move_node(db, node_id, new_parent_id, new_sort_order) → MindMapNode` — with cycle detection
  - `delete_node(db, node_id)` — recursive descendant deletion after confirmation check
  - `duplicate_node(db, node_id) → MindMapNode` — deep-copy with descendants
  - `get_map_tree(db, map_id) → dict` — returns nested JSON: `{map, nodes: [{...children: [...]}]}`
  - `create_edge(db, map_id, source_id, target_id, relation_type="related") → MindMapEdge`
  - `delete_edge(db, edge_id)`
  - `save_snapshot(db, map_id, snapshot_json, label) → MindMapSnapshot`
  - `get_snapshots(db, map_id, limit=50) → list[MindMapSnapshot]`
  - `validate_tree(db, map_id) → list[TreeValidationError]` — checks: orphan nodes, invalid parent refs, cycles, root node rules
  - `reorder_siblings(db, parent_id, ordered_child_ids: list[str])` — bulk updates sort_order
  Include a `_detect_cycle(node_id, proposed_parent_id, db)` helper: walk up from proposed parent; if node_id appears in ancestor chain, cycle exists. (covers: AC-2, AC-3, AC-8, AC-9)

- [ ] **1.6 — Create API routes** — New file `src/api/mindmap_routes.py`. Router at prefix `/api/v1/mindmaps` (handled in `main.py` registration, not in-file). Endpoints:
  - `POST /` — create map
  - `GET /{project_id}` — list maps for project
  - `GET /map/{map_id}` — get single map
  - `PATCH /map/{map_id}` — update map (title, viewport)
  - `POST /map/{map_id}/duplicate` — duplicate map
  - `DELETE /map/{map_id}` — delete map (with confirmation)
  - `POST /map/{map_id}/nodes` — create node
  - `GET /nodes/{node_id}` — get node
  - `PATCH /nodes/{node_id}` — update node
  - `PUT /nodes/{node_id}/move` — move/reparent node (body: `{new_parent_id, sort_order}`)
  - `DELETE /nodes/{node_id}` — delete node + descendants
  - `POST /nodes/{node_id}/duplicate` — duplicate node
  - `GET /map/{map_id}/tree` — get full tree for canvas rendering
  - `POST /map/{map_id}/edges` — create edge
  - `DELETE /edges/{edge_id}` — delete edge
  - `POST /map/{map_id}/snapshots` — save snapshot
  - `GET /map/{map_id}/snapshots` — list snapshots
  - `POST /map/{map_id}/validate` — validate tree integrity
  Define a local `get_db()` like the other route modules (`from src.main import app; return app.state.db`) — there is no `get_db` in `src.main`. Return JSON responses with consistent error shape: `{"error": "error_code", "message": "...", "detail": {}}`. (covers: AC-2, AC-3, AC-8, AC-9)

- [ ] **1.7 — Register routes in main.py** — In `src/main.py`, add: `from src.api.mindmap_routes import router as mindmap_router` then `app.include_router(mindmap_router, prefix="/api/v1")`. Remove the prefix from the router definition if it duplicates. (covers: AC-2)

- [ ] **1.8 — Create frontend types** — New file `tauri-app/src/features/mindmap/types.ts`. TypeScript interfaces:
  - `MindMap`: `{ id, project_id, session_id, title, root_node_id, viewport_state, created_at, updated_at }`
  - `MindMapNode`: `{ id, mind_map_id, project_id, parent_id, title, description, node_type, color, sort_order, metadata, created_at, updated_at }`
  - `NodeType`: union of `'Idea' | 'Problem' | 'Opportunity' | 'Feature' | 'Risk' | 'Assumption' | 'Research Question' | 'Action Item' | 'Decision'`
  - `MindMapEdge`: `{ id, mind_map_id, source_node_id, target_node_id, relation_type, created_at }`
  - `MapTree`: `{ map: MindMap, nodes: TreeNode[] }` where `TreeNode extends MindMapNode { children: TreeNode[] }`
  - `ViewportState`: `{ x: number, y: number, zoom: number }`
  - `UndoEntry`: `{ snapshot: MapTree, label: string }`
  - `NodePosition`: `{ x: number, y: number }` (stored in node.metadata) (covers: AC-5)

- [ ] **1.9 — Create frontend API client** — New file `tauri-app/src/features/mindmap/api.ts`. Functions following existing `client.ts` DUAL-TRANSPORT pattern (isTauri() ? invoke : fetch to http://localhost:8000/api/v1/mindmaps — NOT axios):
  - `createMap(projectId, title, sessionId?) → MindMap`
  - `listMaps(projectId) → MindMap[]`
  - `getMap(mapId) → MindMap`
  - `updateMap(mapId, data) → MindMap`
  - `duplicateMap(mapId) → MindMap`
  - `deleteMap(mapId) → void`
  - `createNode(mapId, parentId, data) → MindMapNode`
  - `getNode(nodeId) → MindMapNode`
  - `updateNode(nodeId, data) → MindMapNode`
  - `moveNode(nodeId, newParentId, sortOrder) → MindMapNode`
  - `deleteNode(nodeId) → void`
  - `duplicateNode(nodeId) → MindMapNode`
  - `getMapTree(mapId) → MapTree`
  - `createEdge(mapId, sourceId, targetId, relationType?) → MindMapEdge`
  - `deleteEdge(edgeId) → void`
  - `saveSnapshot(mapId, snapshot, label) → void`
  - `listSnapshots(mapId) → Snapshot[]`
  - `validateTree(mapId) → ValidationError[]` (covers: AC-2, AC-3)

- [ ] **1.10 — Create Zustand store** — New file `tauri-app/src/features/mindmap/store.ts`. Store shape:
  - `maps: MindMap[]`, `activeMapId: string | null`, `tree: MapTree | null`, `selectedNodeId: string | null`
  - `undoStack: UndoEntry[]`, `redoStack: UndoEntry[]` (max 50 each)
  - `isDirty: boolean`, `isSaving: boolean`, `lastSaved: Date | null`
  - `isLoading: boolean`, `error: string | null`
  - Actions: `loadMaps`, `selectMap`, `createMap`, `updateMap`, `deleteMap`, `duplicateMap`, `addNode`, `updateNode`, `moveNode`, `deleteNode`, `duplicateNode`, `addEdge`, `deleteEdge`, `selectNode`, `pushUndo` (auto-called before mutating actions), `undo`, `redo`, `setViewport`, `expandAll`, `collapseAll`
  - The `pushUndo` action snapshots the current `tree` before any mutation. Called internally by mutating actions (createNode, updateNode, moveNode, deleteNode, addEdge, deleteEdge) after they succeed on the backend but before updating local state. (covers: AC-2, AC-3, AC-9)

- [ ] **1.11 — Create useMindMap hook** — New file `tauri-app/src/features/mindmap/hooks/useMindMap.ts`. Wraps store + API calls. Exports `useMindMap()` returning `{ maps, activeMap, tree, selectedNode, selectMap, createMap, ... }`. Handles loading states, error boundaries, optimistic updates where safe (e.g., node title edit can be optimistic). (covers: AC-2, AC-3)

- [ ] **1.12 — Create useUndoRedo hook** — New file `tauri-app/src/features/mindmap/hooks/useUndoRedo.ts`. Keybindings: Ctrl+Z / Cmd+Z for undo, Ctrl+Shift+Z / Cmd+Shift+Z for redo. Listens on `document` for keydown, checks `activeMapId !== null`. Calls `store.undo()` / `store.redo()`. (covers: AC-4, AC-9)

- [ ] **1.13 — Create useAutoSave hook** — New file `tauri-app/src/features/mindmap/hooks/useAutoSave.ts`. Watches `isDirty` flag. On change, debounces 2 seconds, then calls `api.updateMap` and `api.getMapTree` to persist current state. Sets `isSaving` true during save, updates `lastSaved` on completion. Shows "Saving..." / "Saved" indicator in UI. Auto-saves viewport state too. (covers: AC-9)

- [ ] **1.14 — Create EmptyState component** — New file `tauri-app/src/features/mindmap/components/EmptyState.tsx`. Two variants: "no maps yet" (when `maps.length === 0`) showing a prompt to create a new map, and "empty map" (map exists but has no nodes) showing a prompt to add a root node. Uses shared `Card`, `Button` from `src/components/ui.tsx`. (covers: AC-6)

- [ ] **1.15 — Create custom node component for React Flow** — New file `tauri-app/src/features/mindmap/components/MindMapNode.tsx`. A React Flow custom node (`Handle` + styled card). Shows: title (editable on double-click), node type icon + label, color indicator (left border in node color). Each node type maps to an SVG icon from the shared icon set (`src/lib/icons.ts` — add new icons if missing). Node visual: rounded card with `border-l-4` colored strip, title in `font-semibold text-sm`, type badge below. Selection ring on focus. `Handle` positions: top (target), bottom (source) for parent-child; left/right for cross-branch edges. (covers: AC-3, AC-5, AC-6)

- [ ] **1.16 — Create custom edge component** — New file `tauri-app/src/features/mindmap/components/MindMapEdge.tsx`. Smooth step or bezier edge with optional label for relation type. Default color from Tailwind `border-line`. Distinct styling for cross-branch edges (dashed). (covers: AC-3)

- [ ] **1.17 — Create MindMapCanvas component** — New file `tauri-app/src/features/mindmap/components/MindMapCanvas.tsx`. Wraps React Flow's `<ReactFlow>`:
  - Props: none (reads from store via hook)
  - Converts `MapTree` to React Flow `nodes[]` and `edges[]` using dagre (bundled with `@xyflow/react`) for auto-layout on first render
  - `nodeTypes={{ mindmap: MindMapNode }}`, `edgeTypes={{ mindmap: MindMapEdge }}`
  - Controls: `<Controls>`, `<MiniMap>`, `<Background>` from `@xyflow/react`
  - `fitView` on map load, `fitViewOptions={{ padding: 0.2 }}`
  - `onNodeClick` → `store.selectNode(nodeId)`
  - `onConnect` → `store.addEdge(source, target)` — only for cross-branch edges; parent-child uses `moveNode`
  - `onNodeDragStop` → update position in node metadata, mark dirty
  - `onNodesChange` / `onEdgesChange` → applyChanges from React Flow
  - Keyboard handlers: Enter (add sibling to selected), Tab (add child to selected), Delete/Backspace (confirm then delete selected), Escape (deselect)
  - Pan/zoom: default React Flow behavior, fit-to-screen button in toolbar
  - Collapse/expand: use React Flow's `expandParent`/`collapseNode` or track `hidden` state — simpler: toggle `hidden` on children, use `getNodesBounds` to fit. (covers: AC-3, AC-4, AC-6)

- [ ] **1.18 — Create NodeInspector component** — New file `tauri-app/src/features/mindmap/components/NodeInspector.tsx`. Right-side panel (or bottom sheet on mobile). Shows when a node is selected. Editable fields:
  - Title (`input`, auto-focused)
  - Description (`textarea`, 3 rows)
  - Node type (`select` dropdown with all 9 types)
  - Color (`input[type=color]` or preset swatches)
  - Priority (1-5, radio group or select)
  - Status (draft / in-progress / done, select)
  - Metadata display: created/updated timestamps, node ID (copyable)
  - Save on blur with debounce. Shows "Unsaved changes" indicator. (covers: AC-3, AC-5, AC-6)

- [ ] **1.19 — Create MapToolbar component** — New file `tauri-app/src/features/mindmap/components/MapToolbar.tsx`. Horizontal bar above canvas with:
  - Map selector: dropdown listing all maps for this project, "New Map" button
  - Map title: editable inline, rename on blur
  - Action buttons (icon + tooltip): Add Node (root if none selected, sibling if selected), Auto Layout (re-run dagre), Undo, Redo, Expand All, Collapse All, Fit to Screen, Validate Tree, Delete Map (with confirmation dialog using shared `Modal`)
  - Save state indicator: "Saved" (green) / "Saving..." (spinner) / "Unsaved changes" (yellow dot)
  - Duplicate Map button
  Uses shared `Button`, `Modal` from `src/components/ui.tsx`. (covers: AC-2, AC-3, AC-6, AC-9)

- [ ] **1.20 — Create MindMapWorkspace entry point** — New file `tauri-app/src/features/mindmap/MindMapWorkspace.tsx`. Top-level component mounted by the brainstorming stage. Accepts props: `projectId: string`, `sessionId?: string`. Layout: Toolbar on top, Canvas filling remaining space, Inspector as slide-out panel (absolute positioned right, 320px, with close button). On mount: loads maps for project, auto-selects first or creates new if none. (covers: AC-1)

- [ ] **1.21 — Create index.ts barrel export** — New file `tauri-app/src/features/mindmap/index.ts`. Exports only `MindMapWorkspace` and `types.ts` types needed by consumers. Nothing else leaks. (covers: AC-1)

- [ ] **1.22 — Integrate into Wizard page** — In `tauri-app/src/pages/Wizard.tsx`, add a tab/toggle bar below the header: "Outline" (current text view) | "Mind Map". When "Mind Map" is active and `sessionId` exists, render `<MindMapWorkspace projectId="default-project" sessionId={sessionId} />`. Add the import. (covers: AC-1)

- [ ] **1.23 — Add mind map nav entry** — In `tauri-app/src/components/AppShell.tsx`, add a "Mind Map" nav item (optional, for direct access outside wizard). Route: `/mindmap`. Icon: a mind-map/branching icon. Update `App.tsx` accordingly. This is a convenience, not blocking integration. (covers: AC-1)

- [ ] **1.24 — Write Phase 1 backend tests** — New file `tests/test_mindmap_crud.py`. Test class `TestMindMapCRUD`:
  - `test_create_map`: creates map via service, asserts fields
  - `test_list_maps`: creates 3 maps, lists, asserts count
  - `test_delete_map_cascades`: create map + 5 nodes + 2 edges, delete map, assert all gone
  - `test_delete_map_preserves_brainstorm`: create map, verify session/node data untouched
  - `test_duplicate_map_deep`: create map with nodes, duplicate, assert new IDs, same structure
  - `test_create_node`: create root, child, sibling, verify parent chain
  - `test_move_node`: move node to new parent, verify hierarchy
  - `test_move_node_cycle_prevention`: try to make a node its own ancestor, assert error
  - `test_delete_node_cascades`: delete parent, assert children gone
  - `test_reorder_siblings`: reorder 3 siblings, assert sort_order values
  - `test_validate_tree_clean`: valid tree, assert no errors
  - `test_validate_tree_orphan`: create node with invalid parent_id, assert error
  - `test_validate_tree_cycle`: create cycle via direct parent manipulation, assert error
  - `test_snapshot_save_list`: save 3 snapshots, list, assert order
  - `test_edge_crud`: create edge, assert it exists, delete, assert gone
  Use existing `@pytest.fixture` pattern with `/tmp/dobby_test_{uuid}.db`. Import `DatabaseManager` from `src.db.schema` and service functions from `src.services.mindmap_service`. (covers: AC-11)

- [ ] **1.25 — Write Phase 1 API integration tests** — New file `tests/test_mindmap_api.py`. Use `fastapi.testclient.TestClient` against the app. Test each endpoint: create (201), get (200), list (200, array), update (200), delete (204), move (200), duplicate (201), validate (200, error list). Test error cases: not-found (404), invalid move (400 with cycle explanation), delete nonexistent (404). Include a full workflow: create map → add root → add children → move node → get tree → verify hierarchy. (covers: AC-11)

### Phase 2 — AI Integration

- [ ] **2.1 — Define AI output schema** — In `src/schemas/mindmap_schemas.py`, add `MindMapAITree` (Pydantic model): `{ title: str, central_node: AINode, children: list[AINode] }` where `AINode { title: str, description?: str, node_type: str, children?: list[AINode] }`. This is the contract LLM output must conform to. (covers: AC-7)

- [ ] **2.2 — Implement AI transformation service** — New file `src/services/mindmap_ai.py`. Functions:
  - `generate_map_from_session(db, session_id, project_id) → str` (returns new map_id):
    1. Load `Session.state` JSON
    2. Extract structured brainstorm content: feature spec categories, ideas, risks, opportunities from session state
    3. Build prompt: "You are a mind map expert. Given this brainstorm content, generate a mind map tree in JSON format. Central node is the project title. First-level nodes are themes. Child nodes are specific ideas..." Include the Pydantic schema in the prompt
    4. Call `ollama_client.generate(prompt)` with `format="json"` if supported
    5. Parse and validate against `MindMapAITree`
    6. On validation failure: retry once, then return structured error (`{"error": "schema_validation_failed", "issues": [...]}`) for frontend to display
    7. On success: persist as a new mind map with all nodes, return map_id
  - `expand_node(db, node_id) → list[MindMapNode]`:
    1. Get node context: title, type, sibling names, parent name
    2. Build prompt: "Generate 3-8 child ideas for this node..."
    3. Parse, validate each as `AINode`, create `MindMapNode` rows, return them
  - `regroup_map(db, map_id) → RegroupPreview`:
    1. Serialize current map tree as JSON
    2. Build prompt: "Reorganize this mind map for better clarity. Suggest regrouping, renaming, or restructuring. Return a proposed tree..."
    3. Parse, validate against `MindMapAITree`, return as `RegroupPreview { proposed_tree, changes_summary: str }`
    4. Do NOT persist — caller decides accept/reject
  - `apply_regroup(db, map_id, proposed_tree)`:
    1. Delete all existing nodes for map_id
    2. Recreate from proposed_tree
    3. Save snapshot of pre-regroup state for undo
  Uses existing `get_ollama_client()` from `src.llm.ollama_client`. (covers: AC-7)

- [ ] **2.3 — Add AI API endpoints** — In `src/api/mindmap_routes.py`, add:
  - `POST /ai/generate-from-session/{session_id}` — calls `generate_map_from_session`, returns `{ map_id }`
  - `POST /ai/expand-node/{node_id}` — calls `expand_node`, returns list of created nodes
  - `POST /ai/regroup/{map_id}` — calls `regroup_map`, returns preview (does not modify)
  - `POST /ai/regroup/{map_id}/apply` — calls `apply_regroup`, returns updated map tree
  - `GET /ai/schema` — returns the `MindMapAITree` JSON Schema for frontend reference (covers: AC-7)

- [ ] **2.4 — Add frontend API functions** — In `tauri-app/src/features/mindmap/api.ts`, add:
  - `generateMapFromSession(sessionId, projectId) → { map_id: string }`
  - `expandNode(nodeId) → MindMapNode[]`
  - `regroupMap(mapId) → RegroupPreview`
  - `applyRegroup(mapId) → MapTree` (covers: AC-7)

- [ ] **2.5 — Add AI actions to MapToolbar** — In `MapToolbar.tsx`, add buttons (conditionally shown when `sessionId` is available):
  - "Generate from Session" — calls `generateMapFromSession`, switches to new map on success, shows error toast on failure
  - "Expand" (visible when node selected) — calls `expandNode`, appends children to tree, shows spinner while generating
  - "Regroup" — calls `regroupMap`, opens a diff/preview modal showing proposed changes with "Accept" / "Reject" buttons
  All buttons show loading spinners during AI calls. Errors display as toast notifications. (covers: AC-7)

- [ ] **2.6 — Add regroup preview modal** — New file `tauri-app/src/features/mindmap/components/RegroupPreview.tsx`. Modal showing:
  - Side-by-side or summarized diff of current vs proposed tree
  - "Changes: moved X nodes, renamed Y nodes, added Z branches" summary
  - "Accept" button (calls `applyRegroup`, then refreshes canvas)
  - "Reject" button (closes modal, nothing persisted)
  - Guard text: "Your manual edits will be replaced. A snapshot is saved automatically." (covers: AC-7)

- [ ] **2.7 — Write Phase 2 tests** — New file `tests/test_mindmap_ai.py`:
  - `test_ai_schema_validation_valid`: mock LLM returns valid `MindMapAITree` JSON, assert parsed correctly
  - `test_ai_schema_validation_invalid`: mock LLM returns missing `title` field, assert `ValidationError` raised with message
  - `test_ai_schema_validation_malformed_json`: mock LLM returns `{invalid`, assert graceful error
  - `test_generate_map_from_session`: mock session with known state, mock LLM response, verify map created with correct node count and hierarchy
  - `test_expand_node`: mock LLM returns 5 child nodes, verify they're created under correct parent
  - `test_regroup_preview_does_not_persist`: call regroup, verify preview returned but map unchanged in DB
  - `test_apply_regroup_replaces_tree`: call regroup then apply, verify old nodes deleted, new nodes match proposed
  - `test_regroup_saves_snapshot`: apply regroup, verify snapshot exists with pre-regroup state
  Use `unittest.mock` to patch `OllamaClient.generate` with fixture that returns controlled JSON. (covers: AC-11)

### Phase 3 — Export/Import + Polish

- [ ] **3.1 — Implement export service** — New file `src/services/mindmap_export.py`. Functions:
  - `export_json(db, map_id) → dict`: serialize map + tree as `{ map, nodes: [...recursive...], edges }` — this is the round-trip format
  - `export_markdown(db, map_id) → str`: recursive indent-based Markdown outline: `# Central Node\n## Child\n### Grandchild\n- Edge: related to X`
  - `export_png(db, map_id, options?) → bytes`: Not handled server-side — React Flow exports client-side. Backend provides the tree data; frontend renders then calls `reactFlowInstance.toPng()`. Document this split.
  - `export_svg(db, map_id, options?) → bytes`: Same as PNG — client-side via `reactFlowInstance.toSvg()`.
  - `import_json(db, project_id, data: dict) → MindMap`: validate structure against `MindMapExportSchema`, create map + nodes + edges, return map_id on success, raise `ValidationError` with field-level messages on failure. (covers: AC-10)

- [ ] **3.2 — Add export/import API endpoints** — In `src/api/mindmap_routes.py`, add:
  - `GET /map/{map_id}/export/json` — returns JSON response
  - `GET /map/{map_id}/export/markdown` — returns `text/markdown`
  - `POST /import/{project_id}` — accepts JSON body, returns created map (covers: AC-10)

- [ ] **3.3 — Add frontend export/import** — In `tauri-app/src/features/mindmap/api.ts`, add:
  - `exportJson(mapId) → Blob`
  - `exportMarkdown(mapId) → string`
  - `exportPng(mapId) → Blob` — triggers React Flow `toPng()` on current canvas instance, returns blob
  - `exportSvg(mapId) → Blob` — triggers React Flow `toSvg()`, returns blob
  - `importJson(projectId, file: File) → MindMap` — reads file, posts to backend
  In `MapToolbar.tsx`, add Export dropdown (JSON / Markdown / PNG / SVG) and Import button. Export triggers browser download. Import opens file picker (`input[type=file] accept=".json"`), validates, shows success/error toast. (covers: AC-10)

- [ ] **3.4 — Add node duplication UI** — In `NodeInspector.tsx`, add "Duplicate" button. In `MindMapCanvas.tsx`, add duplicate to right-click context menu. Both call `store.duplicateNode(selectedNodeId)`, which calls `api.duplicateNode` then refreshes tree. (covers: AC-3)

- [ ] **3.5 — Add cross-branch edge UI** — In `MindMapCanvas.tsx`, enable `onConnect` handler for cross-branch edges. Show a dashed line distinct from parent-child edges. Store edges in `mind_map_edges` table. Show relation type label on edge. Allow deletion via edge click + Delete key. (covers: AC-3)

- [ ] **3.6 — Link brainstorm items to map nodes** — In `mind_map_nodes.metadata`, add optional `source_brainstorm_item_id` field. During AI generation (Phase 2), if the session state JSON has identifiable item IDs, include them in the generated node metadata. In `NodeInspector`, show "Source: brainstorm item X" link if available. This is a best-effort link; missing links are not errors. (covers: AC-1)

- [ ] **3.7 — Add loading states** — In `MindMapWorkspace.tsx`, show `Spinner` (from shared UI) while initial map tree loads. In `MindMapCanvas.tsx`, show overlay spinner during AI generation/regroup. In `NodeInspector.tsx`, disable fields during save, show skeleton on first load. (covers: AC-6)

- [ ] **3.8 — Add error boundaries** — New file `tauri-app/src/features/mindmap/components/MindMapErrorBoundary.tsx`. React error boundary wrapping `MindMapCanvas`. On crash: shows "Something went wrong with the mind map" message + "Reload" button (re-fetches tree). Logs error to console. Does not crash the host brainstorming page. (covers: AC-6)

- [ ] **3.9 — Add accessibility** — Across all mind map components:
  - All interactive elements have `aria-label` or visible label
  - Keyboard navigation: arrow keys to move between nodes on canvas (React Flow built-in), Tab to cycle toolbar buttons
  - Node type colors have icon + label fallback (not color alone)
  - `prefers-reduced-motion`: disable React Flow animations, use instant transitions
  - Focus management: selecting a node moves focus to inspector; Escape returns focus to canvas
  - Screen reader announcements for undo/redo, save state changes (use `aria-live` region) (covers: AC-5, AC-6)

- [ ] **3.10 — Include mind maps in project exports** — In existing project export logic (if any), add mind map JSON alongside other project data. If no project export exists yet, add a note: this is a placeholder for when project-level export is implemented. (covers: AC-10)

- [ ] **3.11 — Write Phase 3 tests** — New file `tests/test_mindmap_export.py`:
  - `test_export_json_roundtrip`: create map with nodes, export JSON, import into new project, assert identical structure
  - `test_export_markdown_format`: verify output is valid Markdown with correct indentation
  - `test_import_invalid_json`: import malformed JSON, assert `ValidationError` with field-level message
  - `test_import_missing_required_field`: import JSON without `nodes`, assert explicit error
  - `test_import_cycle_in_json`: import JSON with self-referencing parent, assert rejected
  - `test_export_empty_map`: export map with only root node, verify valid output
  New file `tests/test_mindmap_ui_states.py` (or add to existing):
  - Test store undo/redo: push 3 snapshots, undo twice, verify tree at snapshot 1, redo once, verify at snapshot 2
  - Test store dirty flag: modify node, assert dirty=true; save, assert dirty=false (covers: AC-11)

## Pre-Mortem

### Tigers (Real risks — act on them)

| Risk | Severity | Mitigation | Owner | Decision Date |
|------|----------|------------|-------|---------------|
| **React Flow performance with 200+ nodes** — mind maps can grow large from AI expansion. React Flow handles hundreds of nodes but layout calculation + re-renders can lag on lower-end machines. | Launch-Blocking | Add `React.memo` on custom nodes. Use `nodesDraggable` / `nodesConnectable` conditionally. Benchmark with 300 nodes on a 2020-era laptop. If >500ms layout, paginate or add "collapse all by default" setting. | Dev | Before Phase 1 ship |
| **AI JSON schema non-compliance** — Ollama local models (llama3.2, mistral) often fail to produce valid JSON on first attempt, even with `format="json"`. Retry + validation is necessary but may still fail ~10% of the time. | Launch-Blocking | Implement two-pass: first pass tries `format="json"` with strict schema in prompt. On failure, second pass sends the raw output + error back to LLM: "Fix this JSON to match schema." On second failure, surface a user-friendly error with retry button. Never crash. | Dev | Before Phase 2 ship |
| **Cycle detection race condition** — drag-and-drop re-parenting + auto-save could race. User moves node, auto-save fires before cycle check completes. | Launch-Blocking | Backend `move_node` is the single source of truth for cycle validation. Frontend optimistically updates UI, backend rejects with 400 on cycle. On error response, revert local state and show toast. Add `isMoving` lock in store to prevent concurrent moves. | Dev | Before Phase 1 ship |

### Paper Tigers (Others worry, we don't — document to align)

| Risk | Why not a Tiger |
|------|-----------------|
| "SQLite can't handle concurrent mind map edits" | Single-user local app. No concurrent writers. SQLite WAL mode already enabled. Not a concern. |
| "React Flow is overkill for tree layout" | It also handles pan/zoom/drag/minimap/export — all required. Building those from scratch is higher risk. |
| "Zustand adds bundle size" | ~1KB gzipped. Worth the clean store pattern vs useContext prop drilling through ~10 components. |

### Elephants (Unspoken, uncertain — investigate)

| Risk | Action |
|------|--------|
| **Brainstorm session JSON format is undocumented** — the `Session.state` JSON shape varies by pipeline (wizard vs YOLO). The AI transformation service needs to handle both. | Before Phase 2: document the two state shapes. If they're too different, create separate extraction functions (`_extract_wizard_state`, `_extract_yolo_state`). |
| **No shared UI component library** — `ui.tsx` has Card, Button, Badge, Modal, Spinner, ErrorState. But no Select, Textarea, ColorPicker, or Toast components used by mind map. | Before Phase 1 frontend: check if these exist elsewhere. If not, build minimal versions inside the mindmap feature or add to shared `ui.tsx` (preferred for Select, Textarea). |
| **Tauri IPC overhead** — current API client uses `invoke` from `@tauri-apps/api/core`. Mind map has many small API calls (node updates on blur). Need to confirm latency is acceptable. | During Phase 1: measure round-trip for `PATCH /nodes/{id}`. If >100ms, batch updates (debounce inspector changes, send all at once). |

## Sequencing Rationale

### Phase 1 first: highest value, lowest uncertainty
- Phase 1 delivers a complete, usable mind map editor. It's shippable on its own.
- The canvas, CRUD, and persistence are the foundation everything else depends on.
- No LLM dependency = no nondeterminism in testing.
- ICE: Impact=9, Confidence=9, Ease=7 → highest priority.

### Phase 2 second: depends on Phase 1 routes + models
- AI is the differentiator, but depends on stable CRUD API.
- ICE: Impact=8, Confidence=6 (LLM output variability), Ease=5 → second.

### Phase 3 third: nice-to-have, no blockers
- Export/import is valuable for sharing but doesn't block core usage.
- ICE: Impact=6, Confidence=9, Ease=6 → third.
- Polish tasks (a11y, error boundaries) are small individually; batch them here.

### What's explicitly deferred (Won't in MoSCoW)
- Real-time collaboration (single-user app)
- Version history beyond undo/redo stack
- Custom themes per node type beyond color + icon
- Mobile-first responsive layout (desktop app, Tauri)
- Mind map template library
- Export to OPML / FreeMind formats (JSON + Markdown covers 90% use case)
- Node comments / attachments
- Search within mind map
- Print layout

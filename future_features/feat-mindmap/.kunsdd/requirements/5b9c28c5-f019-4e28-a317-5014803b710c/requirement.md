# Interactive Mind Mapping for Brainstorming

## Background

Dobby is a local-first AI idea-generation / business-planning app (FastAPI + SQLAlchemy/SQLite backend, React 18 + TypeScript + Tailwind + Tauri frontend). The Brainstorming stage already supports generating, reviewing, and editing ideas via wizard sessions and YOLO generation. Users need a visual mind-map workspace to turn brainstormed ideas into structured, editable concept maps alongside the existing text-based view.

## Goal

Add an interactive visual mind-map workspace within the Brainstorming stage. Users can create, view, organize, edit, and persist mind maps. The map supports AI-generated structures from brainstorm content and full manual editing with CRUD, drag-and-drop, undo/redo, and export.

## Decisions

- **Mind-map library**: React Flow (`@xyflow/react` v12+). Handles pan, zoom, minimap, drag, selection, and SVG/PNG export natively. Compatible with React 18 + Tailwind.
- **Brainstorming data source**: Session `state` JSON (the existing `Session.state` column). "Generate Mind Map" reads structured brainstorm output from this JSON, converts to mind map nodes via a transformation service.
- **Undo/redo**: Snapshot-stack approach (serialize full map → push to bounded stack, default depth 50). Simpler than operation-log replay for a mind map.
- **Phased delivery**: Three phases, each independently shippable and testable.

## Architecture: app-inside-app

The mind map feature is built as a self-contained sub-application with clear boundaries from the host Dobby app. This keeps the feature modular, testable in isolation, and avoids coupling to brainstorming internals.

### Backend boundary

- **Router**: `src/api/mindmap_routes.py` — namespaced under `/api/v1/mindmaps`
- **Models**: `src/db/mindmap_models.py` — SQLAlchemy ORM classes (separate from existing `schema.py` to avoid monolithic file growth)
- **Service**: `src/services/mindmap_service.py` — CRUD, tree validation, cycle detection, snapshot management
- **AI pipeline**: `src/services/mindmap_ai.py` — session JSON → mind map tree, node expansion, regrouping. Depends on existing `src/llm/ollama_client.py`.
- **Contract**: The host app passes session `state` JSON in; the mind map module returns validated tree JSON out. No circular imports.

### Frontend boundary

- **Feature root**: `tauri-app/src/features/mindmap/`
- **Entry point**: `<MindMapWorkspace>` — the single component the brainstorming stage mounts
- **Internal structure**:
  ```
  features/mindmap/
  ├── index.ts              # public exports only
  ├── MindMapWorkspace.tsx   # entry point, owns top-level state
  ├── store.ts               # Zustand store (isolated from global app state)
  ├── components/
  │   ├── MindMapCanvas.tsx   # React Flow wrapper
  │   ├── NodeInspector.tsx   # side panel for editing selected node
  │   ├── MapToolbar.tsx      # toolbar actions
  │   └── EmptyState.tsx      # empty/new map states
  ├── hooks/
  │   ├── useMindMap.ts       # map CRUD operations
  │   ├── useUndoRedo.ts      # snapshot stack management
  │   └── useAutoSave.ts      # debounced persistence
  ├── types.ts                # TypeScript interfaces matching API DTOs
  └── api.ts                  # API client (map, node, edge, snapshot, AI endpoints)
  ```
- **Dependencies**: Only shared UI primitives (button, dialog, input from `src/components/ui/`), the API client, and React Flow. Does not import from other feature directories.

## Phases

### Phase 1 — Core CRUD + Canvas (ship first)

**Goal**: A working mind map editor with full persistence, no AI yet.

- Database migration + SQLAlchemy models
- Backend CRUD routes: maps, nodes, edges, snapshots
- Frontend: React Flow canvas with pan/zoom/minimap/fit-to-screen
- Node inspector side panel (title, type, color, description editing)
- Toolbar: Add Node, Auto Layout, Undo/Redo, Expand/Collapse All
- Keyboard shortcuts
- Drag-and-drop re-parenting with cycle prevention
- Collapse/expand branches
- Snapshot-based undo/redo (in-memory stack, persisted snapshots optional in phase 1)
- Autosave with debounce
- Empty states
- Tests: CRUD, hierarchy, drag validation, cycle prevention, cascade-delete, persistence round-trip, undo/redo

### Phase 2 — AI Integration

**Goal**: Generate, expand, and regroup mind maps from brainstorm session data.

- AI transformation service: session `state` JSON → mind map tree JSON
- Schema validation layer with graceful fallback for invalid LLM output
- "Generate Mind Map" action in brainstorming stage
- "Expand selected node with AI" (3–8 child ideas)
- "Regroup with AI" with accept/reject preview
- Guard: never overwrite user edits silently; AI output is applied as a proposed diff
- Tests: AI JSON schema validation, session→map transformation, preview/accept/reject flow

### Phase 3 — Export/Import + Polish

**Goal**: Shareable output and production fit-and-finish.

- Export: JSON (round-trip), Markdown outline, PNG, SVG
- Import: JSON with schema validation, user-friendly error messages per field
- Include mind maps in project-level exports
- Node duplication with descendants
- Cross-branch edge creation/deletion
- Link brainstorm items to map nodes where source data allows
- Polish: loading states, error boundaries, reduced-motion support, a11y pass
- Tests: export/import round-trip, import validation edge cases

## Acceptance criteria

1. **Integration**: A "Mind Map" tab/toggle exists within the Brainstorming stage. When AI brainstorming produces structured categories, a "Generate Mind Map" action produces a valid, renderable map without overwriting manual edits.
2. **Map CRUD**: Users can create, rename, duplicate, and delete (with confirmation) mind maps per project and per brainstorming session. Maps persist across app restarts.
3. **Node CRUD**: Users can add root/child/sibling nodes; edit title, description, type, color, priority, and status; delete nodes with descendant confirmation; move nodes via drag-and-drop re-parenting; reorder siblings; collapse/expand branches; duplicate nodes with descendants.
4. **Keyboard shortcuts**: Enter (add sibling), Tab (add child), Delete/Backspace (delete selected after confirmation), Escape (cancel edit).
5. **Node types**: A fixed taxonomy — Idea, Problem, Opportunity, Feature, Risk, Assumption, Research Question, Action Item, Decision — each with icon + label, not color alone.
6. **Canvas UX**: Pan, zoom, fit-to-screen, minimap, and selection. Central node visually distinct. Side panel inspector for selected-node editing. Toolbar with Add Node, Generate with AI, Auto Layout, Undo/Redo, Expand/Collapse All, Export. Empty states for new maps and maps with no nodes.
7. **AI assistance**: "Generate Mind Map" extracts brainstorm content → structured JSON → validated → rendered. "Expand node with AI" generates 3–8 child ideas. "Improve/regroup with AI" previews proposed changes before applying — never silently overwrites user edits. Invalid AI output fails gracefully with a user-visible error.
8. **Data integrity**: No orphan nodes, no invalid parent IDs, no cycles, root node rules enforced. Cascading deletes on map deletion do not touch brainstorm content. Foreign keys, indexes, and migrations included.
9. **Undo/redo**: Snapshot-stack undo/redo for all local edits with a visible save state indicator. Autosave after each change.
10. **Export/Import**: Export as JSON (round-trip), Markdown outline, PNG/SVG (via React Flow utilities). Import valid JSON maps with schema validation and user-friendly errors. Include map structure in project exports.
11. **Tests**: CRUD for maps and nodes, hierarchy operations, drag/re-parent validation, cycle prevention, cascade-delete, persistence round-trip, AI JSON schema validation, undo/redo stack, export/import round-trip, and UI empty/loading/error states.

## Constraints

- Reuse existing patterns: SQLAlchemy ORM with String UUID PKs, metadata JSON columns (`metadata` ↔ `extra_metadata`), Pydantic request/response models, FastAPI REST routes, React 18 + TypeScript + Tailwind components.
- Keep the existing brainstorming text view intact. Mind mapping is additive.
- All visible CRUD actions must be fully wired to SQLite persistence. No mock-only wiring.
- Do not delete brainstorm content when a mind map is deleted.
- Frontend state uses Zustand (lightweight, no boilerplate, works well with React Flow). The mind map store is isolated from global app state.
- The mind map module has zero imports from other feature directories. It depends only on shared UI primitives and the API client.

## Data model (aligned with existing conventions)

```sql
-- mind_maps
CREATE TABLE mind_maps (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    root_node_id TEXT,
    viewport_state TEXT,  -- JSON: {x, y, zoom}
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_mind_maps_project ON mind_maps(project_id);
CREATE INDEX idx_mind_maps_session ON mind_maps(session_id);

-- mind_map_nodes
CREATE TABLE mind_map_nodes (
    id TEXT PRIMARY KEY,
    mind_map_id TEXT NOT NULL REFERENCES mind_maps(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    parent_id TEXT REFERENCES mind_map_nodes(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    node_type TEXT NOT NULL DEFAULT 'Idea',
    color TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    metadata TEXT DEFAULT '{}',  -- JSON: position, priority, status, etc.
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_mmn_map ON mind_map_nodes(mind_map_id);
CREATE INDEX idx_mmn_project ON mind_map_nodes(project_id);
CREATE INDEX idx_mmn_parent ON mind_map_nodes(parent_id);

-- mind_map_edges (cross-branch links, distinct from parent-child hierarchy)
CREATE TABLE mind_map_edges (
    id TEXT PRIMARY KEY,
    mind_map_id TEXT NOT NULL REFERENCES mind_maps(id) ON DELETE CASCADE,
    source_node_id TEXT NOT NULL REFERENCES mind_map_nodes(id) ON DELETE CASCADE,
    target_node_id TEXT NOT NULL REFERENCES mind_map_nodes(id) ON DELETE CASCADE,
    relation_type TEXT DEFAULT 'related',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_mme_map ON mind_map_edges(mind_map_id);

-- undo/redo snapshots
CREATE TABLE mind_map_snapshots (
    id TEXT PRIMARY KEY,
    mind_map_id TEXT NOT NULL REFERENCES mind_maps(id) ON DELETE CASCADE,
    snapshot_json TEXT NOT NULL,  -- full serialized map state
    operation_label TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_mms_map_time ON mind_map_snapshots(mind_map_id, created_at);
```

## Deliverables

### Phase 1

1. Database migration + SQLAlchemy models in `src/db/mindmap_models.py`
2. API routes in `src/api/mindmap_routes.py` under `/api/v1/mindmaps`
3. Service layer in `src/services/mindmap_service.py` (CRUD, tree validation, cycle detection, snapshots)
4. Frontend feature module in `tauri-app/src/features/mindmap/` with React Flow canvas, node inspector, toolbar, keyboard shortcuts, drag-and-drop, undo/redo, autosave
5. Zustand store (`store.ts`), API client (`api.ts`), types (`types.ts`)
6. Tests: CRUD, hierarchy, drag validation, cycle prevention, cascade-delete, persistence, undo/redo

### Phase 2

7. AI service in `src/services/mindmap_ai.py` (session JSON → tree, node expansion, regrouping)
8. Schema validation layer for AI output with user-visible fallback
9. "Generate Mind Map", "Expand with AI", "Regroup with AI" actions with preview/accept/reject
10. Brainstorming stage integration: tab/toggle + AI action buttons
11. Tests: AI schema validation, session→map transformation, preview/accept/reject flow

### Phase 3

12. Export (JSON, Markdown, PNG, SVG) and import with validation
13. Node duplication with descendants, cross-branch edges, brainstorm-to-node linking
14. Polish: loading states, error boundaries, reduced-motion, accessibility pass
15. Include mind maps in project-level exports
16. Tests: export/import round-trip, import validation edge cases


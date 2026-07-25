# Mind Map — UI Integration Guide

How the mind-map feature should plug into the **current, redesigned Dobby app** (Tauri 2 + React
18 + Tailwind, token-driven theme, sidebar `AppShell`). Written after verifying the live code, so
these are concrete, file-level directions — not generic advice.

## 1. Where it lives (three entry points)

The REQUIREMENT calls this the "Brainstorming stage," but the app has no page by that name. Its
ideation surface is **Backlog** (the idea list) and the **Wizard/YOLO/Bulk** generators. Integrate
in three places, in priority order:

1. **Primary — a top-level nav item.** In `tauri-app/src/components/AppShell.tsx`, add to the `NAV`
   array (place it after **Graph**, before **Settings**):
   ```ts
   { to: '/mindmap', label: 'Mind Map', icon: IconMindmap },
   ```
   Add `IconMindmap` to `src/lib/icons.tsx` (a central node with three branching children — same
   inline-SVG style as `IconGraph`/`IconLayers`). Add the route in `App.tsx`:
   `<Route path="/mindmap" element={<MindMapPage />} />` → `MindMapPage` wraps
   `<MindMapWorkspace projectId="default-project" />`.

2. **Contextual — a "List | Mind Map" toggle on the Backlog page** (`pages/BacklogPage.tsx`). This is
   the most natural "turn my ideas into a map" moment. Use the same segmented-toggle pattern the
   Wizard uses for steps; when "Mind Map" is active, render `<MindMapWorkspace projectId=...
   sessionId={...} />`. (The plan wires it into `Wizard.tsx`; Backlog is the better fit — Wizard is a
   linear 7-step generator, not an ideation canvas. Keep the Wizard hook as a secondary option.)

3. **Discovery — a Dashboard "Start something" card.** In `pages/Dashboard.tsx`, add a fourth mode
   card next to Wizard/YOLO/Bulk: **"Mind Map — organize ideas visually,"** linking to `/mindmap`.

## 2. Use the app's design system (don't reinvent)

The app is fully token-driven; the mind map must read from the same CSS variables so it matches
light/dark automatically and inherits the **Dobby violet** accent.

- **Reuse `src/components/ui.tsx`**: `Card`, `Button`, `Badge`, `Modal`, `Spinner`, `LoadingState`,
  `ErrorState`, `EmptyState`, `PageHeader`. **Add `Select` and `Textarea`** to this file (they don't
  exist yet) so NodeInspector and the toolbar use shared primitives — do not hand-roll form controls.
- **Toasts**: reuse `src/lib/toast.tsx` `useToast()` for AI success/failure and save errors. Do not
  add a second toast system.
- **Theme tokens** (from `src/index.css` / `tailwind.config.js`): style React Flow with them so it
  tracks the theme:
  ```tsx
  <ReactFlow ...>
    <Background color="rgb(var(--line))" gap={16} />
    <MiniMap maskColor="rgb(var(--surface2))" nodeColor="rgb(var(--brand))" />
    <Controls />   {/* wrap in a .card for consistent chrome */}
  </ReactFlow>
  ```
  Node cards: `bg-surface border border-line text-ink`, selection ring `ring-2 ring-brand`,
  left strip `border-l-4` in the node-type color. Because React Flow reads inherited CSS, the app's
  `.dark` class flips the whole canvas with no extra work.
- **Node-type color + icon** must map to the existing badge tones so the map reads as "Dobby":
  | Node type | Badge tone | Icon (add to `lib/icons.tsx`) |
  |---|---|---|
  | Idea | `brand` (violet) | sparkles |
  | Opportunity | `success` | trending-up |
  | Feature | `accent` | layers |
  | Problem / Risk | `danger` / `warning` | alert |
  | Assumption | `neutral` | help-circle |
  | Research Question | `neutral` | search |
  | Action Item | `brand` | check-square |
  | Decision | `accent` | git-branch |

## 3. Layout inside the shell

`AppShell`'s `<main>` centers content at `max-w-6xl`, which is too narrow for a canvas. For the
`/mindmap` route, let the workspace go **full content width** (either render `MindMapWorkspace`
outside the `max-w-6xl` wrapper for this route, or give it `className="-mx-6 w-[calc(100%+3rem)]"`).
Layout: `PageHeader` + `MapToolbar` on top, canvas fills the rest, `NodeInspector` as a 320px
right slide-out (absolute, with the app's `card` styling and a close button).

## 4. API transport — use `fetch`, skip the invoke layer

The app's `client.ts` is dual-transport (`invoke` in Tauri, `fetch` in browser) **because it has
matching Rust commands**. The mind map has **no Rust commands** and adding 18 of them is wasteful:
the Python backend is always reachable on `localhost:8000` from both the Tauri webview (CSP is
`null`) and the browser. So `features/mindmap/api.ts` should **call `fetch` directly** (reuse the
same `http()` helper shape as `client.ts`), not `invoke`. This is the one deviation from "mirror
client.ts exactly" — mirror its *error handling and base-URL* convention, not its invoke branch.

## 5. State library note

The app currently uses **plain React hooks + context** (`ThemeProvider`, `ToastProvider`) — it has
**no Zustand today**. The plan introduces Zustand for the isolated mind-map store. That's acceptable
(~1KB, well-scoped) but it's the app's *first* Zustand dependency — flag it in the PR. If you'd
rather not add a state lib, a `useReducer` + context inside `features/mindmap/` covers this store's
needs. Recommendation: **Zustand is fine, kept strictly inside the feature folder** (the REQUIREMENT
already mandates this isolation).

## 6. Persistence & backend fit (already correct in the plan)

- New tables via `src/db/mindmap_models.py` importing `Base` from `src.db.schema`; import them in
  `schema.py` before `Base.metadata.create_all` runs in `DatabaseManager.__init__`. ✔ matches code.
- Use `Column("metadata", JSON)` mapped to a `extra_metadata` Python attr (the app's convention). ✔
- `mindmap_routes.py` defines its own `get_db()` (`from src.main import app; return app.state.db`),
  registered in `main.py` with `app.include_router(mindmap_router)`. ✔ matches the other routers.
- Reuse `src/llm/ollama_client.py` for Phase 2 AI, honoring the user's selected model in Settings. ✔

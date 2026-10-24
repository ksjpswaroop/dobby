# Dobby — Vision UI/UX Design

**Local-first AI workbench for builders.** One minimal, categorized desktop app to *capture → generate → automate → build → ship* — fully on-device (Tauri 2 + React 18 + Tailwind + FastAPI + SQLite, LLM via local Ollama/llama.cpp), with an on-device marketplace of skills, flows, and apps.

This document specifies the redesigned shell, the information architecture, the minimal design language, and the per-screen UX for all 13 new features. It is written to be *built*: it references the existing design tokens in `index.css` and the primitives in `components/ui.tsx` (Card/CardBody, Button, Badge, Spinner/LoadingState, PageHeader, EmptyState, ErrorState, ScoreRing) plus the `.nav-link` / `.card` / `.input` / `.chip` component classes.

---

## (a) Design philosophy

**Categorized · minimal · keyboard-first · local-first · calm.**

- **Categorized** — Every destination lives in exactly one of six mental buckets (Workspace, Generate, Studio, Automate, System, Marketplace). The user never scans a flat list of 20+ links; they scan 6 headers, then drill in.
- **Minimal** — One accent (violet `--brand`), generous whitespace, few borders, no gradients or decoration that doesn't carry meaning. Chrome recedes; content leads. Reuse the existing token palette rather than introducing new colors.
- **Keyboard-first** — `⌘K` opens the Command Center from anywhere. Every primary action has a shortcut. Navigation, search, and command execution never require the mouse. Focus rings (`focus-visible:ring-brand/40`) are always visible.
- **Local-first** — Nothing leaves the device by default. The status pill always tells the truth about what's running (backend, Ollama model, offline). "Private, offline" is a feature surfaced in the UI, not a footnote.
- **Calm** — Motion is short and purposeful (150ms transitions, `animate-fade-in`, `animate-scale-in`). No spinners where a skeleton will do. Errors are recoverable, not alarming. The interface stays quiet until the user acts.

Guiding rule: *a new builder should feel oriented in 10 seconds and productive in 60.*

---

## (b) Information architecture

Six categories, ordered by the natural build loop — you *organize* work, then *generate* artifacts, *capture* media, *automate* the repetitive parts, *operate/observe* the system, and *extend* it from the marketplace.

| Category | Contains | Why grouped this way |
|----------|----------|----------------------|
| **Workspace** | Dashboard, Projects, Documents, Backlog, Graph, Mind Map | The "where is my stuff" layer — everything you've created and its structure. Home base you return to between tasks. |
| **Generate** | Wizard, YOLO, Bulk, Prototype Builder, Video Studio | The "make an artifact from a prompt" layer — one-shot and guided generation of documents, apps, and video. |
| **Studio** | Audio Transcription, YouTube → Notes, Notes | The "capture the world into text" layer — media in, structured notes out. |
| **Automate** | Command Center, Skill Builder, Flow Builder | The "make it repeatable" layer — turn one-off actions into reusable skills and multi-step flows. |
| **System** | Global Search, Terminal, Logs & Traces, Control Center, Settings | The "operate & observe" layer — find anything, run commands, watch what agents do, tune the machine. |
| **Marketplace** | Marketplace (Skills / Flows / Apps) | The "extend Dobby" layer — install community skills/flows/apps locally today, publish later. |

Item-placement rationale worth noting:
- **Mind Map** sits in Workspace (not Studio) because it visualizes *your existing* projects/documents, like Graph.
- **Command Center** lives in Automate (it is the action hub) but is *also* globally reachable via `⌘K` from the top bar — the sidebar entry is the discoverable, browsable form of the same palette.
- **Global Search** is a System destination *and* is always present as the top-bar search field; the sidebar entry opens the full results/filters page.
- **Prototype Builder** and **Video Studio** are Generate (they produce artifacts from a brief), while **Skill/Flow Builder** are Automate (they produce reusable machinery).

Status model: each item is `live` (Dashboard, Projects, Documents, Backlog, Graph, Wizard, YOLO, Bulk, Settings) or `planned` (the 13 roadmap features + Mind Map). Status drives rendering — see (f).

---

## (c) The redesigned shell

Three regions: **grouped sidebar** (left), **global top bar** (top of main column), **content** (main). This preserves the current `AppShell` structure and its `h-14` bars, `w-60` sidebar, and `max-w-6xl` content column — the redesign is additive, not a rewrite.

### Grouped, collapsible sidebar (`w-60`, `border-r border-line`, `bg-surface/60`)

```
┌─────────────────────────┐
│  ◧ Dobby            v2.0 │   ← brand row (h-14), unchanged
├─────────────────────────┤
│  WORKSPACE            ⌄  │   ← category header (collapsible)
│   ◱ Dashboard           │
│   ◲ Projects            │
│   ◳ Documents           │
│   ◴ Backlog             │
│   ⬡ Graph               │
│   ⬢ Mind Map     ·soon  │   ← planned badge
│  GENERATE             ⌄  │
│   ✦ Wizard              │
│   ⚡ YOLO                │
│   ▤ Bulk                │
│   ⧉ Prototype   ·soon   │
│   ▷ Video Studio ·soon  │
│  STUDIO             ⌄    │
│   ...                    │
│  AUTOMATE           ⌄    │
│  SYSTEM             ⌄    │
│  MARKETPLACE        ⌄    │
├─────────────────────────┤
│  Local-first · Ollama    │   ← footer, unchanged
└─────────────────────────┘
```

- **Category headers**: uppercase, `text-[11px] font-semibold tracking-wide text-ink-muted`, with a chevron (`IconChevronRight`, rotates 90° when open, reusing the ProjectSwitcher pattern). Clicking toggles the group; state persists in `localStorage` (`dobby.nav.collapsed`). Headers are `<button>`s with `aria-expanded`.
- **Items**: reuse `.nav-link` / `.nav-link-active` exactly. Each item keeps its lucide-style icon (`size={18}`) from `lib/icons`; new features get new icons added there (Terminal, Search, Skill, Flow, Mic, Video, etc.).
- **Planned items**: rendered with reduced emphasis (`opacity-70`) and a trailing `Badge tone="neutral"` reading "Soon". They remain clickable and route to a roadmap placeholder screen (see f).
- **Density**: default groups Workspace + Generate expanded; the rest remember the user's last state. This keeps the sidebar scannable without scrolling on first run.
- **Active-project scoping** stays in the top bar (ProjectSwitcher), not the sidebar — navigation is about *capability*, the project switcher is about *scope*.

### Global top bar (`h-14`, `border-b border-line`, `bg-surface/60 backdrop-blur`)

```
┌───────────────────────────────────────────────────────────────────────┐
│  [▾ My Workspace]   [ ⌕ Search…  ⌘K ]        ● llama3.1  [☀ ◐ ☾]        │
└───────────────────────────────────────────────────────────────────────┘
  ProjectSwitcher      Search + Command Center      Status pill  Theme
```

- **ProjectSwitcher** — unchanged (left).
- **Search field (center)** — a `.input`-styled button/field, `max-w-md`, with a leading search icon and a trailing `⌘K` kbd hint. Focusing it (or pressing `⌘K`) opens the **Command Center** overlay. On desktop the field is inline; below `md` it collapses to an icon button. This is the single, always-present entry to both Global Search and command actions.
- **Command Center overlay** — a centered `Modal`-style palette (`animate-scale-in`, `shadow-pop`, `max-w-xl`) with a fuzzy input at top and grouped results below: *Actions* (run wizard, new project, toggle theme…), *Navigate* (jump to any destination, live or planned), *Search results* (semantic + full-text over projects/docs/notes). Arrow keys move, `Enter` runs, `Esc` closes. Mirrors the ProjectSwitcher dropdown mechanics (outside-click close, keyboard nav) at full-screen scale.
- **Status/model pill** — extend the existing `StatusPill`: shows the live dot (success/warning/danger) + active model name, and on hover a small popover with backend URL, model, and quick "switch model" link to Settings. Truthful about offline states.
- **Theme toggle** — unchanged (light / system / dark segmented control).

### Content region

`main` keeps `overflow-y-auto` + centered `max-w-6xl px-6 py-8 animate-fade-in`. Every screen opens with a `PageHeader` (title + subtitle + right-aligned actions), matching current pages.

---

## (d) Minimal design principles

- **Spacing & rhythm** — 4px base grid (Tailwind default). Cards use `rounded-2xl` + `p-5` (`CardBody`). Page sections separated by `gap-6`/`mb-6`. Let whitespace, not lines, do the grouping; use `border-line` sparingly.
- **One accent** — Violet `--brand` is the *only* action/selection color (buttons, active nav, focus rings, selected chips). Semantic tones (`--success`/`--warning`/`--danger`) are reserved strictly for status. Never use the accent decoratively.
- **Progressive disclosure** — Show the 20% first; reveal advanced controls on demand (collapsible "Advanced" sections, popovers, right-side inspector panels). The Command Center is the escape hatch for power users so the surface can stay clean.
- **Consistent states** — Every data view implements the four canonical states with existing primitives:
  - *Loading* → `LoadingState` or `.skeleton` blocks (prefer skeletons for content-shaped waits).
  - *Empty* → `EmptyState` with icon + one-line description + a single primary `Button` CTA.
  - *Error* → `ErrorState` with a message and `onRetry`.
  - *Populated* → `Card`/table content.
- **Typography** — One sans family. Sizes: page title `text-2xl font-semibold`, section `text-base font-medium`, body `text-sm`, meta `text-xs text-ink-muted`. Numbers/scores can use `ScoreRing`.
- **Dark mode** — First-class via the `.dark` token set already defined. Never hardcode hex; always use token utilities (`bg-surface`, `text-ink`, `border-line`, `bg-brand/10`) so both themes track automatically. Verify contrast in both.
- **Accessibility** — Visible `focus-visible` rings everywhere; all interactive chrome is real `<button>`/`<a>` with `aria-label`/`aria-expanded`; `⌘K` and arrow-key nav; icon-only controls always carry a title/label; respect `prefers-reduced-motion` by dropping non-essential transitions; hit targets ≥ 32px.

---

## (e) Per-feature screen & UX (all 13 new features)

Each planned screen follows the same skeleton: `PageHeader` → primary work area → state handling via `EmptyState`/`LoadingState`/`ErrorState`. Layouts below describe the *populated* state.

### System

**1. Global Search — `/search`**
Full-page results view backing the top-bar field. Layout: a large `.input` search box (auto-focused) at top; below, a left rail of filters (source type: Projects / Documents / Notes / Backlog / Logs; date; project scope) and a right results list. Each result is a `Card` row: title, source badge (`Badge tone="brand"`), matched snippet with highlighted terms, and a relevance meter. Toggle between **Semantic** (local embeddings) and **Exact** (full-text) with a segmented control. Interactions: type to query (debounced), `↑/↓` to move, `Enter` to open, `⌘Enter` to open in split. Empty state invites indexing; a small "Indexing… n/m" inline progress shows when embeddings are building.

**3. Logs & Traces — `/logs`**
Run observability. Layout: left column = chronological run list (each run a `Card` row: name, status dot, duration, model, timestamp); right column = trace detail for the selected run — a collapsible tree of steps (agent → tool call → result), each node showing inputs/outputs, token counts, and latency. Live runs stream in with a pulsing dot (reuse the `StatusPill` ping). Interactions: filter by status/tool/date, click a node to expand, copy any payload, "re-run" a past run. Uses `Badge` tones for status. Error entries expand to full stack/`ErrorState` styling.

**4. Embedded Terminal — `/terminal`**
Sandboxed, approval-gated shell. Layout: a dark terminal surface filling the content area with a fixed command input at the bottom and a top strip showing the sandbox scope (working dir, allowed paths) as chips. Every command that mutates state or hits the network surfaces an **approval prompt** as an inline `Modal` ("Dobby wants to run `npm install` in ~/proj — Allow / Deny") — approval is per-command and per-session, never blanket. Interactions: run, interrupt (`⌃C`), clear, scrollback; command history with `↑`. A persistent banner reinforces that nothing runs without approval. Read-only until the sandbox is granted (EmptyState explaining how to enable).

**10. Control Center — `/control`**
Agents / permissions / orchestration control. Layout: a grid of `Card`s — one per running or configured agent — showing name, current task, model, live status, and pause/stop controls; plus a **Permissions** panel listing granted capabilities (filesystem paths, network, terminal, marketplace installs) as toggles with clear scopes. A top summary row uses stat tiles (active agents, queued tasks, blocked-on-approval). Interactions: pause/resume/stop an agent, revoke a permission, inspect an agent's live trace (deep-links to Logs & Traces), and approve pending permission requests. This is the "kill switch + trust dashboard" for autonomous work.

### Studio

**5. Audio Transcription — `/transcribe`**
Local Whisper/STT. Layout: a drop zone (`EmptyState`-style dashed border) for audio/video files or a **Record** button; once a file is loaded, a two-pane view — left: waveform + playback scrubber; right: live-populating transcript with timestamps. Interactions: choose model size (tiny→large) and language, start/stop, seek by clicking a transcript line (jumps audio), edit text inline, export (`.txt`/`.srt`/`.md`) or "Send to Notes". Progress shown as a determinate bar per chunk. Fully offline; a note states audio never leaves the device.

**6. YouTube → Notes — `/youtube`**
URL in, notes out. Layout: a single URL `.input` + fetch button at top; on fetch, a card shows the pulled video metadata (thumbnail, title, duration) and a pipeline stepper — *Fetch → Extract audio → Transcribe → Summarize → Notes* — each step with its own status dot. Result area is a tabbed view: **Transcript**, **Summary**, **Notes** (structured outline). Interactions: pick summary style/length, regenerate any stage, "Save to Documents/Notes". Reuses the transcription engine from `/transcribe`. Respects local-first: only the fetch step touches the network, and it's clearly labeled.

**7. Notes — `/notes`**
AI notes from any source. Layout: a two-pane editor — left: source list / import (paste text, pick a document, drop a file, or link a transcription); right: a clean prose editor (`.prose`, `data-selectable`) with an AI action bar (Summarize, Outline, Expand, Extract action items, Rewrite tone). Notes are saved as Documents and can feed Backlog/Graph. Interactions: `⌘K`-style inline AI menu on selection, autosave with a subtle saved indicator, tag and link notes. Minimal, writing-focused; chrome fades while typing.

### Generate

**11. Prototype Builder + Test — `/prototypes`**
Generate app prototypes, preview, test. Layout: three-pane — left: brief/spec input and file tree of the generated prototype; center: live preview iframe (device-size toggle: mobile/tablet/desktop, mirroring the browser preview pattern); right: a **Test** panel that runs generated checks and shows pass/fail with `ScoreRing` for overall health. Interactions: describe the app → generate → preview updates live → iterate via chat-style refinements → run tests → export the project. Long generations stream into the file tree with skeletons. This is the flagship XL Generate surface; keep the three panes resizable and the preview dominant.

**12. Video Studio — `/video`**
Local video generation. Layout: a script/prompt panel on the left (scene list, per-scene prompt, voice/style options), a preview player center, and a render queue on the right (each job a `Card` with progress + status). Interactions: compose scenes, choose model/style, render (determinate progress, cancelable), preview, export MP4. Because renders are long, jobs run in the background and surface completion via the queue + a toast; the queue survives navigation. EmptyState offers starter templates.

### Automate

**2. Command Center — `/command`**
The browsable form of the `⌘K` palette. Layout: full-page action hub — a search field on top, then grouped, filterable cards of every available **Action**, **Skill**, and **Flow**, each with a run button and a keyboard hint. A right rail shows recent/pinned commands. Interactions: run any action inline, pin favorites, assign shortcuts, and see what each action will do before running. The overlay (`⌘K`) and this page share one command registry so they never drift.

**8. Skill Builder — `/skills`**
Author reusable AI skills. Layout: left: list of skills (`Card` rows with name, trigger, last-run); center: a skill editor — name, description, trigger/inputs schema, the prompt/instructions body (`.prose` editor), and tool permissions; right: a live **Test** panel to run the skill against sample input and inspect output + trace. Interactions: define inputs, edit instructions, dry-run, version, and "Publish to Marketplace" (later phase). Progressive disclosure: advanced fields (model, temperature, tool grants) live under an "Advanced" collapse.

**9. Flow Builder — `/flows`**
Visual multi-step automations. Layout: a canvas (node-graph, consistent with the existing Graph view's visual language) where nodes are skills/actions/conditions and edges are data/control flow; a left palette of draggable node types; a right inspector for the selected node's config. A top bar has Run / Save / validate. Interactions: drag to add, connect ports, configure per node, run the whole flow with live per-node status (dots animate as data passes), and open any run in Logs & Traces. Minimal node styling — rounded cards, one accent for the active path.

### Marketplace

**13. Local App Marketplace — `/marketplace`**
Install skills/flows/apps locally (publish later). Layout: a storefront grid — top tabs **Skills / Flows / Apps**, a search/filter bar, and a responsive grid of item `Card`s (icon, name, author, short description, install count, `Badge` for category). Clicking a card opens a detail panel: description, required permissions (explicitly listed), screenshots, and an **Install** button. Interactions: browse/search, view permissions before install, install locally (installs land in the matching section — skills in Skill Builder, flows in Flow Builder, apps in the launcher), manage/uninstall from an "Installed" tab. A clear banner distinguishes *local install* (available now on the roadmap) from *publish to cloud* (later). Every install is permission-gated through Control Center.

---

## (f) Motion, feedback & the "coming soon" state

**Motion & feedback**
- Transitions are 150ms and limited to `opacity`/`transform`/`colors` (reuse `animate-fade-in`, `animate-scale-in`, `shadow-pop`). No layout-thrashing animations.
- Feedback hierarchy: instant (button `active:` state) → short toast for background events (render done, saved) → inline status dots for live processes (reuse the `StatusPill` ping) → determinate progress bars for anything with known length (transcription chunks, renders).
- Prefer **skeletons** (`.skeleton`) over spinners for content-shaped loads; reserve `Spinner`/`LoadingState` for indeterminate short waits.
- Respect `prefers-reduced-motion`: drop the ping and scale-ins, keep instant state changes.

**Planned / "on roadmap" state**
Planned destinations are real routes so the IA is complete and explorable from day one, but they render a consistent **Roadmap placeholder**:
- Sidebar: item at `opacity-70` with a trailing `Badge tone="neutral"` "Soon".
- Page: a `PageHeader` with the feature name + a one-line description, then an `EmptyState` styled panel showing:
  - the feature's icon,
  - a short "What this will do" paragraph,
  - its **phase badge** (e.g., `Badge tone="brand"` "Phase 2") and rough timeframe from the roadmap,
  - a single CTA — "Notify me / Track on roadmap" (local, no network) — and a link to the relevant already-live capability if one exists (e.g., YouTube→Notes links to Documents).
- The Command Center lists planned actions too, dimmed and tagged "Soon", so users discover what's coming without dead ends.

This keeps the app honest (nothing pretends to work), navigable (the full structure is present), and motivating (users see the roadmap taking shape). As each feature ships, flipping its status from `planned` to `live` in `categories.json` is the only change needed to promote it.

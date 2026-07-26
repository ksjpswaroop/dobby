# Dobby — Feature Tracker

Single source of truth for what is built, what is next, and what is deferred.
Supersedes the loose `PHASE_*_*.md` files at the repo root (see *Housekeeping*).

**Last updated:** 2026-07-26 · **Branch:** `feat/dobby-v2-workbench` · **PR:** [#1](https://github.com/ksjpswaroop/dobby/pull/1)

**Status at a glance:** 13 of 23 navigation surfaces are live · 60 API endpoints ·
112 backend tests passing · frontend typechecks and builds clean.

---

## Legend

| Mark | Meaning |
|---|---|
| ✅ | Built, tested, verified running end-to-end |
| 🟡 | Partially built — works but has a named gap |
| ⬜ | Specced, not started |
| ❄️ | Deliberately deferred (reason given) |

Phases follow `docs/expansion/04_ROADMAP_AND_PROJECT_PLAN.md`.

---

## 1. Shipped

### Core generation platform
| # | Feature | State | Notes |
|---|---|---|---|
| 1.1 | Project CRUD + multi-project switching | ✅ | `localStorage` active project; seeded `default-project` on first run |
| 1.2 | Feature backlog with Pareto scoring | ✅ | impact/effort/risk sliders, ranked list |
| 1.3 | Wizard generation (7 gated steps) | ✅ | per-step review/accept/edit; `force` override for weak models |
| 1.4 | YOLO generation (one-shot, 7 artifacts) | ✅ | live run events, score rings, accept/discard |
| 1.5 | Bulk generation (many ideas, parallel) | ✅ | coverage matrix; verified 21/21 documents, zero gaps |
| 1.6 | Deterministic verifier | ✅ | 7 rule-based checks, no LLM, pass threshold 85 |
| 1.7 | Document browser + reader | ✅ | grouped by feature/type, markdown download |
| 1.8 | Dependency graph (Mermaid) | ✅ | live-extends as each document is generated |

### Observability
| # | Feature | State | Notes |
|---|---|---|---|
| 2.1 | Run history + event traces | ✅ | `/logs` |
| 2.2 | Live run streaming (SSE) | ✅ | in-process asyncio pub/sub |
| 2.3 | Global search | ✅ | projects, documents, backlog, runs |
| 2.4 | Command palette (⌘K) + Command Center | ✅ | actions, model switching, live search |

### Mind map
| # | Feature | State | Notes |
|---|---|---|---|
| 3.1 | Canvas: CRUD, drag re-parent, collapse | ✅ | React Flow; cycle-rejection returns 400 |
| 3.2 | Tree + radial layouts | ✅ | dependency-free, ~40-line tidy-tree |
| 3.3 | AI generate / expand / regroup | ✅ | two-pass JSON repair for small models |
| 3.4 | Undo/redo + server snapshots | ✅ | snapshot restore covers deletes |
| 3.5 | Export: JSON, Markdown, Mermaid, PNG, SVG | ✅ | PNG/SVG rendered client-side |
| 3.6 | **Markdown-outline interchange** | ✅ | *new* — the portable format; import + export + replace |
| 3.7 | **AI chat editing** | ✅ | *new* — markdown-in/markdown-out, ~5s on qwen2.5:7b |
| 3.8 | **Branch colour + checkboxes** | ✅ | *new* — colour inherited through nodes and edges |
| 3.9 | Document → mind map | ✅ | *new* — generated specs are already heading markdown |

### Research (new — sits before Create)
| # | Feature | State | Notes |
|---|---|---|---|
| 5.1 | Five-track research (product, market, competition, business, technical) | ✅ | Tracks run concurrently; ~4 min on llama3.2 |
| 5.2 | Pluggable web search, default off | ✅ | `none` / `searxng` (local) / `tavily` / `brave`; remote ones labelled in the UI |
| 5.3 | Fabricated-statistic backstop | ✅ | Unsourced figures auto-tagged `[unverified]` — prompt instructions alone proved insufficient |
| 5.4 | Research → backlog hand-off | ✅ | Findings become scored feature proposals; user picks before anything is written |
| 5.5 | Traced through Logs & Traces | ✅ | Reuses the existing `Tracer` + SSE channel |

### Platform
| # | Feature | State | Notes |
|---|---|---|---|
| 4.1 | Local-first: Ollama, SQLite, no cloud calls | ✅ | |
| 4.2 | Model management in-app | ✅ | list / pull / delete |
| 4.3 | Theme (system/light/dark) | ✅ | |
| 4.4 | Tauri desktop shell | 🟡 | builds and bundles a DMG; **no tray, unsigned, no updater** — see 6.4 |

---

## 2. Next up — highest value first

These are ordered by *how much they increase daily use*, not by how easy they are.

| # | Feature | Phase | Why it matters | Est. |
|---|---|---|---|---|
| N1 | **Terminal** (`/terminal`) | P2 | The single biggest reason to leave Dobby today. Sandboxed, approval-gated. | 2w |
| N2 | **Skills** (`/skills`) | P3 | Turns Dobby from a document generator into something users extend. Prompt + tools + schema, runnable and publishable. | 3w |
| N3 | **Flows** (`/flows`) | P3 | Chains skills into automations. Skills without flows stay toys. | 3w |
| N4 | **Audio transcription** (`/transcribe`) | P2 | Whisper sidecar. Unlocks N5 and N6. | 2w |
| N5 | **YouTube → notes** (`/youtube`) | P2 | Transcript + audio extract + note builder. Strong daily-use hook. | 1w |
| N6 | **Notes builder** (`/notes`) | P2 | The capture surface the mind map already half-implies. | 2w |
| N7 | **Prototypes** (`/prototypes`) | P4 | Build and test app prototypes from a generated spec. | 4w |
| N8 | **Video generation** (`/video`) | P4 | | 3w |
| N9 | **Control system** (`/control`) | P3 | Govern agents, permissions, models, resource limits. | 2w |
| N10 | **Marketplace** (`/marketplace`) | P5 | Install/publish skills, flows, apps. Needs N2+N3 first. | 4w |

---

## 3. Known gaps in shipped work

| # | Gap | Severity | Detail |
|---|---|---|---|
| G1 | **~950 lines of dead backend code** | **High** | `src/audit/trail.py` (484 L) has zero importers — `GET /projects/{id}/audit` queries `AuditEntry` directly instead. `src/graph/graph.py` (448 L) was imported by three modules that never used a single symbol; those imports are now removed, leaving the module orphaned. `src/utils/logging.py` is unreferenced and `src/utils/` has no `__init__.py`. **Decide: delete or wire up.** |
| G2 | Unreachable methods across live modules | Medium | `WizardPipeline.complete_wizard` / `resume_wizard`, `YOLOPipeline.edit_and_accept`, `ParetoScorer.adjust_scores_based_on_learning`, most of `SessionManager`, `DatabaseManager.backup`/`restore`, `OllamaClient.generate_stream`/`list_models`. Several are half-built features, not accidents — triage individually. |
| G3 | Model listing implemented twice | Medium | `settings_routes.py:84` re-implements `/api/tags` with raw `httpx` while `OllamaClient.list_models` sits unused. One of the two should go. |
| G4 | 8 endpoints no client ever calls | Medium | graph/edges, backlog start, 3 session routes, audit, yolo/reject, and a duplicate `GET /api/v1/health` shadowing the app-level `/health`. |
| G5 | Test coverage has holes | Medium | Nothing covers `src/audit`, `src/graph`, `src/sessions`, `src/cli`, or the execution paths of `wizard.py` / `yolo.py` — the two pipelines that *are* the product. |
| G6 | Outline export is not byte-identical | Low | A bullet under `## X` returns as `###`. Same tree, different text. JSON stays lossless. |
| G7 | Client undo cannot resurrect deleted nodes | Low | By design — server snapshots cover it, and whole-tree rewrites use them. |
| G8 | Mind map is 31 of 68 operations (46%) | Medium | The subsystem is disproportionate to its place in the product. Worth watching, not yet worth splitting. |
| G9 | No auth, no multi-user | ❄️ | Correct for a local-first app. Revisit only if sync ships. |
| G10 | Bundle chunks >500 kB | Low | Mermaid + React Flow. Needs `manualChunks` before any web deploy. |
| G11 | `datetime.utcnow()` deprecated | Low | ~950 warnings per test run. Mechanical fix, touches many files. |

---

## 4. Recommended organisation changes

### Menu — keep five verbs, fix what sits under them

The five-verb sidebar (Ideate · Create · Automate · Develop · Settings) is
right and should not change again. The problems are *inside* it:

| # | Change | State |
|---|---|---|
| M1 | Section landings must open a working tab, not a stub | ✅ done — `/automate`→`/command`, `/develop`→`/logs` |
| M2 | Live tabs ordered before planned ones | ✅ done |
| M3 | Unknown routes redirect home instead of rendering an empty shell | ✅ done |
| M4 | **Create has 9 tabs, 5 of them stubs** — split media capture out or hide unbuilt tabs behind a "Coming soon" toggle | ⬜ |
| M5 | Consider demoting `Bulk` into Wizard/YOLO as a mode rather than a third sibling | ⬜ |

### Look and feel

The visual language (OpenWorker palette, rounded cards, soft shadows, in-page
tabs) is consistent and does not need rework. What it needs:

| # | Change | State |
|---|---|---|
| L1 | Ten "coming soon" cards is too many to advertise. Show planned items only in a roadmap view, or gate them behind a setting. | ⬜ |
| L2 | Empty states should offer the *next action*, not just describe emptiness | 🟡 partly done in mind map |
| L3 | Onboarding: first run drops you on a dashboard with no explanation of Wizard vs YOLO vs Bulk | ⬜ |
| L4 | Keyboard shortcuts exist but are undiscoverable outside ⌘K | ⬜ |

### How to evolve

The strategic question is **which of the two Dobbys is the product** — see 6.3.
Assuming it is this repository:

1. **Finish one vertical completely** before starting another. Terminal (N1)
   is the right one: it is the main reason to leave the app.
2. **Skills + Flows are the moat** (N2, N3). Document generation is
   commoditised; a local, extensible, private automation surface is not.
3. **Media capture (N4–N6) is the daily-use hook.** It is what makes someone
   open Dobby before their browser — the "toothbrush test" from the 100-day
   roadmap.
4. **Marketplace last** (N10). It needs things worth installing.

---

## 5. Housekeeping

| # | Task | Why |
|---|---|---|
| H1 | Move the 18 root `PHASE_*` / `ARCHITECTURE_*` / `BUILD_SUMMARY` files into `docs/history/` | They are progress notes, not documentation. They dominate the repo root and nobody reads them. |
| H2 | Fold `future_features/feat-mindmap/TRACKER.md` into this file | Two trackers is one too many. |
| H3 | Delete `src/audit/` and `src/graph/` — or wire them up | G1. Both are substantial, coherent modules that nothing calls. Dead code that *looks* load-bearing is worse than none. |
| H4 | Delete `src/utils/logging.py`, or add `__init__.py` and use it | G1. |
| H5 | Drop the duplicate `GET /api/v1/health` | G4 — it shadows nothing but confuses readers. |
| H6 | Add a `path="*"` test | Regression guard for M3. |
| H7 | `manualChunks` for mermaid + React Flow | G10. |
| H8 | Cover `wizard.py` / `yolo.py` execution paths with tests | G5 — these are the product's core and are currently untested. |

---

## 6. Open questions for the owner

| # | Question |
|---|---|
| 6.1 | Should planned surfaces be visible at all before they are built? Ten stubs makes the app feel emptier than it is. |
| 6.2 | Is Bulk a first-class mode or a Wizard option? |
| 6.3 | **Which codebase is Dobby?** This Tauri repo, or the rebranded OpenWorker fork in `~/Downloads/openworker-main`? The fork is not under version control and is not pushed anywhere — that work is one disk failure from gone. |
| 6.4 | Ship a signed, auto-updating desktop build, or stay dev-only for now? Tray, code signing, and updater endpoints are all unimplemented here. |

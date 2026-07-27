# Dobby — Current Status

**Date:** 2026-07-26 · **Branch:** `feat/dobby-v2-workbench` · **PR:** [#1](https://github.com/ksjpswaroop/dobby/pull/1)

For what to build next, see [FEATURE_TRACKER.md](FEATURE_TRACKER.md).

---

## What Dobby is today

A local-first desktop app that turns a product idea into a full set of
specification documents, with nothing leaving the machine. Tauri shell, React
frontend, FastAPI backend, SQLite storage, Ollama for inference.

**It works end to end.** You can create a project, add features to a
Pareto-ranked backlog, generate seven document types per feature (three ways:
guided, one-shot, or bulk), watch generation stream live, verify output against
deterministic rules, browse and export the results, and organise the whole thing
as a mind map.

### Health

| Measure | Value |
|---|---|
| API operations | 68 across 60 paths |
| Backend tests | 112 passing |
| Frontend | typechecks clean, builds clean |
| Navigation surfaces | 23 total — **13 live, 10 planned stubs** |
| Dead backend code | ~950 lines (see tracker G1) |
| External runtime dependencies | none beyond Ollama |

---

## Changes made in this session

### Mind map: portability and conversational editing

The mind map could previously only talk to itself. Now it interchanges with the
rest of the world and can be edited by asking.

- **Markdown-outline interchange** (`src/services/mindmap_outline.py`). Heading
  markdown is what markmap, Obsidian, Logseq and most text-to-mind-map tools
  read, so it became the portable format. Import, export, and whole-map replace.
  The parser accepts headings, bullets, mixed indentation, checkboxes, inline
  emphasis and code fences, and falls back to bullets past h6.
- **AI chat editing.** "Add a branch about risks" rewrites the map. This one
  deliberately does not use JSON — the map has a faithful text form, so the
  model gets markdown and returns markdown, which small local models handle
  reliably where JSON needs a repair round. ~5s on `qwen2.5:7b-instruct`.
- **Safety on whole-tree rewrites.** Every chat edit snapshots first, labelled
  with the instruction. A reply returning under 40% of the previous node count
  is rejected — the signature of a model that returned only the fragment it
  changed — unless the instruction itself asked to delete or simplify.
- **Per-branch colour** inherited down through nodes and edges, so a branch
  stays traceable in radial layout.
- **Node checkboxes** that survive export as `[x]` task markers.
- **Documents → Mind map.** Generated specs are already heading-structured
  markdown, so a spec becomes a navigable map with no conversion step.
- **Generation quality rules.** The map-generation prompt now asks for concrete,
  fact-carrying titles over category labels, and forbids essay scaffolding.

### Navigation fixes

- **Two of five sidebar verbs opened on a "coming soon" card.** `/automate`
  redirected to `/skills` and `/develop` to `/terminal`, both unbuilt, while
  working tabs sat one along. They now land on `/command` and `/logs`.
- **Live tabs now lead** their sections, so no strip starts with a stub.
- **Unknown routes redirect home** — previously they rendered the app chrome
  around an empty page.

### Cleanup

- Removed dead `src.graph.graph` imports from `routes.py`, `wizard.py` and
  `yolo.py`. All three imported six symbols and used none.

### Toolbar

The mind-map toolbar got **smaller** while gaining capability: New / Import /
Duplicate / Delete collapsed into one menu, and everything new went behind a
single Outline panel rather than more buttons.

### Tests

42 new (70 → 112): outline parsing, DB round-trip, HTTP layer, and chat-edit
guards against real small-model failure modes (truncation, prose preamble, code
fences).

---

## A licensing decision worth recording

The session began with a request to use code from
[Mind Map Wizard](https://github.com/linus-sch/Mind-Map-Wizard). **It is
CC BY-NC 4.0 and none of its code is here.**

Copying it would have breached the upstream licence (Dobby is commercial), made
this repository's MIT `LICENSE` inaccurate for those files, and created exposure
in any diligence review. The capabilities were rebuilt from scratch instead —
features and ideas are not copyrightable, only their expression. Full reasoning
in [docs/MINDMAP_INTERCHANGE.md](docs/MINDMAP_INTERCHANGE.md).

Anyone wanting their actual code commercially should contact
`contact@mindmapwizard.com`, which their licence explicitly invites.

---

## What is pending

Summarised here; the full list with estimates is in
[FEATURE_TRACKER.md](FEATURE_TRACKER.md).

### Unbuilt features (10 stub surfaces)
Terminal · Skills · Flows · Marketplace · Prototypes · Video · Transcribe ·
YouTube · Notes · Control

### Structural debt
1. **~950 lines of dead backend code.** `src/audit/` (484 L) and `src/graph/`
   (448 L) are complete, coherent modules that nothing calls. `src/utils/` has
   no `__init__.py`. Decide: delete or wire up.
2. **The two core pipelines are untested.** `wizard.py` and `yolo.py` execution
   paths have no coverage, despite being what the product does.
3. **18 progress notes clutter the repo root.** `PHASE_*`, `ARCHITECTURE_*`,
   `BUILD_SUMMARY` — history, not documentation.
4. **Desktop shell is dev-grade.** No tray, unsigned, no updater.

### Open questions
See tracker §6. The most important: **which codebase is Dobby?** This repo, or
the rebranded OpenWorker fork in `~/Downloads/openworker-main` — which is **not
a git repository and is not pushed anywhere**. That work exists on one disk only.

---

## Recommended direction

**Menu:** keep the five verbs. That structure is right and should stop moving.
The problem was never the sidebar — it was that half the tabs underneath were
empty. Consider hiding planned surfaces behind a roadmap view instead of
advertising ten "coming soon" cards.

**Look and feel:** no rework needed. The visual language is consistent. Spend
the effort on onboarding instead — a first-run user has no idea whether to pick
Wizard, YOLO, or Bulk.

**Evolution, in order:**

1. **Finish Terminal.** It is the main reason to leave the app today.
2. **Build Skills, then Flows.** Document generation is commoditised; a local,
   private, extensible automation surface is not. This is the moat.
3. **Then media capture** (transcribe → YouTube → notes). This is the
   daily-use hook — the "toothbrush test" the 100-day roadmap was built around.
4. **Marketplace last.** It needs things worth installing.

Do these one at a time and finish each. The app currently has more started
than finished, and the ratio is the main thing holding it back.

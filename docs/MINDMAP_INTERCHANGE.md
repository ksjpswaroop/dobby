# Mind map: outline interchange & AI editing

## Provenance — why we did not use Mind Map Wizard's code

[Mind Map Wizard](https://github.com/linus-sch/Mind-Map-Wizard) was evaluated as a
source of code for this feature. **It is licensed CC BY-NC 4.0 (Attribution –
NonCommercial), and none of its code is used here.**

Three reasons that mattered:

1. **NonCommercial.** Dobby has a commercial plan (paid tiers, a marketplace
   take-rate). Incorporating CC BY-NC code would breach the licence.
2. **Licence incompatibility.** Dobby ships under MIT. CC BY-NC code cannot be
   relicensed as MIT, so the repository's own `LICENSE` would become inaccurate
   for those files — a problem in any diligence review.
3. Creative Commons licences are not designed for software: no patent grant, no
   source/object distinction.

What *was* taken is the set of ideas — which are not copyrightable — after
reviewing its published feature list: heading-markdown as the interchange
format, chat-based editing, checkboxes, and per-branch colouring. Every line
here is original. Anyone wanting to use their actual code commercially should
contact `contact@mindmapwizard.com`, which their licence explicitly invites.

## The outline format

Heading markdown is the closest thing to a lingua franca for mind-mapping tools
— markmap, Obsidian's outline view, Logseq, and most "text to mind map"
generators all read it. Using it as our interchange format means a Dobby map
opens elsewhere, and an outline written anywhere imports here.

```markdown
# Map title
## A branch
Prose under a heading becomes that node's description.
### A child
- [x] a completed leaf
- another leaf — with a description after the dash
```

Rules the parser follows:

| Input | Becomes |
|---|---|
| First `#` | The map title (not a node) |
| `##` … `######` | Nodes at depth 1–5 |
| Later `#` headings | Top-level branches (some tools emit every branch as h1) |
| `-` / `*` / `+` bullets | Nodes nested under the current heading, 2 spaces per level |
| `[x]` / `[ ]` after the marker | Checked state |
| ` — text` after a title | That node's description |
| Any other prose | Appended to the open node's description |
| Fenced code blocks | Ignored entirely |

Beyond h6 the exporter falls back to indented bullets, so arbitrarily deep maps
still round-trip.

**Round-trip guarantee:** `parse(render(tree))` reproduces titles, hierarchy,
descriptions and checked state. Node ids and cross-branch links do *not* survive
— JSON export remains the lossless format.

Unchecked nodes emit no `[ ]` marker, so a map that never uses checkboxes stays
clean for other tools.

## AI chat editing

`POST /api/v1/mindmaps/ai/chat/{map_id}` with `{"instruction": "..."}`.

Unlike every other AI call in this codebase, this one **does not use JSON**. The
map has a faithful plain-text form, so the model is given markdown and asked for
markdown back. A 1.5B local model handles that reliably where it would need a
repair round for JSON, and a partially-mangled outline still parses into a usable
tree rather than failing wholesale. Measured at ~5s on `qwen2.5:7b-instruct`.

Safety, because the edit rewrites the whole tree:

- Every edit **snapshots first**, labelled with the instruction, so it is
  revertible from the panel.
- A reply returning **under 40% of the previous node count** is rejected
  outright — this is what a model does when it ignores "output the COMPLETE
  outline" and returns only the fragment it changed. The check is skipped when
  the instruction itself asks to delete, trim, or simplify, and for maps under
  5 nodes where there is no meaningful baseline.
- Unparseable output changes nothing.

Note that the client-side undo stack cannot serve here: it replays edits onto
surviving nodes and cannot resurrect deleted ones. The panel's "Undo that" calls
the server's snapshot restore instead.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/map/{id}/export/outline` | Map as heading markdown |
| `POST` | `/import/{project_id}/outline` | New map from pasted markdown |
| `PUT` | `/map/{id}/outline` | Rewrite a map from edited text (snapshots first) |
| `POST` | `/ai/chat/{map_id}` | Natural-language edit |
| `GET` | `/map/{id}/snapshots` | Restore points |
| `POST` | `/map/{id}/restore/{snapshot_id}` | Revert |

## Where it shows up

- **Mind Map → Outline panel.** Two tabs: *Ask* (chat editing with suggestion
  chips) and *Outline* (the whole map as an editable textarea, with Copy/Apply).
- **Documents → Mind map.** Generated docs are already heading-structured
  markdown, so a spec becomes a navigable map with no conversion step.
- **Map → Import a file…** `.json` round-trips losslessly; anything else
  (`.md`, `.txt`) is parsed as an outline.
- **Export → Markdown outline (portable)** for taking a map elsewhere.

## Branch colour

One hue per top-level branch, inherited by all descendants, applied to both node
borders and edges. This is what makes a radial map readable: colour identifies a
node's branch even when it has drifted far from its parent. Fixed hex values
rather than theme tokens, because the palette must stay mutually distinguishable
in both light and dark mode. An explicit per-node `color` overrides it.

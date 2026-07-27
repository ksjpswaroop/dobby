# Dobby — User Guide

Dobby turns a half-formed idea into a complete, verified set of engineering
documents, and then keeps those documents alive as you work. Everything runs
on your machine: your ideas, drafts, and research never leave it unless you
explicitly turn on a web-search provider.

This guide covers every feature that currently ships. It is organised by what
you are trying to do, not by menu structure.

---

## Contents

1. [Getting started](#getting-started)
2. [The daily loop](#the-daily-loop) — the habit Dobby is built around
3. [Capturing ideas](#capturing-ideas)
4. [Generating documents](#generating-documents)
5. [Editing documents](#editing-documents) — the editor in depth
6. [The AI copilot](#the-ai-copilot)
7. [Prioritising work](#prioritising-work)
8. [Research](#research)
9. [Mind maps](#mind-maps)
10. [Automations & the Inbox](#automations--the-inbox)
11. [Models & performance](#models--performance)
12. [Keyboard shortcuts](#keyboard-shortcuts)
13. [Settings reference](#settings-reference)
14. [Troubleshooting](#troubleshooting)

---

## Getting started

**You need Ollama running** with at least one model pulled:

```bash
ollama pull llama3.2
```

Start the backend, then the UI:

```bash
cd /Users/swaroop/projects/09-dobby && source .venv/bin/activate && python -m uvicorn src.main:app --port 8000
```

```bash
cd /Users/swaroop/projects/09-dobby/tauri-app && npm run dev
```

Open `http://localhost:1420`. A default project is seeded automatically, so
there is nothing to configure before you start.

**First run.** Today Home shows an onboarding checklist. Its steps tick
themselves off from real data as you use the app — it cannot tell you a step
is done when it isn't. Dismiss it whenever you like.

---

## The daily loop

Dobby is designed around opening it once a day and leaving with something
done. Today Home (`/`) is built for that in a deliberate order:

1. **Momentum** — your streak and a 14-day sparkline.
2. **Do this next** — the single most valuable thing, with a real reason.
3. **Pinned** — what you are actively working on.
4. **Today's slice** — ideas waiting to be triaged, work in flight.

### Reading the streak

Your streak counts consecutive days on which you did something that counts:
captured an idea, triaged one, generated a document, ran a verifier, or ran
research. Passive browsing does not count.

- Days are **your local days**, not UTC. Something at 11:59pm and something at
  12:01am are two different days, as they should be.
- Several actions on one day count that day **once**.
- If you haven't built *today* but did *yesterday*, the streak still shows.
  It is not broken until you miss a full day. The copy never scolds you — a
  habit surface that makes you feel bad is one you stop opening.

### "Do this next"

This card recommends one thing and tells you why. The **reason is always
computed** from your actual state, never invented. Priority order:

| Signal | Why it ranks there |
|---|---|
| Pending approval | Work is *parked* waiting on you — blocking beats valuable |
| Failed run | Something you started didn't finish |
| Failed verification | A document didn't meet its bar |
| Untriaged ideas | Captured but not yet turned into anything |
| Unresolved comments | Notes you left yourself are still open |
| Documents in review | Waiting on a decision |
| High-Pareto unstarted | The best value-per-effort work available |
| Missing documents | Features prioritised but nothing written |

If a local model is available, the sentence is rephrased to read naturally. If
not, you get the computed sentence and a small **computed** badge. Either way
the facts are the same.

---

## Capturing ideas

The whole point is that capturing costs you nothing. There is one required
field: the text.

### Quick capture — ⌘I

Press **⌘I** from anywhere in Dobby. Type. Press **Enter**. The overlay closes
and you are back exactly where you were.

> This works from any Dobby page, but only while Dobby is focused. A true
> OS-wide hotkey (capture while in another app) is not shipped yet.

### The Idea Inbox — `/ideas`

Four tabs: **Inbox**, **Backlog**, **Research**, **Archived**.

Everything lands in Inbox. From there each idea has three actions:

- **Backlog** — becomes a real backlog feature, Pareto-scored 5/5/5 by
  default. Adjust the scores later, or let the AI propose them.
- **Research** — creates a research brief on that topic, *pending*. It does
  not start automatically; you choose when to run it.
- **Archive** — out of the way, still findable.

**Nothing is ever deleted by triage.** The original capture stays, marked with
what it became, so "what did I capture, and what happened to it" is always
answerable.

You can also capture inline at the top of the Ideas page — **⌘Enter** submits.

### Pinning

Click the pin icon on any idea, backlog item, or document. Pinned things
appear in the **Pinned** strip on Today Home. Reorder with the ← / → buttons
(deliberately not drag-only, so it works from the keyboard). If you pin
something and later delete it, the pin cleans itself up.

---

## Generating documents

Three modes, same engine, different amounts of control.

### Wizard — `/wizard`

Step-by-step through all seven artifacts, with a review gate at each stage.
Use this when the feature matters and you want to steer.

### YOLO — `/yolo`

All seven artifacts in one pass, then accept or reject. Use this when you want
a complete first draft to react to. Roughly 5 minutes on a local model.

### Bulk — `/bulk`

Paste many ideas, generate every document for all of them. Use this when
seeding a new project.

**The seven artifacts:** Feature Spec, User Stories, Functional Analysis,
Flowchart, Pseudocode, TDD Tests, Documentation.

### Custom document types

Beyond the built-in seven you can define your own — an ADR, release notes, a
retro. A custom type specifies:

- **Sections** it must contain
- **A generation prompt**
- **Verification rules** — minimum word count, required sections, and whether
  placeholder text (`TODO`, `TBD`, `FIXME`, `Lorem ipsum`) fails the check

Custom types then get their own deterministic verifier, so "is this document
actually finished" has a real answer rather than a vibe.

---

## Editing documents

Open `/documents`, pick one, click **Open editor**.

The editor is a split pane: **raw Markdown on the left, live preview on the
right**. The right pane also hosts four tabs — Preview, Versions, Comments,
Links.

### Autosave and version history

Edits save automatically about a second after you stop typing. The header
shows `Unsaved → Saving… → Saved`.

**Every content change writes an immutable snapshot first.** That includes
manual edits, AI section regeneration, inline refine, and restores. This is
what makes the AI features safe to use casually: nothing they do is
unrecoverable.

In the **Versions** tab each entry shows what kind of change it was:

```
v3   refine     4:12 PM · 340w · refined 82 chars
v2   restore    3:58 PM · 7w   · before restoring v1
v1   edit       3:58 PM · 353w
```

- **Diff** shows a colour-coded unified diff against the current text.
- **Restore** brings back that version — and is *itself* snapshotted, so you
  can undo an undo.

### Regenerating one section

In the **Preview** tab, scroll to "Regenerate a section". Each heading is
listed with its word count and a **Redo** button. Only that section is
rewritten; everything else stays byte-identical.

The model gets the rest of the document as context so voice and terminology
stay consistent, but it can only replace the one section. If it drops the
heading, the heading is put back.

### Inline AI refine

1. Select some text in the left pane
2. The refine bar activates: **Shorten · Expand · More formal · Plainer**
3. You get a **preview** with a word-count delta (e.g. `84 → 51 words`)
4. **Apply** or **Discard**

Nothing is written until you Apply. Applying also re-anchors any comments
whose positions shifted.

### Comments

Select text, open **Comments**, write a note. Comments anchor to character
offsets *and* remember the text they were written against — so when you edit
text above them, they are re-found by content rather than silently drifting
onto the wrong sentence.

**Resolve** / **Reopen** / delete. Deleting a comment deletes its replies too.
The open-comment count shows in the document header and feeds "Do this next".

### Status workflow

Every document moves **Draft → In Review → Approved**.

- Draft can only go to In Review.
- In Review can go forward to Approved or back to Draft.
- **Approved can only go back to In Review — never straight to Draft.** That
  would quietly erase the fact it was ever reviewed.

Every transition is timestamped and kept, so you can see how a document
matured.

### Wiki links and tags

Type `[[Some Document Title]]` anywhere in the content. The **Links** tab
shows:

- **Links out** — resolved links are clickable; unresolved ones are listed as
  unresolved rather than hidden, so a typo is visible
- **Backlinks** — every document that links *to* this one

Tags go in the chip row under the title. Type a name, press Enter. A leading
`#` is stripped, so `#v1` and `v1` are the same tag. Use them for orthogonal
slices — `#frontend`, `#v1`, `#blocked` — alongside the Pareto backlog.

### Summarize

The **Summarize** button in the header gives you 3–5 bullets of what actually
matters in the document.

---

## The AI copilot

Open `/copilot`.

### Asking questions

Ask anything about your work. Answers are built **only** from your own
documents, and every answer carries numbered citations you can click through
to the source document.

```
Q: What does the audit log export feature do?

A: The Audit Log Export feature allows users to export historical audit logs
   of a product in CSV format for compliance checks and audits [1]. The
   generated CSV report includes timestamps, user IDs, change types, and
   affected fields [4][5].

   SOURCES  [1] Feature Spec  [2] Audit log export  [4] Functional Analysis
```

If your documents don't contain the answer, the copilot says so rather than
filling the gap. That is deliberate — an answer you can't trace is worse than
no answer.

### Project vs global scope

The toggle at the top switches between:

- **This project** — retrieval limited to the current project, and the top
  backlog items are included as context
- **All projects** — retrieval spans every project on the machine, and
  citations show which project each source came from

Use global scope for portfolio questions: *"which projects still lack an API
contract?"*, *"where did I use SQLite?"*

### Threads

Chats persist. The first question you ask becomes the thread's title, so your
history stays navigable. Delete a thread with the bin icon.

---

## Prioritising work

### The Pareto backlog — `/backlog`

Every feature is scored on **impact** (value if built), **effort** (work
required), and **risk** (chance it goes wrong), each 1–10.

```
Pareto score = (impact × 0.6) − (effort × 0.3) − (risk × 0.1)
```

The backlog sorts by that score. Sort by created date or title instead from
the dropdown.

### Letting the AI propose scores

Ask for a suggestion on any feature. The model reads the feature and any
documents that mention it, then proposes impact/effort/risk with a written
rationale and a confidence figure.

**It changes nothing.** You see the current and suggested scores side by side,
with both Pareto totals, and you either:

- **Accept** as-is
- **Accept with edits** — override any of the three numbers
- **Reject**

Only on Accept does the real backlog change. Scores outside 1–10 are clamped;
if the model returns something unparseable you get an error rather than a
guess.

---

## Research

Open `/research`. Give it a topic and optional context ("focus on the EU
market", "we're B2B").

Research runs several tracks and produces a brief with evidence. Findings can
be promoted into backlog features.

**Web search is off by default.** Dobby makes no network calls beyond your
local model until you choose a provider in Settings:

| Provider | Where queries go |
|---|---|
| `none` (default) | Nowhere — local reasoning only |
| `wigolo` | A local daemon you run yourself |
| `searxng` | Your own self-hosted instance |
| `tavily` / `brave` | **A third party** — the UI says so before you enable it |

Content fetched from the web is treated as untrusted: suspicious instruction-
like phrases are flagged and quoted rather than acted on, and the source is
marked `[flagged]` in the evidence list.

---

## Mind maps

Open `/mindmap`. Fully shipped across three phases:

- **Canvas** — pan, zoom, minimap, node inspector, keyboard shortcuts,
  drag-to-reparent, persistence
- **AI** — generate a map from a session, expand a node, regroup the whole
  map, or edit it by chat instruction
- **Export/import** — JSON, Markdown, Mermaid (server-side), PNG and SVG
  (rendered from the canvas), plus validated import

You can also turn any document's headings straight into a mind map from the
**Mind map** button in the document list.

---

## Automations & the Inbox

### Automations — `/automations`

Schedule work with cron expressions. The scheduler lives inside the app
process, because a desktop app that is sometimes closed cannot rely on a
separate daemon. On restart it catches up anything that came due while you
were away, once — not once per missed occurrence. Overlapping runs are
skipped rather than queued.

### The Inbox — `/inbox`

When something consequential needs permission — running a shell command,
reaching a host, sending a message, writing outside the project — it becomes
an **ask** in your Inbox.

Three principles:

- **Parked, not blocking.** An ask is a database row first. A question raised
  by a background job at 3am is still answerable at 9am.
- **Silence is never consent.** An unanswered approval times out as *denied*.
- **Grants are narrow.** When you say "remember this", you grant exactly one
  capability for one target — never "trust this agent".

You can mirror new asks to Slack or Telegram from Settings. Configuring the
mirror *is* the consent for those notifications.

---

## Models & performance

### Choosing models per task — `/settings`

You can route each kind of work to a different model:

`generate · chat · summarize · prioritize · refine · regenerate_section ·
research · embed · other`

The typical pairing is a small fast model for chat and a larger one for
document drafts. Any task you don't route falls back to your default model.

### Usage dashboard — `/usage`

Every model call is logged automatically — task type, model, latency,
estimated tokens, and whether it failed.

```
Calls 42 · Tokens (est.) 61,204 · Avg latency 8.1s · Compute (est.) $0.0031
```

Two honesty notes the UI states plainly:

- **Token counts are estimated** (~4 characters per token) because local
  runtimes don't report usage.
- **Cost is estimated** from time × power × electricity rate, because local
  inference has no invoice. Both the wattage and the rate are configurable in
  Settings — a laptop and a workstation differ by an order of magnitude.

The useful signal is *relative*: which task type and which model are actually
eating your afternoon. Failed calls are logged too, so a model that keeps
timing out shows up rather than vanishing.

### Prompt library

Dobby's built-in prompts are visible and forkable. Built-ins are read-only —
**fork one to change it**. A fork remembers where it came from, so you can
diff your version against the original and see exactly what you changed.

Prompts declare variables as `{{name}}`. Rendering validates that every
declared variable has a value, so a typo fails loudly instead of sending the
model a literal `{{contxt}}`.

---

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| **⌘K** | Command palette — run actions, switch models, search everything |
| **⌘I** | Quick capture an idea from anywhere |
| **⌃`** | Toggle the terminal drawer |
| **⌘Enter** | Submit (inline capture, quick capture) |
| **Enter** | Send (copilot, quick capture) |
| **Shift+Enter** | Newline instead of send |
| **Esc** | Close any overlay |
| **↑ ↓ / Enter** | Navigate and run in the palette |

---

## Settings reference

Open `/settings`.

| Setting | What it does |
|---|---|
| Ollama host / model | Where the local model lives and which is the default |
| Theme | Light, dark, or follow the system |
| Verification threshold | Score a document must hit to pass (default 85) |
| Search provider | Off by default — see [Research](#research) |
| Model routes | Per-task model assignment |
| Power / electricity rate | Basis for the local compute-cost estimate |
| Shell allowlist | **Empty by default.** Nothing runs until you opt a program in — program names only, never whole command lines |
| Workspace root | Which directory the terminal may work in |
| Extra providers | OpenAI-compatible base URL (covers LM Studio, llama.cpp, vLLM, OpenRouter) and Anthropic |
| Inbox mirroring | Send new approvals to Slack or Telegram |
| License | Activate, check status, re-verify, deactivate |

---

## Troubleshooting

**The UI loads but everything is empty.**
The backend isn't running, or isn't on port 8000. Check
`curl http://localhost:8000/health`.

**Generation fails or hangs.**
Check Ollama is up (`ollama list`) and that the model named in Settings is
actually pulled. The `/usage` dashboard records failed calls with their error.

**The copilot says it can't find anything.**
Retrieval is keyword-based over your documents. If a project has no generated
documents yet, there is nothing to ground an answer in. Generate documents
first, or switch to global scope.

**A comment points at the wrong text.**
Comments re-anchor by content when you edit. If the text a comment was written
against was deleted entirely, the comment keeps its old position and is
flagged rather than removed — the note itself may still matter.

**"Cannot go from draft to approved".**
That is intentional. Send it to review first.

**Transcription rejects my file.**
Supported: `.wav .mp3 .m4a .mp4 .aac .flac .ogg .opus .webm .mov .mkv`.
Convert others first — e.g. `afconvert -f WAVE -d LEI16 in.aiff out.wav` on
macOS. Most formats also need `ffmpeg` installed.

**A terminal command is refused.**
The shell allowlist is empty by default. Add the program name in Settings.
This is a deliberate default, not a bug.

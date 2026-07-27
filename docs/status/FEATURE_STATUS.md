# Dobby — Feature Status & Test Evidence

**As of 2026-07-27** · branch `feat/dobby-v2-workbench` · 823 backend tests passing

This document records every shipped feature, how to test it yourself step by
step, and the actual output captured when it was verified. Commands are
copy-pasteable. Where a result is quoted, it is real output from this machine,
not an illustration.

> **On screenshots.** Visual verification was performed live in the in-app
> browser against the running dev server. Because those captures are not
> written to disk, this document gives the exact navigation steps and the
> observable result for each screen instead, so any claim here can be
> re-checked in under a minute. Where a UI state is described ("shows a
> 3-day streak"), that is what was actually on screen.

---

## How to run everything

```bash
cd /Users/swaroop/projects/09-dobby && source .venv/bin/activate && DOBBY_DISABLE_AUTH=1 python -m uvicorn src.main:app --host 0.0.0.0 --port 8000
```

The UI runs separately on port 1420 (`npm run dev` inside `tauri-app/`, or the
in-app preview). The backend must be up first; the UI falls back to an error
state rather than silently showing stale data.

Full test suite:

```bash
cd /Users/swaroop/projects/09-dobby && source .venv/bin/activate && python -m pytest tests/ -q
```

Captured result: `823 passed, 1985 warnings in 19.47s`

---

## Scorecard

| Phase | Days | Status |
|---|---|---|
| 1 — Daily Home & Frictionless Capture | 1–10 | **10/10 done** |
| 2 — Living Documents | 11–20 | **10/10 done** |
| 3 — AI Copilot | 21–30 | **9 done, 1 partial (D29)** |
| 4 — Capture++ & Multimodal | 31–40 | 1/10 (D31 Transcribe) |
| 5 — Planning & PM | 41–50 | not started |
| 6 — Integrations | 51–60 | 1/10 (D56 superseded) |
| 7 — Collaboration & Sharing | 61–70 | not started |
| 8 — Habit, Delight & Retention | 71–80 | not started |
| 9 — Quality, Trust & Power | 81–90 | not started |
| 10 — Scale, Ecosystem & Ritual | 91–100 | not started |

Separately, the `OW · Features` parity tracker stands at 45 Done / 7 Partial /
2 Planned / 1 N/A, and the `Feature · Mind Map` module is fully shipped across
all three of its phases.

---

# Phase 1 — Daily Home & Frictionless Capture

## D1 · Today Home

**What it is.** One endpoint assembling today's actionable slice — ideas to
triage, work in flight, top backlog item.

**Test it**

1. Open `http://localhost:1420/`
2. Look for the "Good afternoon / Here's today's actionable slice" card.

**Verified result.** Card renders with an "Ideas to triage (1)" section listing
the actual captured idea, clickable through to `/ideas`.

```bash
curl -s http://localhost:8000/api/v1/dashboard/today/default-project | python3 -m json.tool
```

---

## D2 · Quick Capture (⌘I)

**What it is.** An in-app overlay to capture a thought from any page without
losing your place.

> **Honest scope note.** The roadmap asked for an OS-global hotkey. This is an
> *in-app* global hotkey — it works from every page in Dobby, but not when
> Dobby is in the background. A true OS-level hotkey needs Tauri capability
> work that is deferred alongside reveal-in-Finder.

**Test it**

1. Open any page, e.g. `http://localhost:1420/backlog`
2. Press **⌘I** (Ctrl+I on Windows/Linux)
3. Type anything, press **Enter**

**Verified result.** Overlay opened over the Backlog page, accepted
"captured via quick-capture hotkey from the backlog page", toasted "Idea
captured", closed itself, and the idea appeared in the Idea Inbox.

---

## D3 · Idea Inbox & Triage

**What it is.** The lowest-friction object in the app: one required field.
Triage promotes an idea into a Pareto-scored backlog feature or a research
brief. The idea is never deleted, only marked.

**Test it**

```bash
# capture
curl -s -X POST http://localhost:8000/api/v1/ideas \
  -H "Content-Type: application/json" \
  -d '{"project_id":"default-project","text":"smoke test idea via curl"}'
```

Then open `http://localhost:1420/ideas`, click **Backlog** on that row, and
open `http://localhost:1420/backlog`.

**Verified result.** The idea appeared in the real backlog as
`smoke test idea via curl`, category `idea`, Pareto `1.00`
(= 5×0.6 − 5×0.3 − 5×0.1). Triaging to Research instead created a real
`ResearchBrief` with `status: pending`, ready to run — created but not
auto-run, matching the propose-don't-act pattern used elsewhere.

---

## D4 · Command Palette (⌘K)

Already shipped before this cycle. Press **⌘K** anywhere.

---

## D5 · Daily Streak & Momentum

**What it is.** Consecutive-days streak plus a 14-day sparkline on Today Home.

**Two design decisions worth knowing.** Activity is derived from the Activity
Timeline feed, *not* `AuditEntry` — the audit log only ever recorded node
create/update/verify, never idea captures, runs, or research, which are
exactly the qualifying actions a build streak should reward. And day
boundaries use a UTC offset supplied by the browser, because a streak is a
local-calendar concept: 11:59pm and 12:01am are different days to a person
and the same day to UTC.

**Test it**

```bash
curl -s "http://localhost:8000/api/v1/momentum/project/default-project?tz_offset_minutes=330" | python3 -m json.tool
```

**Verified result (real output):**

```json
{ "streak": 2, "active_today": false, "longest_recent": 2,
  "total_active_days": 2, "tz_offset_minutes": 330,
  "sparkline": [ ... {"date":"2026-07-26","count":17},
                     {"date":"2026-07-27","count":7} ... ] }
```

At `tz_offset_minutes=330` (IST) "today" was already 07-28, so `active_today`
is correctly `false` while the streak stays alive at 2 via the yesterday
grace. In the browser's own timezone the card read **"3-day streak — You've
built today. Nice."**

**Edge cases covered by tests** (`tests/test_momentum.py`, 21 tests): same-day
actions counting once, a one-day gap resetting the streak, the 11:59pm/12:01am
boundary, negative offsets rolling backward, and a brand-new user seeing 0.

---

## D6 · Morning Briefing

Superseded — the Automations "digest" action plus Today Home cover this.

## D7 · Activity Timeline

**What it is.** A reverse-chronological feed across ideas, backlog, runs, and
research, with category filters, cursor pagination, and deep links.

**Test it**

1. Open `http://localhost:1420/activity`
2. Click the **Runs** filter
3. Click any event

**Verified result.** Events grouped under "TODAY" with icons and timestamps.
The Runs filter narrowed to shell runs only. Clicking a finished run navigated
to `/logs` and highlighted the matching row.

```bash
curl -s "http://localhost:8000/api/v1/timeline/project/default-project?limit=5" | python3 -m json.tool
```

## D8 · Pins & Favorites

**Test it.** Open `/ideas`, click the pin icon on a row, then open `/`.

**Verified result.** Pinned item appeared in the "Pinned" strip on Today Home.
Reordering is ←/→ buttons rather than drag-only so it is keyboard-operable.
A pin whose target is later deleted is cleaned up the next time the list is
read, rather than showing a broken row.

## D9 · Global Full-Text Search

Already shipped. Press **⌘K** or open `/search`.

## D10 · First-Run Onboarding

**Verified result.** Checklist appears on Today Home for a fresh install with
step state derived from real data — it cannot disagree with the app. The only
stored state is whether it was dismissed.

---

# Phase 2 — Living Documents

All ten features share one foundation: **no content change reaches a node
without a snapshot being written first**, so "can I undo this?" has one answer
everywhere.

## Full editor walkthrough

1. Open `http://localhost:1420/documents`
2. Select any document, click **Open editor**
3. You land on `/documents/:nodeId`

**Verified result.** Split pane: raw Markdown left, live rendered preview
right. Header showed `draft · feature · 353 words · v2 · 1 open comments ·
Saved`, with tabs Preview / Versions / Comments (1) / Links.

### D11 Editor + D17 Live preview

Type in the left pane. Autosave fires 1.2s after you stop; the header flips
Unsaved → Saving… → Saved. The preview re-renders as you type.

The Markdown renderer is hand-written and **escapes every character before
applying formatting**, because document content can come from a local model or
an imported file. A library configured wrong fails open; this fails closed.
`javascript:` URLs in links degrade to plain text.

### D12 Targeted section regeneration

In the Preview tab, scroll to "Regenerate a section" and click **Redo** on one
section. Only that section is replaced.

Section parsing tracks code fences, so a `#` inside a shell example is never
mistaken for a heading — which would split the document at the wrong place and
make regeneration overwrite the wrong text. This is covered by
`test_hash_inside_code_fence_is_not_a_heading`.

### D13 Version history & diff — **fully verified end-to-end**

```bash
NODE=4e753d35-f58d-4a37-9aab-7beb67716814   # any real node id

# 1. replace the whole document
curl -s -X PUT "http://localhost:8000/api/v1/documents/$NODE" \
  -H "Content-Type: application/json" \
  -d '{"content":"# Edited\n\nThis replaced the whole doc."}'

# 2. list versions
curl -s "http://localhost:8000/api/v1/documents/$NODE/versions"

# 3. diff  4. restore
curl -s -X POST "http://localhost:8000/api/v1/documents/$NODE/versions/$VER/restore"
```

**Captured output:**

```
1. edit     -> words: 7    versions: 1   dirty: True
2. versions -> v1 edit 353w
3. diff     -> +2 -23 lines
4. restore  -> restored words: 353  sections: 5
```

The original 353-word document with all five sections came back intact.
In the UI the Versions tab showed:

```
v2   restore   7/27/2026, 7:34:08 PM · 7w · before restoring v1   [Diff] [Restore]
v1   edit      7/27/2026, 7:34:08 PM · 353w                       [Diff] [Restore]
```

Note `v2 restore` — **restoring is itself snapshotted**, so a restore is undoable.

### D14 Inline AI refine

Select text in the editor. The refine bar activates with Shorten / Expand /
More formal / Plainer. Output is shown as a **preview with a word-count delta**
before you Apply — an AI rewrite you cannot inspect first is one you stop
trusting. Applying re-anchors comments whose offsets shifted.

### D15 Comments & annotations

Select text, open the **Comments** tab, write a note, Add comment.

**Verified:** a comment anchored to offsets 2–10 captured `anchor_text` of
`'# Overvi'`. When text is later inserted above it, `reanchor_comments` finds
the anchor by content and moves the offsets. A comment whose anchor text is
gone entirely keeps its old offsets and is reported as orphaned rather than
deleted — the note may still be the useful part.

### D16 Status workflow

```bash
curl -s -X POST ".../documents/$NODE/status" -d '{"status":"in_review"}'   # 200
curl -s -X POST ".../documents/$NODE/status" -d '{"status":"approved"}'    # from draft: 409
```

Transitions are enforced: draft→in_review→approved, and **approved can never
fall straight back to draft** — that would discard the fact it was reviewed.
Every transition is appended to `status_history` with a timestamp.

### D18 Wiki links · D19 Tags · D20 Custom types

- Type `[[Some Document Title]]`, open the **Links** tab. Resolved links are
  clickable; unresolved ones are listed as unresolved rather than hidden.
  Backlinks are computed in both directions.
- Add a tag in the header chip row. Verified: `tags: ['verified']`.
- Custom document types carry a section structure and deterministic
  verification rules (required sections, min words, no placeholder text).
  Verified: a type requiring "Highlights" and "Breaking Changes" correctly
  failed a document containing only "Highlights".

**Bug found and fixed during this work.** Deleting a comment that had replies
raised `FOREIGN KEY constraint failed` — SQLAlchemy batched both deletes into
one `executemany` whose order is not guaranteed, so the parent could go first.
Fixed with an explicit flush between. Caught by
`test_deleting_a_parent_removes_replies`.

---

# Phase 3 — AI Copilot

Every feature routes through `model_routing.call()`, which is the single place
that resolves the per-task model **and** writes telemetry — so no model call
can exist that the usage dashboard cannot see.

## D21 · Project Chat Copilot — **verified against real Ollama**

**Test it**

1. Open `http://localhost:1420/copilot`
2. Ask: *"What does the audit log export feature do?"*

**Captured output (real, local llama3.2):**

```
MODEL: default   latency: 14280 ms
ANSWER: The Audit Log Export feature allows users to export historical audit
logs of a product in CSV format for compliance checks and audits. This
facilitates transparency and accountability by providing a structured way to
track changes and activities within the product [1]. The generated CSV report
includes detailed information such as timestamps, user IDs, change types,
affected fields, and more [4][5]...
CITATIONS: [(1,'Feature Spec'), (2,'Audit log export'), (3,'Feature Spec'),
            (4,'Functional Analysis'), (5,'Documentation'), (6,'Feature Spec')]
```

In the UI the thread auto-titled itself from the question, and the six sources
rendered as clickable chips that navigate to the document.

**Why retrieval is lexical, not embeddings.** It works with zero setup on a
machine with no embedding model pulled, and it is deterministic — the same
question retrieves the same documents, which matters when the answer carries
citations the user is meant to trust.

```bash
curl -s "http://localhost:8000/api/v1/copilot/retrieve?question=audit%20log%20export&project_id=default-project"
```

**Captured ranking** — the title match correctly outranks passing mentions:

```
10.5  Audit log export
 7.5  Feature Spec
 7.5  Functional Analysis
 5.5  Flowchart
```

## D22 · Next-Best-Action

The **reason is always deterministic**; only the wording is model-phrased. If
the model is unavailable the computed sentence is shown verbatim and the card
is badged `computed`. A recommendation that invents its justification is one
you learn to ignore.

```bash
curl -s http://localhost:8000/api/v1/copilot/signals/default-project
```

**Captured output** — ordered by fixed urgency weights:

```
untriaged_ideas         w=60   Triage 1 idea
unresolved_comments     w=55   Resolve 1 comment
high_pareto_unstarted   w=40   Start: Data Encryption
```

Full ordering: pending approval (100) > failed run (90) > failed verification
(85) > untriaged ideas (60) > unresolved comments (55) > review waiting (50) >
high Pareto unstarted (40) > missing documents (30) > empty project (20).
Something *blocking* outranks something merely *valuable*.

## D23 · AI-Assisted Prioritization

The model proposes impact/effort/risk with a rationale and confidence.
**Nothing touches the backlog until you accept**, and you may edit the numbers
while accepting. Out-of-range scores are clamped to 1–10; unparseable model
output raises rather than guessing. Covered by 7 tests including
`test_suggestion_does_not_touch_the_feature`.

## D25 · One-Click Summarize

Click **Summarize** in the document editor header.

## D26 · Cross-Project Global Copilot

Same surface, **All Projects** toggle. Retrieval spans every project and
citations carry the project name.

## D27 · Prompt Library

```bash
curl -s "http://localhost:8000/api/v1/copilot/prompts?project_id=default-project"
```

**Captured:** `5 prompts: ['feature_spec','chat_grounded','prioritize_feature','summarize_document','user_stories']`

Built-ins are **immutable — fork to edit**. A fork records `forked_from`, which
is what makes "show me what I changed" and "reset to Dobby's version"
possible. Rendering validates that every declared `{{variable}}` has a value,
so a typo'd placeholder fails loudly instead of sending the model a literal
`{{contxt}}`.

## D28 · Per-Task Model Routing

```bash
curl -s http://localhost:8000/api/v1/copilot/routing
```

Map any of `generate, chat, summarize, prioritize, refine, regenerate_section,
research, embed, other` to a specific model. An unset task falls through to
the global default, so an empty map behaves exactly as before.

## D29 · Streaming Generation View — **Partial, not done**

Per-call latency and live run tracing ship (Logs & Traces, `/usage`), but real
token-by-token streaming needs a streaming transport through
`providers.generate()`. Marked `Partial` in the tracker rather than claimed.

## D30 · Token / Latency / Cost Dashboard

Open `http://localhost:1420/usage`.

**Captured output after the one real copilot call:**

```
calls: 1   tokens(est): 1843   avg: 14278 ms
by_task:  [('chat', 1, '14278ms')]
by_model: [('default', 1)]
cost_basis: {'watts': 60.0, 'rate_per_kwh': 0.15,
             'note': 'Local inference has no invoice — this is time x power x rate, an estimate.'}
```

The telemetry row was written automatically by `model_routing.call()` with no
extra wiring at the call site. **Both the cost and the token counts are
labelled as estimates in the UI**, because local runtimes report neither and a
confidently wrong number is worse than none.

---

# Phase 4 — partial

## D31 · Transcribe — verified with real audio

The whisper.cpp backend existed with full test coverage but had **no UI at
all**; this cycle wired it up.

```bash
say -o /tmp/t.aiff "Testing the new transcribe page end to end"
afconvert -f WAVE -d LEI16 /tmp/t.aiff /tmp/t.wav
# upload via /api/v1/attachments/project/default-project, then:
curl -s -X POST http://localhost:8000/api/v1/transcription/transcribe ...
```

**Captured output:**

```json
{"text":"testing the new transcribe page end to end.",
 "engine":"whisper.cpp","model":"tiny.en","duration_ms":758,"audio_seconds":2.28}
```

`.aiff` is correctly rejected as unsupported — that is the format whitelist
working, not a bug.

---

# What is not done

70 of the 100 roadmap features remain (D32–D100, minus the few superseded).
These are tracked in `Dobby_100_Day_Roadmap.xlsx` with a **Lane** column
assigning each to one of eight parallel workstreams:

| Lane | Scope | Rows |
|---|---|---|
| A | Daily Home & Capture | 20 |
| B | Documents & Editor | 10 |
| C | AI Copilot & Model Ops | 10 |
| D | Planning & PM | 10 |
| E | Integrations & Server | 20 |
| F | Habit & Delight | 10 |
| G | Quality & Trust | 10 |
| H | Scale & Ecosystem | 10 |

Lane E is the largest and the only one requiring server infrastructure
(GitHub/Jira/Linear/Notion sync, public REST API, team roles, presence,
multi-device sync).

**Known partial items** carried in `OW · Features`: per-task threads and
working folders, inline-vs-inbox routing, persona progressive disclosure,
Slack app manifest (needs external credentials), 25+ connectors, OS-level
reveal-in-Finder, and the deliberately-deferred cloud OAuth broker.

# Dobby Expansion — Build-Ready Feature Specs

This document specifies the 13 new features that evolve Dobby from a local-first document generator into a **local-first AI workbench** — one categorized desktop app to capture, generate, automate, build, and ship, fully on-device (Tauri 2 + React + FastAPI + SQLite, LLM via local Ollama/llama.cpp, bring-your-own-model, zero cloud dependency). Features are grouped under the six navigation categories and sequenced across phases P1–P6. Each spec covers overview, user value, capabilities, UX, architecture, dependencies, effort, risks, and acceptance criteria, and stays faithful to the local-first, on-device principle throughout.

Phasing summary:

- **P1 — Foundations & Findability:** Global Search, Command Center, Logs & Traces.
- **P2 — Media & Capture Studio:** Embedded Terminal, Audio Transcription, YouTube to Notes, Notes Builder.
- **P3 — Automation:** Skill Builder, Flow Builder, Control Center.
- **P4 — Build & Generate:** Prototype Builder + Test, Video Generation.
- **P5–P6 — Marketplace & Publish:** Local App Marketplace.

---

# System

## 1. Global Search (P1, M)

**Overview.** Global Search indexes every Dobby artifact — projects, the 7 generated engineering documents, backlog items, dependency-graph nodes, notes, transcripts, and run logs — into a single local index and answers queries with a blend of SQLite FTS5 full-text ranking and local vector similarity. Embeddings are produced on-device via a small local model (e.g. nomic-embed-text or bge-small through Ollama) and stored in sqlite-vec, so nothing leaves the machine. Results are typed, de-duplicated, and grouped by category with inline snippets and match highlighting. An incremental, event-driven indexer keeps the index fresh so newly generated documents are searchable within seconds.

**User value.** Builders instantly recall anything they have ever generated or captured without remembering which project or file it lived in. One keystroke jumps from a vague memory to the exact document, note, or run.

**Capabilities.**

- Hybrid ranking that fuses SQLite FTS5 BM25 scores with sqlite-vec cosine similarity.
- On-device embedding generation via a local model with batched, cached vectors.
- Incremental, event-driven reindexing on document/note/run create-update-delete.
- Typed, category-grouped results with snippet extraction and term highlighting.
- Scoped filters (by project, category, date range, document type).
- Keyboard-first result navigation with instant open/preview.
- Graceful fallback to pure full-text search when no embedding model is installed.

**UX.** A persistent top-bar search field opens an overlay panel that streams results as the user types, grouped under collapsible category headers with highlighted snippets. Arrow keys move through results and Enter opens the item in its native view; a scope chip row lets the user narrow by project or type.

**Architecture.** New FastAPI module `src/search/` owns an indexer service and a query service; storage uses SQLite FTS5 virtual tables plus a sqlite-vec extension table for embeddings. Embeddings call the local Ollama/llama.cpp embedding endpoint with an in-process LRU cache. Tauri IPC exposes `search/query` and `search/reindex` commands; the indexer subscribes to existing pipeline events to stay incremental.

**Dependencies.** None.

**Effort.** ~4 person-weeks.

**Risks.**

- Embedding model availability varies across users; must degrade to FTS-only cleanly.
- Index bloat and reindex latency on large libraries without incremental batching.
- Hybrid score normalization can surface irrelevant vector matches if weights are untuned.

**Acceptance criteria.**

- Query returns fused FTS + vector results in under 300ms on a 5k-item library.
- A newly generated document is searchable within 5s of creation.
- Results are grouped by category with correct snippet highlighting.
- Deleting an item removes it from both FTS and vector indexes.
- With no embedding model installed, search still returns full-text results without error.
- Scope filters correctly restrict results to the selected project or type.

## 3. Logs & Traces (P1, M)

**Overview.** Logs & Traces gives builders a timeline of every run in Dobby — document generations, verifier passes, skills, and flows. Each run emits a structured trace of nested spans (agent step, LLM call, tool invocation, verifier check) with timing, token counts, inputs, outputs, and status, persisted to SQLite. A live-tailing view streams spans as a run executes, and a tree/waterfall view lets users drill into any completed run to inspect prompts, model responses, and errors. Because all telemetry is local, users can debug prompt regressions and slow steps without any external observability service.

**User value.** When a generation misbehaves or a flow fails, builders can see exactly which step and prompt caused it instead of guessing. It turns opaque AI runs into inspectable, debuggable timelines.

**Capabilities.**

- Structured span model (run > agent step > LLM/tool call) with timing and token metrics.
- Live tailing of spans over an IPC/event stream during execution.
- Waterfall and tree visualizations of completed runs.
- Full prompt/response/tool-arg capture with expandable payload viewers.
- Status, error, and retry annotations per span.
- Filter and search runs by feature, project, status, and date.
- Local retention policy with size-capped pruning.

**UX.** A runs list shows recent executions with status, duration, and token totals; selecting one opens a waterfall/tree of spans that expand to reveal prompts, outputs, and errors. A live-tail toggle streams new spans in real time while a run is in progress.

**Architecture.** New `src/tracing/` module exposes a lightweight span-emitter API instrumented into the generation pipeline, verifiers, and later skills/flows; spans persist to SQLite tables (`runs`, `spans`) with JSON payload columns. A pub/sub event bus pushes span updates over Tauri IPC to the live view. A background pruner enforces retention limits.

**Dependencies.** None.

**Effort.** ~4 person-weeks.

**Risks.**

- Instrumentation overhead or payload bloat if large prompts are stored verbatim.
- Retrofitting span emission across existing pipeline code is invasive.
- Live streaming backpressure on very chatty runs.

**Acceptance criteria.**

- Every document generation produces a run with nested, timed spans.
- Live-tail view shows spans appearing within 1s of emission.
- A completed run's waterfall accurately reflects span durations and order.
- Prompt and response payloads are viewable and correctly associated with their span.
- Failed spans are visibly marked with captured error detail.
- Retention pruning caps stored trace size without corrupting recent runs.

## 4. Embedded Terminal (P2, M)

**Overview.** Embedded Terminal provides an interactive shell pane backed by a real PTY, scoped to a per-project working directory. Every command — whether typed by the user or proposed by an agent/flow — runs through an approval gate with an allowlist/denylist policy, so destructive or network operations require explicit confirmation. The PTY runs in a restricted environment (constrained cwd, scrubbed env, optional command timeouts and output caps) and streams stdout/stderr into an xterm-style view. This lets automations execute build, test, and scaffold commands locally while keeping the user in control of anything risky.

**User value.** Builders and their agents can run real commands (installs, builds, tests, git) without leaving Dobby, while approval gating prevents an automation from doing anything destructive unattended.

**Capabilities.**

- Real PTY sessions scoped to a per-project working directory.
- Approval gate with configurable allowlist/denylist and per-command confirm.
- Streaming stdout/stderr into an xterm.js terminal view.
- Restricted environment: scrubbed env vars, cwd jail, output size caps.
- Per-command timeouts and a kill/abort control.
- Agent-proposed commands surfaced for user approval before execution.
- Session history persisted per project.

**UX.** A terminal pane opens per project with a familiar shell prompt; when an agent proposes a command or a command matches a gated pattern, an inline approval banner shows the exact command and requires a click to run. Output streams live with clear success/failure indicators.

**Architecture.** New `src/terminal/` module wraps a PTY (via a Rust pty crate in the Tauri layer or a Python pty bridge) with a policy engine evaluating each command against allow/deny rules. Sessions and history persist to SQLite; the frontend uses xterm.js fed over an IPC byte stream. The environment is constrained (cwd jail, filtered env) and every gated command requires explicit user confirmation.

**Dependencies.** Logs & Traces.

**Effort.** ~5 person-weeks.

**Risks.**

- Sandbox escape or policy bypass if command parsing is naive (shell metacharacters).
- Cross-platform PTY behavior differences (macOS/Linux/Windows).
- Approval fatigue if the gate fires too often for benign commands.

**Acceptance criteria.**

- A typed command runs in the project cwd and streams output live.
- A denylisted or agent-proposed command is blocked until explicitly approved.
- Commands cannot read or write outside the configured cwd jail.
- A long-running command can be aborted and respects the configured timeout.
- Command approvals and executions appear as spans in Logs & Traces.
- Session history reloads correctly when reopening a project.

## 10. Control Center (P3, L)

**Overview.** Control Center is the governance and orchestration hub: it shows all configured agents/skills, their granted tools and permission scopes, which local models are installed and how requests route to them, and every currently running or queued automation. Users can approve or revoke tool grants, set global and per-skill permission policies (e.g. terminal off by default, network denied), pause or kill running flows, and define model-routing rules (which model handles which task class). It centralizes the approval and safety controls that individual features (terminal, skills, flows) enforce, giving one place to see and constrain what autonomous processes may do.

**User value.** Builders and team leads get one trustworthy place to see and control everything their agents can do and are doing, so autonomy never becomes uncontrolled. It makes running local automations safe and auditable.

**Capabilities.**

- Inventory of agents/skills with their granted tools and permission scopes.
- Global and per-skill permission policy editing (tool allow/deny, network, fs scope).
- Model registry view and routing rules (task class to local model).
- Live view of running/queued automations with pause and kill controls.
- Central approval queue for pending agent-proposed actions.
- Audit log of permission changes and executed sensitive actions.
- Emergency stop-all-automations control.

**UX.** A dashboard with tabs for Agents/Skills, Permissions, Models, and Running — each a table with inline toggles and controls. A live Running panel lists active automations with pause/kill, and a permissions matrix shows which skills hold which tool grants.

**Architecture.** New `src/control/` module centralizes a permission/policy store (SQLite) that the terminal, skills, and flow executors query before privileged actions, plus a runtime registry of active runs fed by the tracing/event bus. Model routing config maps task classes to Ollama/llama.cpp models. IPC exposes policy CRUD, run control (pause/kill), and the approval queue; changes are audit-logged.

**Dependencies.** Logs & Traces, Skill Builder, Flow Builder, Embedded Terminal.

**Effort.** ~7 person-weeks.

**Risks.**

- Central policy store becoming a bottleneck or single point of failure.
- Race conditions between policy changes and in-flight privileged actions.
- Complexity of routing rules confusing users into misconfiguration.

**Acceptance criteria.**

- All skills/agents and their tool grants are listed accurately.
- Revoking a tool grant blocks that tool in subsequent skill/flow runs.
- Running automations appear live and can be paused and killed.
- Model routing rules direct a task class to the configured local model.
- Pending agent-proposed actions surface in a central approval queue.
- Permission changes and sensitive actions are recorded in the audit log.

---

# Automate

## 2. Command Center (P1, M)

**Overview.** Command Center is the keyboard-driven nerve center invoked with a global shortcut from anywhere in the app. It aggregates navigation targets, generator entry points (Wizard/YOLO/Bulk), recent projects and documents, and — as later phases land — installed skills and flows into one fuzzy-searchable list of executable actions. Each action carries metadata (icon, category, argument schema) so the palette can prompt for parameters inline before dispatching to the appropriate backend command. A local usage-frequency store ranks recently and often-used actions to the top, and the same action registry powers Global Search's action results. Everything resolves against a local action registry with no network calls.

**User value.** Power users drive the entire workbench from the keyboard, cutting multi-click navigation to a single palette invocation. It becomes the fastest path to start any generation or automation.

**Capabilities.**

- Global shortcut invocation with fuzzy matching over a typed action registry.
- Inline argument prompts driven by each action's parameter schema.
- Frequency- and recency-ranked results via a local usage store.
- Dispatch to navigation, generators, and (later) skills and flows.
- Extensible action registry other modules register into at startup.
- Category-scoped modes (e.g. `>` for commands, `@` for projects).
- Recent-actions list and quick-repeat of the last command.

**UX.** A centered modal palette overlays the app on the global shortcut with a single input and a live-filtered, keyboard-navigable action list showing icon, name, and category. Selecting an action either executes immediately or expands an inline mini-form for required arguments before dispatch.

**Architecture.** New `src/actions/` module maintains an in-memory action registry populated by each feature module at startup and persisted metadata in SQLite; the frontend palette is a React overlay component. Argument schemas are JSON-schema-like and validated client-side before an IPC dispatch to the target FastAPI command. Usage frequency is stored locally to rank results.

**Dependencies.** Global Search.

**Effort.** ~3 person-weeks.

**Risks.**

- Action registry fragmentation if modules register inconsistently.
- Argument-schema UX becomes clunky for actions with many parameters.
- Keybinding conflicts with OS or WebView shortcuts.

**Acceptance criteria.**

- The global shortcut opens the palette from any screen and focuses the input.
- Fuzzy search matches action names and aliases with sub-100ms filtering.
- Executing a navigation action routes correctly; a generator action starts the flow.
- An action requiring arguments shows an inline form and validates before dispatch.
- Frequently used actions rise to the top across sessions.
- New modules can register actions without changing palette code.

## 8. Skill Builder (P3, L)

**Overview.** Skill Builder lets users define reusable AI skills: named, parameterized units that bundle a prompt template, an input/output schema, an optional set of allowed tools (e.g. terminal, file read, search), and a target model. Skills are authored in a guided editor with a live test harness that runs the skill against sample inputs and shows the trace. Each skill is versioned and stored in a local manifest so it can be invoked from the Command Center, composed inside Flow Builder, and later published to the Marketplace. This turns one-off prompting into a durable, shareable library of automations.

**User value.** Builders capture their best prompts and workflows once and reuse them everywhere, instead of retyping prompts. Skills become composable building blocks that grow into a personal automation library.

**Capabilities.**

- Guided skill editor with prompt template, input/output schema, and model selection.
- Declarative tool grants (search, file read, terminal) scoped per skill.
- Live test harness running the skill on sample inputs with trace output.
- Semantic versioning and revision history per skill.
- Local skill manifest registry consumable by Command Center and Flow Builder.
- Parameter validation against the declared input schema.
- Export/import of skill definitions for later Marketplace publishing.

**UX.** A two-pane editor shows the skill definition (prompt, schema, tools, model) on the left and a live test runner on the right where the user supplies sample inputs and inspects streamed output plus trace. A skills list manages versions and lets users duplicate or promote a skill.

**Architecture.** New `src/skills/` module defines a skill manifest schema (JSON) and an executor that binds parameters, enforces tool grants, and calls the local LLM. Skills, versions, and test cases persist to SQLite and a skills directory on disk. Execution emits spans to Logs & Traces and registers actions with Command Center; tool grants integrate with the terminal and search sandboxes.

**Dependencies.** Command Center, Logs & Traces, Embedded Terminal.

**Effort.** ~7 person-weeks.

**Risks.**

- Over-broad tool grants could let a skill do more than intended.
- Manifest schema churn breaks previously authored skills without migration.
- Test harness must faithfully mirror production execution or trust erodes.

**Acceptance criteria.**

- A user can define a skill with a prompt, typed inputs/outputs, and model.
- The test harness runs the skill and shows streamed output plus a trace.
- Invalid inputs are rejected against the declared schema before execution.
- Skills are versioned and prior versions remain runnable.
- A saved skill is invocable from Command Center and selectable in Flow Builder.
- Tool grants are enforced — a skill cannot use an ungranted tool.

## 9. Flow Builder (P3, L)

**Overview.** Flow Builder is a drag-and-drop canvas where nodes represent skills, document generators, tools (terminal, search, transcription), and control constructs (branch, loop, map, human-approval). Users wire node outputs to inputs to compose multi-step automations, then run them with live per-node status and full traces. A local flow engine executes the DAG, passing typed data between nodes, pausing at approval gates, and persisting run state so flows can resume. Flows are versioned, saved locally, and can be triggered from the Command Center or on a schedule — becoming the automation backbone of the workbench.

**User value.** Builders assemble repeatable pipelines (e.g. transcribe → notes → generate PRD → scaffold in terminal) visually, without writing glue code. Complex multi-step work runs with one click and full visibility.

**Capabilities.**

- Drag-and-drop node canvas with typed input/output ports and edge validation.
- Node types for skills, generators, tools, and control flow (branch/loop/map/approval).
- Local DAG execution engine with typed data passing between nodes.
- Live per-node status overlay and full trace integration.
- Human-in-the-loop approval nodes that pause and resume a run.
- Flow versioning, save/load, and resumable run state.
- Triggering from Command Center and (later) on a schedule.

**UX.** A zoomable canvas hosts nodes the user drags from a palette and connects by dragging between ports, with invalid connections rejected inline. A run mode overlays live status badges on each node and streams a trace panel; approval nodes surface an inline confirm before continuing.

**Architecture.** New `src/flows/` module defines a flow graph schema and a topological execution engine that invokes the skill executor, generators, and tool modules, persisting node/run state to SQLite for resumability. The frontend uses a React flow-graph library for the canvas. Execution emits per-node spans to Logs & Traces; approval nodes gate via the same confirmation pattern as the terminal. Flows register as Command Center actions.

**Dependencies.** Skill Builder, Command Center, Logs & Traces, Embedded Terminal.

**Effort.** ~8 person-weeks.

**Risks.**

- DAG execution edge cases (cycles, fan-out, partial failure) are hard to get right.
- Type mismatches between node ports cause confusing runtime failures.
- Resumable state management grows complex with loops and approvals.

**Acceptance criteria.**

- A user can build a multi-node flow by dragging and connecting nodes.
- Invalid port connections (type mismatch) are rejected at edit time.
- Running a flow executes nodes in dependency order with typed data passing.
- An approval node pauses the run and resumes on user confirmation.
- Per-node status and traces are visible during and after a run.
- A flow can be saved, reloaded, versioned, and resumed after interruption.

---

# Studio

## 5. Audio Transcription (P2, M)

**Overview.** Audio Transcription lets users import audio/video files (or record directly) and produces a timestamped, speaker-segmented transcript entirely on-device using Whisper.cpp or faster-whisper. Files are decoded via a bundled ffmpeg, chunked, and transcribed with a user-selectable model size (tiny to large) to trade speed for accuracy. Progress streams per chunk, and the finished transcript is editable, searchable (via Global Search), and can be sent straight into Notes Builder. Transcripts and their segment timing are stored locally so they can be replayed against the source audio.

**User value.** Creators and founders turn interviews, meetings, and voice memos into searchable text without paying for or trusting a cloud transcription service. Everything stays private and works offline.

**Capabilities.**

- Local STT via Whisper.cpp or faster-whisper with selectable model size.
- ffmpeg-based decoding of common audio/video containers.
- Timestamped segments with optional speaker/diarization labels.
- Streaming per-chunk progress and partial transcript display.
- In-app recording capture as a transcription source.
- Editable transcript with segment-to-audio playback sync.
- One-click handoff to Notes Builder and indexing into Global Search.

**UX.** A drop zone accepts files or a record button captures live audio; a progress bar shows chunk-by-chunk transcription while text fills in. The finished transcript renders as clickable timestamped segments with an inline audio player and an edit mode.

**Architecture.** New `src/studio/transcription/` module shells out to a bundled Whisper.cpp/faster-whisper binary and ffmpeg, running jobs on a background worker queue. Transcripts, segments, and job status persist to SQLite; audio files are stored in a local media directory. Progress and completion stream over Tauri IPC events; output is registered with the search indexer.

**Dependencies.** Global Search, Logs & Traces.

**Effort.** ~4 person-weeks.

**Risks.**

- Model download size and first-run setup friction for larger Whisper models.
- Transcription latency on CPU-only machines for long files.
- Diarization accuracy is limited without heavier local models.

**Acceptance criteria.**

- Importing a common audio/video file produces a timestamped transcript.
- Users can choose a Whisper model size and see the accuracy/speed trade-off.
- Progress streams per chunk and partial text appears during processing.
- Clicking a segment seeks the audio player to that timestamp.
- Edited transcripts persist and are findable via Global Search.
- A transcript can be sent to Notes Builder in one action.

## 6. YouTube to Notes (P2, M)

**Overview.** YouTube to Notes takes a video URL, uses yt-dlp to fetch the audio stream (and any available captions) locally, then either parses existing captions or runs the audio through the Audio Transcription pipeline. The resulting transcript is passed to Notes Builder to produce structured, sectioned notes with timestamps and key takeaways. Everything downloads to and processes on the user's machine, so there is no third-party transcription or summarization service in the loop. Source metadata (title, channel, duration, URL) is captured for citation and later search.

**User value.** Creators and researchers convert long videos into skimmable, timestamped notes in one paste, without watching the whole thing or using a paid summarizer. It captures learning from video into a searchable local library.

**Capabilities.**

- yt-dlp-based local fetch of audio stream and available caption tracks.
- Caption-first path with fallback to local Whisper transcription.
- Video metadata capture (title, channel, duration, URL) for citation.
- Automatic handoff to Notes Builder for structured, timestamped notes.
- Key-takeaway and section extraction with source timestamps.
- Indexing of notes and transcript into Global Search.
- Batch queue for multiple URLs.

**UX.** A single URL input with a fetch button shows download and processing progress, then reveals the transcript and generated notes side by side. Notes sections link back to source timestamps, and the video's metadata is shown as a citation header.

**Architecture.** New `src/studio/youtube/` module invokes yt-dlp as a subprocess on a background worker, reusing the transcription and notes modules downstream. Downloads land in the local media directory; transcripts, notes, and video metadata persist to SQLite. Progress streams over IPC; outputs register with the search indexer. Only user-initiated URLs are fetched — no autonomous downloading.

**Dependencies.** Audio Transcription, Notes Builder.

**Effort.** ~3 person-weeks.

**Risks.**

- yt-dlp breakage from upstream site changes requires periodic updates.
- Legal/ToS considerations around downloading video content.
- Long videos strain CPU transcription when captions are unavailable.

**Acceptance criteria.**

- Pasting a valid URL fetches audio/captions locally with visible progress.
- When captions exist they are used; otherwise Whisper transcription runs.
- Generated notes are sectioned with takeaways linked to source timestamps.
- Video metadata is captured and displayed as a citation.
- Notes and transcript are searchable via Global Search.
- Multiple URLs can be queued and processed sequentially.

## 7. Notes Builder (P2, S-M)

**Overview.** Notes Builder is the summarization and structuring engine of the Studio category: given any input (a transcript, an existing Dobby document, pasted text, or extracted web text), it uses the local LLM to produce well-organized notes with headings, bullet summaries, key takeaways, and optional action items. Users pick a note template (meeting notes, study notes, article summary, decision log) and the model fills it, preserving source references and timestamps where present. Notes live in a dedicated local store, are fully editable in a Markdown editor, and are indexed for Global Search. It is the shared downstream target for Audio Transcription and YouTube to Notes.

**User value.** Builders convert raw, messy input into structured knowledge they can actually reuse, in seconds, without leaving the app or exposing content to a cloud model. Templates make the output immediately usable.

**Capabilities.**

- Multi-source ingestion (transcript, document, pasted text, extracted URL text).
- Template-driven structuring (meeting/study/article/decision-log).
- Local-LLM generation of headings, summaries, takeaways, and action items.
- Source-reference and timestamp preservation in output.
- Markdown editor for post-generation editing.
- Local note store with tagging and project association.
- Indexing into Global Search and re-generation with a different template.

**UX.** A composer screen lets the user pick or paste a source and choose a note template, then streams the generated notes into an editable Markdown pane. A sidebar lists saved notes by project and tag for quick reopening.

**Architecture.** New `src/studio/notes/` module orchestrates local LLM calls via the existing Ollama/llama.cpp client with template prompts stored as versioned assets. Notes persist to SQLite with tags and project links; generation streams over IPC and emits spans to Logs & Traces. Outputs register with the search indexer; templates are extensible.

**Dependencies.** Global Search, Logs & Traces.

**Effort.** ~3 person-weeks.

**Risks.**

- Summary quality varies with the local model's capability and context window.
- Long sources may need chunked map-reduce summarization to fit context.
- Template rigidity may not fit every note type.

**Acceptance criteria.**

- Generating notes from a transcript yields correctly structured template output.
- Long inputs are chunked and summarized without exceeding model context.
- Generated notes retain source references/timestamps where available.
- Notes are editable in Markdown and persist across sessions.
- Notes are searchable via Global Search and taggable.
- Re-running with a different template produces correspondingly restructured notes.

---

# Generate

## 11. Prototype Builder + Test (P4, XL)

**Overview.** Prototype Builder turns a Dobby spec (PRD, backlog, or prompt) into a runnable prototype: it scaffolds a project, generates code with the local LLM, installs dependencies and runs a dev server through the sandboxed terminal, and previews the app in an embedded WebView. An iterative generate-run-fix loop uses build/test output and Logs & Traces to self-correct, and an auto-test step generates and runs smoke/UI tests against the preview. The whole loop runs on-device, letting builders go from idea and spec to a clickable, tested prototype without cloud build services.

**User value.** Founders and developers see their idea running as a real, testable app minutes after specifying it — closing the gap between document and working software entirely on their own machine.

**Capabilities.**

- Spec-to-scaffold generation from PRD/backlog/prompt via local LLM.
- Dependency install and dev-server launch through the sandboxed terminal.
- Embedded WebView live preview of the running prototype.
- Iterative generate-run-fix loop driven by build/test output.
- Auto-generated smoke/UI tests executed against the preview.
- Trace-integrated debugging of each generation and fix step.
- Export of the generated project to disk.

**UX.** A builder screen shows the source spec, a streaming code/generation log, and a live app preview pane side by side, with a status timeline of scaffold, install, run, test, and fix iterations. Users can trigger a re-generate, view failing tests, and export the project.

**Architecture.** New `src/generators/prototype/` module orchestrates a generate-run-fix loop that emits code to a project directory, drives installs/dev-server via the Embedded Terminal, and renders the running app in a Tauri WebView; UI tests run via a local headless driver. State and iterations persist to SQLite and emit spans to Logs & Traces. All model calls use the local LLM; nothing is built in the cloud.

**Dependencies.** Embedded Terminal, Logs & Traces, Control Center, Flow Builder.

**Effort.** ~12 person-weeks.

**Risks.**

- Local models may produce non-building code, making the fix loop slow or stuck.
- Sandboxing a live dev server and preview securely is complex.
- Long generate-run-fix loops consume significant local compute and time.

**Acceptance criteria.**

- A spec generates a scaffolded project that installs and starts a dev server.
- The running prototype renders in the embedded preview pane.
- The generate-run-fix loop uses build errors to attempt corrections.
- Auto-generated smoke tests run against the preview and report pass/fail.
- All build commands run through the approval-gated sandboxed terminal.
- The generated project can be exported to disk and run standalone.

## 12. Video Generation (P4, L)

**Overview.** Video Generation (in Studio/Generate) turns a script, notes, or document into a rendered video: it segments the script into scenes, generates or selects visuals (slides, diagrams, or local image-model frames) per scene, synthesizes narration with a local TTS engine (e.g. Piper), and assembles the timeline with captions using a bundled ffmpeg. Users can preview and re-order scenes, swap voices, and tweak timing before rendering the final MP4. Because rendering, TTS, and assembly all run locally, creators can produce explainer or summary videos without cloud video/voice services.

**User value.** Technical creators turn written content into publishable video without a studio or cloud render pipeline, cutting production from hours to minutes while keeping full local control.

**Capabilities.**

- Script/notes-to-scene segmentation via local LLM.
- Per-scene visual generation or selection (slides, diagrams, local image model).
- Local TTS narration with selectable voices (e.g. Piper).
- Auto-generated synchronized captions.
- Scene reordering, timing, and voice adjustment in a timeline editor.
- ffmpeg-based assembly and MP4 export at selectable resolution.
- Trace-logged, resumable render jobs.

**UX.** A storyboard view lists scenes with their visual, narration text, and duration, editable inline and reorderable by drag. A preview player scrubs the assembled timeline, and a render button produces the final MP4 with a progress bar.

**Architecture.** New `src/generators/video/` (Studio) module segments scripts via the local LLM, calls a local TTS binary (Piper) and optional local image model for visuals, and assembles output with a bundled ffmpeg on a background render queue. Scenes, assets, and jobs persist to SQLite and a media directory; render progress streams over IPC and emits spans to Logs & Traces.

**Dependencies.** Notes Builder, Logs & Traces.

**Effort.** ~8 person-weeks.

**Risks.**

- Local image/visual generation quality and speed on consumer hardware.
- Audio/video sync drift during ffmpeg assembly.
- Large render jobs consume significant disk and CPU/GPU.

**Acceptance criteria.**

- A script is segmented into editable scenes with narration and visuals.
- Local TTS produces narration audio per scene with a selectable voice.
- Captions are generated and stay synchronized with narration.
- Scenes can be reordered and re-timed before rendering.
- Rendering produces a playable MP4 with synced audio, visuals, and captions.
- Render jobs are trace-logged and resumable after interruption.

---

# Marketplace

## 13. Local App Marketplace (P5–P6, XL)

**Overview.** The Marketplace lets builders extend Dobby by installing packaged skills, flows, and mini-apps. Each package ships a signed manifest declaring its contents, required permissions/tool grants, and compatibility, and installs into a sandboxed plugin runtime governed by Control Center. In P5 the catalog is local-first — install from files, folders, or a local registry, with full permission review before install and one-click enable/disable/uninstall. In P6 it connects to a shared cloud catalog for discovery, publishing, versioned updates, and monetization rails, while keeping installed packages running on-device. This is what turns Dobby from an app into an extensible platform.

**User value.** Builders get instant capabilities from a growing ecosystem without building everything themselves, and creators can package and share (later sell) their skills and flows. It makes the workbench extensible and community-powered.

**Capabilities.**

- Signed package manifest declaring contents, permissions, and compatibility.
- Permission review screen shown before install with explicit grant approval.
- Sandboxed plugin runtime for installed skills/flows/apps, governed by Control Center.
- Local-first install from file/folder/registry with enable/disable/uninstall.
- Versioned updates with changelog and rollback.
- Dependency resolution between packages and Dobby version compatibility checks.
- P6: shared cloud catalog for discovery, publishing, and monetization rails.
- Developer SDK and packaging CLI for authoring distributable packages.

**UX.** A gallery of installable packages with categories, search, and detail pages showing the manifest and requested permissions; installing opens a permission-review dialog before enabling. An Installed tab manages enable/disable, updates, and removal.

**Architecture.** New `src/marketplace/` module defines a package manifest + signature scheme, an installer that verifies signatures and writes into a sandboxed plugin directory, and a runtime loader that registers packaged skills/flows/apps under Control Center permission policies. Local catalog metadata lives in SQLite; P6 adds a cloud catalog client for discovery, publishing, and update checks while execution stays on-device. Packages run sandboxed with only their granted tools.

**Dependencies.** Skill Builder, Flow Builder, Control Center, Prototype Builder + Test.

**Effort.** ~14 person-weeks.

**Risks.**

- Malicious or over-permissioned packages if sandboxing/signing is weak.
- Manifest/compatibility versioning across Dobby releases causes breakage.
- Cloud publishing (P6) introduces trust, moderation, and monetization complexity.

**Acceptance criteria.**

- A signed local package installs after an explicit permission-review approval.
- Installed skills/flows/apps run sandboxed with only their granted tools.
- Packages can be enabled, disabled, updated, rolled back, and uninstalled.
- Manifest signature verification rejects tampered or unsigned packages.
- Dobby-version and dependency compatibility are checked before install.
- P6 cloud catalog supports discovery and publishing while execution stays local.
